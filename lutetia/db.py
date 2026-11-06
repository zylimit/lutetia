import asyncio
import json
import logging
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


def is_transient_db_error(e: BaseException) -> bool:
    # client-side asyncpg DataError subclasses both InterfaceError and ValueError: not transient
    return isinstance(e, TRANSIENT_DB_ERRORS) and not isinstance(e, ValueError)


def ms_to_dt(ms: Optional[int]) -> Optional[datetime]:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


async def _init_conn(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


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
        applied = []
        async with self.pool.acquire() as conn:
            for f in sorted(Path(sql_dir).glob("*.sql")):
                await conn.execute(f.read_text(encoding="utf-8"))
                applied.append(f.name)
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
