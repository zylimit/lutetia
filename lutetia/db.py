import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, TypeVar

import asyncpg

from .models import Attribute, Device, GpsPosition, Telemetry

log = logging.getLogger(__name__)

T = TypeVar("T")

# Only connection-class faults are transient; data errors (server DataError, client-side encode errors) are not.
# asyncio.TimeoutError is listed explicitly: on Python 3.9 it is not an OSError.
TRANSIENT_DB_ERRORS = (OSError, asyncio.TimeoutError, asyncpg.PostgresConnectionError,
                       asyncpg.OperatorInterventionError, asyncpg.InsufficientResourcesError,
                       asyncpg.InterfaceError)  # ConnectionError is an OSError


def scram_sha256_verifier(password: str, salt: Optional[bytes] = None, iterations: int = 4096) -> str:
    """PostgreSQL SCRAM-SHA-256 verifier (RFC 5802/7677). Stored pre-hashed, so the plaintext never reaches server SQL/logs."""
    salt = os.urandom(16) if salt is None else salt
    salted = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted, b"Server Key", hashlib.sha256).digest()
    b64 = lambda b: base64.b64encode(b).decode("ascii")  # noqa: E731
    return "SCRAM-SHA-256$%d:%s$%s:%s" % (iterations, b64(salt), b64(stored_key), b64(server_key))


def is_transient_db_error(e: BaseException) -> bool:
    # client-side asyncpg DataError subclasses both InterfaceError and ValueError: not transient
    return isinstance(e, TRANSIENT_DB_ERRORS) and not isinstance(e, ValueError)


def ms_to_dt(ms: Optional[int]) -> Optional[datetime]:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


async def _init_conn(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


def max_age_hours(default_hours: float, upload_interval_h: Optional[float]) -> float:
    """STALE threshold: a sensor that uploads every N hours is only stale after 2N hours."""
    return max(default_hours, 2 * (upload_interval_h or 0))


class Database:
    def __init__(self, url: str):
        self.url = url
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self) -> None:
        self.pool = await asyncpg.create_pool(self.url, min_size=1, max_size=5, init=_init_conn)

    async def close(self) -> None:
        if self.pool:
            await self.pool.close()

    async def migrate(self, sql_dir: Path) -> List[str]:
        files = sorted(Path(sql_dir).glob("*.sql")) if Path(sql_dir).is_dir() else []
        if not files:
            raise SystemExit("no migration files found in %s" % sql_dir)
        applied = []
        async with self.pool.acquire() as conn:
            for f in files:
                await conn.execute(f.read_text(encoding="utf-8"))
                applied.append(f.name)
            ro_password = os.environ.get("DATABASE_RO_PASSWORD", "")
            if ro_password:
                # 明文不进服务端语句：Python 侧算 SCRAM verifier，ALTER ROLE 不支持绑定参数，经 quote_literal 拼字面量
                literal = await conn.fetchval("SELECT quote_literal($1::text)", scram_sha256_verifier(ro_password))
                await conn.execute("ALTER ROLE lutetia_ro LOGIN PASSWORD %s" % literal)
                log.info("ro password set")
        return applied

    # --- devices -----------------------------------------------------------
    async def upsert_devices(self, devices: Sequence[Device]) -> None:
        if not devices:
            return
        async with self.pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO device (source, device_id, name, device_type, expected_online, extra)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (source, device_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    device_type = EXCLUDED.device_type,
                    expected_online = COALESCE(EXCLUDED.expected_online, device.expected_online),
                    extra = EXCLUDED.extra,
                    updated_at = now()
                """,
                [(d.source, d.device_id, d.name, d.device_type, d.expected_online, d.extra) for d in devices],
            )

    async def set_expected_online(self, source: str, device_id: str, flag: Optional[bool]) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE device SET expected_online = $3, updated_at = now() WHERE source = $1 AND device_id = $2",
                source, device_id, flag,
            )

    async def list_device_ids(self, source: str) -> List[str]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT device_id FROM device WHERE source = $1 ORDER BY device_id", source)
        return [r["device_id"] for r in rows]

    async def _insert_skipping_poison(self, rows: Sequence[T], insert_batch: Callable[[Sequence[T]], Awaitable[int]],
                                      describe: Callable[[T], str]) -> int:
        """Whole batch first; on a non-transient error fall back to row by row and drop only the rows that still fail.
        Transient errors (connection class) propagate untouched so the caller's retry takes over."""
        if not rows:
            return 0
        try:
            return await insert_batch(rows)
        except Exception as e:
            if is_transient_db_error(e):
                raise
            log.warning("insert batch of %d rows failed (%s: %s), retrying row by row", len(rows), type(e).__name__, e)
        inserted = 0
        for r in rows:
            try:
                inserted += await insert_batch([r])
            except Exception as e:
                if is_transient_db_error(e):
                    raise
                log.warning("dropped row %s: %s: %s", describe(r), type(e).__name__, e)
        return inserted

    # --- gps ---------------------------------------------------------------
    async def insert_gps_positions(self, rows: Sequence[GpsPosition]) -> int:
        """Idempotent batch insert; returns the number of rows actually inserted.
        A poison row (non-transient error) is skipped with a warning instead of failing the whole batch."""
        return await self._insert_skipping_poison(
            rows, self._insert_gps_batch,
            lambda r: "device_id=%s update_time=%s" % (r.device_id, getattr(ms_to_dt(r.update_time), "isoformat", lambda: None)()))

    async def _insert_gps_batch(self, rows: Sequence[GpsPosition]) -> int:
        cols = list(zip(*[(
            r.device_id, ms_to_dt(r.update_time), ms_to_dt(r.device_time), ms_to_dt(r.arrived_time),
            r.lat, r.lon, r.speed_raw, r.course, r.altitude, r.total_distance, r.status, r.alarm,
            r.strstatus, r.stralarm, r.moving, r.temp1, r.temp2, r.temp3, r.temp4, r.origin, r.raw,
        ) for r in rows]))
        async with self.pool.acquire() as conn:
            inserted = await conn.fetch(
                """
                INSERT INTO gps_position (device_id, update_time, device_time, arrived_time, lat, lon, speed_raw,
                    course, altitude, total_distance, status, alarm, strstatus, stralarm, moving,
                    temp1, temp2, temp3, temp4, origin, raw)
                SELECT * FROM unnest(
                    $1::text[], $2::timestamptz[], $3::timestamptz[], $4::timestamptz[],
                    $5::float8[], $6::float8[], $7::float8[], $8::int[], $9::float8[], $10::float8[],
                    $11::bigint[], $12::bigint[], $13::text[], $14::text[], $15::smallint[],
                    $16::int[], $17::int[], $18::int[], $19::int[], $20::text[], $21::jsonb[])
                ON CONFLICT (device_id, update_time) DO NOTHING
                RETURNING 1
                """,
                *[list(c) for c in cols],
            )
        return len(inserted)

    # --- sensors -----------------------------------------------------------
    async def insert_telemetry(self, rows: Sequence[Telemetry]) -> int:
        return await self._insert_skipping_poison(
            rows, self._insert_telemetry_batch,
            lambda r: "device_id=%s key=%s ts=%s" % (r.device_id, r.key, getattr(ms_to_dt(r.ts), "isoformat", lambda: None)()))

    async def _insert_telemetry_batch(self, rows: Sequence[Telemetry]) -> int:
        cols = list(zip(*[(r.device_id, r.key, ms_to_dt(r.ts), r.value_num, r.value_str, r.origin) for r in rows]))
        async with self.pool.acquire() as conn:
            inserted = await conn.fetch(
                """
                INSERT INTO sensor_telemetry (device_id, key, ts, value_num, value_str, origin)
                SELECT * FROM unnest($1::text[], $2::text[], $3::timestamptz[], $4::float8[], $5::text[], $6::text[])
                ON CONFLICT (device_id, key, ts) DO NOTHING
                RETURNING 1
                """,
                *[list(c) for c in cols],
            )
        return len(inserted)

    async def upsert_attributes(self, rows: Sequence[Attribute]) -> None:
        if not rows:
            return
        async with self.pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO sensor_attribute (device_id, key, value, last_update_ts)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (device_id, key) DO UPDATE SET value = EXCLUDED.value, last_update_ts = EXCLUDED.last_update_ts
                """,
                [(a.device_id, a.key, a.value, ms_to_dt(a.last_update_ts)) for a in rows],
            )

    # --- bookkeeping -------------------------------------------------------
    async def record_api_call(self, source: str, action: str, ok: bool) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute("INSERT INTO api_call (source, action, ok) VALUES ($1, $2, $3)", source, action, ok)

    async def api_calls_since(self, source: str, since: datetime, action: Optional[str] = None) -> int:
        async with self.pool.acquire() as conn:
            if action:
                return await conn.fetchval(
                    "SELECT count(*) FROM api_call WHERE source = $1 AND called_at >= $2 AND action = $3", source, since, action)
            return await conn.fetchval("SELECT count(*) FROM api_call WHERE source = $1 AND called_at >= $2", source, since)

    async def device_status(self) -> List[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT d.source, d.device_id, d.name, d.device_type, d.expected_online,
                       GREATEST(g.last_ts, t.last_ts) AS last_ts,
                       NULLIF(regexp_replace(ui.value, '[^0-9.]', '', 'g'), '')::float AS upload_interval_h
                FROM device d
                LEFT JOIN sensor_attribute ui ON ui.device_id = d.device_id AND ui.key = 'uploadInterval'
                LEFT JOIN (SELECT device_id, max(update_time) AS last_ts FROM gps_position GROUP BY device_id) g
                       ON g.device_id = d.device_id AND d.source = 'gps51'
                LEFT JOIN (SELECT device_id, max(ts) AS last_ts FROM sensor_telemetry GROUP BY device_id) t
                       ON t.device_id = d.device_id AND d.source = 'dingtek'
                ORDER BY d.source, d.name
                """
            )
        return [dict(r) for r in rows]

    async def call_summary(self, hours: int = 24) -> List[Dict[str, Any]]:
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT source, action, count(*) AS n FROM api_call WHERE called_at >= $1 GROUP BY source, action ORDER BY source, action",
                since,
            )
        return [dict(r) for r in rows]

    async def backup_summary(self) -> Dict[str, Any]:
        """Newest successful backup and the newest run overall (read-only; table is tiny, one row per day)."""
        async with self.pool.acquire() as conn:
            ok = await conn.fetchrow("SELECT finished_at, bytes FROM backup_run WHERE ok ORDER BY finished_at DESC NULLS LAST LIMIT 1")
            latest = await conn.fetchrow("SELECT finished_at, ok, error FROM backup_run ORDER BY finished_at DESC NULLS LAST LIMIT 1")
        return {"last_ok_at": ok["finished_at"] if ok else None, "last_ok_bytes": ok["bytes"] if ok else None,
                "latest_ok": latest["ok"] if latest else None, "latest_at": latest["finished_at"] if latest else None,
                "latest_error": latest["error"] if latest else None}

    async def latest_sensor_values(self, keys: Sequence[str]) -> List[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT d.device_id, d.name, k.key, t.value_si, t.value_num, t.value_str, t.ts
                FROM device d CROSS JOIN unnest($1::text[]) AS k(key)
                CROSS JOIN LATERAL (
                    SELECT value_si, value_num, value_str, ts FROM sensor_telemetry_v t
                    WHERE t.device_id = d.device_id AND t.key = k.key ORDER BY ts DESC LIMIT 1
                ) t
                WHERE d.source = 'dingtek'
                """,
                list(keys),
            )
        return [dict(r) for r in rows]

    async def latest_alarm_values(self, keys: Sequence[str]) -> List[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT d.device_id, d.name, k.key, t.value_num, t.ts
                FROM device d CROSS JOIN unnest($1::text[]) AS k(key)
                CROSS JOIN LATERAL (
                    SELECT value_num, ts FROM sensor_telemetry_v t
                    WHERE t.device_id = d.device_id AND t.key = k.key ORDER BY ts DESC LIMIT 1
                ) t
                WHERE d.source = 'dingtek'
                """,
                list(keys),
            )
        return [dict(r) for r in rows]

    async def latest_gps_positions(self) -> List[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                WITH RECURSIVE ids AS (
                    SELECT min(device_id) AS device_id FROM gps_position
                    UNION ALL
                    SELECT (SELECT min(device_id) FROM gps_position WHERE device_id > ids.device_id)
                    FROM ids WHERE ids.device_id IS NOT NULL
                )
                SELECT ids.device_id, d.name, p.update_time, p.lat, p.lon, p.speed_kmh, p.speed_raw, p.origin, p.moving, p.total_distance_km
                FROM ids LEFT JOIN device d ON d.device_id = ids.device_id AND d.source = 'gps51'
                CROSS JOIN LATERAL (
                    SELECT update_time, lat, lon, speed_kmh, speed_raw, origin, moving, total_distance_km FROM gps_position_v p
                    WHERE p.device_id = ids.device_id ORDER BY update_time DESC LIMIT 1
                ) p
                WHERE ids.device_id IS NOT NULL
                ORDER BY ids.device_id
                """
            )
        return [dict(r) for r in rows]

    async def manhole_locations(self) -> List[Dict[str, Any]]:
        # regex-filter in a subquery before the cast; <=3 integer digits and <=12 decimals cannot overflow double precision
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT d.device_id, d.name, la.v AS lat, lo.v AS lon
                FROM device d
                JOIN (SELECT device_id, value::double precision AS v FROM
                        (SELECT device_id, value FROM sensor_attribute
                         WHERE key = 'latitude' AND value ~ '^-?[0-9]{1,3}(\\.[0-9]{1,12})?$' OFFSET 0) f) la
                  ON la.device_id = d.device_id
                JOIN (SELECT device_id, value::double precision AS v FROM
                        (SELECT device_id, value FROM sensor_attribute
                         WHERE key = 'longitude' AND value ~ '^-?[0-9]{1,3}(\\.[0-9]{1,12})?$' OFFSET 0) f) lo
                  ON lo.device_id = d.device_id
                WHERE d.source = 'dingtek' AND la.v BETWEEN -90 AND 90 AND lo.v BETWEEN -180 AND 180
                ORDER BY d.name, d.device_id
                """
            )
        return [dict(r) for r in rows]

    async def list_devices(self) -> List[Dict[str, Any]]:
        keep = ("source", "device_id", "name", "device_type", "expected_online", "last_ts")
        return [{k: r[k] for k in keep} for r in await self.device_status()]

    async def query_positions(self, device_id: str, since: Optional[datetime], until: Optional[datetime],
                              limit: int) -> List[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT device_id, update_time, device_time, arrived_time, lat, lon, speed_kmh, speed_raw, course,
                       altitude, total_distance_km, moving, temp1_c, origin
                FROM gps_position_v
                WHERE device_id = $1 AND ($2::timestamptz IS NULL OR update_time >= $2)
                  AND ($3::timestamptz IS NULL OR update_time <= $3)
                ORDER BY update_time DESC LIMIT $4
                """,
                device_id, since, until, limit,
            )
        return [dict(r) for r in rows]

    async def query_telemetry(self, device_id: str, key: Optional[str], since: Optional[datetime],
                              until: Optional[datetime], limit: int) -> List[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT device_id, key, ts, value_si, value_num, value_str, origin
                FROM sensor_telemetry_v
                WHERE device_id = $1 AND ($2::text IS NULL OR key = $2)
                  AND ($3::timestamptz IS NULL OR ts >= $3) AND ($4::timestamptz IS NULL OR ts <= $4)
                ORDER BY ts DESC LIMIT $5
                """,
                device_id, key, since, until, limit,
            )
        return [dict(r) for r in rows]

    async def telemetry_series(self, device_id: str, keys: Sequence[str], days: int, hourly: bool) -> List[Dict[str, Any]]:
        """Read-only chart series; up to 1501 newest rows per key so the caller can detect truncation."""
        if hourly:
            inner = ("SELECT key, date_trunc('hour', ts) AS ts, avg(value_si) AS value_si FROM sensor_telemetry_v "
                     "WHERE device_id = $1 AND key = $2 AND ts >= now() - make_interval(days => $3) GROUP BY key, 2 "
                     "ORDER BY 2 DESC LIMIT 1501")
        else:
            inner = ("SELECT key, ts, value_si FROM sensor_telemetry_v "
                     "WHERE device_id = $1 AND key = $2 AND ts >= now() - make_interval(days => $3) "
                     "ORDER BY ts DESC LIMIT 1501")
        out: List[Dict[str, Any]] = []
        async with self.pool.acquire() as conn:
            for key in keys:
                rows = await conn.fetch("SELECT * FROM (" + inner + ") s ORDER BY ts", device_id, key, days)
                out.extend(dict(r) for r in rows)
        return out

    async def positions_recent(self, device_id: str, days: int, limit: int) -> List[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT update_time, lat, lon, speed_kmh, moving, origin
                FROM gps_position_v
                WHERE device_id = $1 AND update_time >= now() - make_interval(days => $2)
                ORDER BY update_time DESC LIMIT $3
                """,
                device_id, days, limit,
            )
        return [dict(r) for r in rows]

    async def positions_thinned(self, device_id: str, days: int, bucket_sec: int, limit: int) -> List[Dict[str, Any]]:
        """近 days 天轨迹按 bucket_sec 秒一格抽稀，每格留最新一点；倒序，limit 兜底取最新的格。"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT DISTINCT ON (bucket) update_time, lat, lon, speed_kmh, moving, origin
                FROM (
                    SELECT update_time, lat, lon, speed_kmh, moving, origin,
                           floor(extract(epoch FROM update_time) / $3::int) AS bucket
                    FROM gps_position_v
                    WHERE device_id = $1 AND update_time >= now() - make_interval(days => $2)
                ) s
                ORDER BY bucket DESC, update_time DESC LIMIT $4
                """,
                device_id, days, bucket_sec, limit,
            )
        return [dict(r) for r in rows]

    async def get_device(self, source: str, device_id: str) -> Optional[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT source, device_id, name, device_type, expected_online, extra, updated_at "
                "FROM device WHERE source = $1 AND device_id = $2", source, device_id)
        return dict(row) if row else None

    async def device_attributes(self, device_id: str) -> List[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT key, value, last_update_ts FROM sensor_attribute WHERE device_id = $1 ORDER BY key", device_id)
        return [dict(r) for r in rows]
