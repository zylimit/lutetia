# risk: high
"""Phase 6 Task 6.2: backup status on the ops dashboard (pure anomaly rules + backup_summary + overview JSON)."""
import dataclasses
import os
from datetime import datetime, timedelta, timezone

import pytest
from aiohttp.test_utils import TestClient, TestServer

from lutetia.config import Config, load_dotenv
from lutetia.db import Database
from lutetia.web import WebServer, anomalies
from lutetia.web.i18n import t

load_dotenv()
DB_URL = os.environ.get("DATABASE_URL", "")
PWD = "pw-test"
NOW = datetime(2026, 11, 9, 3, 0, 0, tzinfo=timezone.utc)


def summary(last_ok_h=None, latest_ok=True, error=None):
    last = NOW - timedelta(hours=last_ok_h) if last_ok_h is not None else None
    return {"last_ok_at": last, "last_ok_bytes": 1048576 if last else None,
            "latest_ok": latest_ok if last or latest_ok is False else None, "latest_at": last, "latest_error": error}


def compute(bk):
    return anomalies.compute(NOW, [], [], [], None, [], 1400, 3.4, backup=bk)


def test_never_backed_up_is_red():
    items = compute(summary(None, latest_ok=None))
    assert [(i["level"], i["kind"], i["detail"]) for i in items] == [("red", "backup", "no successful backup yet")]


def test_success_25h_ago_no_item():
    assert compute(summary(25)) == []


def test_success_27h_ago_red_with_hours_and_threshold():
    items = compute(summary(27))
    assert len(items) == 1 and items[0]["level"] == "red" and items[0]["kind"] == "backup"
    assert items[0]["detail"] == "27.0 h since the last successful backup (limit 26 h)"


def test_latest_run_failed_after_earlier_success_is_red_with_error():
    # yesterday 02:30 ok (24 h ago, still fresh), today's run failed: must be red despite the fresh success
    items = compute(summary(24, latest_ok=False, error="dump exit 1"))
    assert len(items) == 1 and items[0]["level"] == "red"
    assert items[0]["detail"] == "latest backup failed: dump exit 1"
    assert t("en", "kind.backup") == "Backup" and t("fr", "kind.backup") == "Sauvegarde"


def test_compute_without_backup_has_no_backup_items():
    assert compute(None) == []


@pytest.fixture
async def db():
    if not DB_URL:
        pytest.skip("DATABASE_URL not set")
    d = Database(DB_URL)
    try:
        await d.connect()
    except Exception as e:  # noqa: BLE001
        pytest.skip("database unreachable: %s" % e)
    yield d
    await d.close()


async def test_backup_summary_reads_newest_ok_and_newest_run(db):
    base = datetime(2099, 1, 1, tzinfo=timezone.utc)  # newer than any real row
    ids = []
    try:
        async with db.pool.acquire() as conn:
            for off, ok, size, err in ((0, True, 111, None), (1, False, None, "upload exit 2")):
                t = base + timedelta(days=off)
                ids.append(await conn.fetchval(
                    "INSERT INTO backup_run (started_at, finished_at, ok, kind, bytes, error) VALUES ($1, $1, $2, 'daily', $3, $4) RETURNING id",
                    t, ok, size, err))
        s = await db.backup_summary()
        assert s["last_ok_at"] == base and s["last_ok_bytes"] == 111
        assert s["latest_ok"] is False and s["latest_at"] == base + timedelta(days=1) and s["latest_error"] == "upload exit 2"
    finally:
        async with db.pool.acquire() as conn:
            await conn.execute("DELETE FROM backup_run WHERE id = ANY($1::bigint[])", ids)


async def test_overview_includes_last_backup(db):
    cfg = dataclasses.replace(Config.from_env(), dashboard_pwd=PWD, api_key="k-test", dashboard_host="127.0.0.1")
    app = WebServer(cfg, db, datetime.now(timezone.utc)).build_app()
    async with TestClient(TestServer(app)) as client:
        await client.post("/login", data={"username": "admin", "password": PWD, "next": ""}, allow_redirects=False)
        async with db.pool.acquire() as conn:  # newest row failed -> latest_ok must be False
            rid = await conn.fetchval(
                "INSERT INTO backup_run (started_at, finished_at, ok, kind, bytes, error) VALUES ($1, $1, FALSE, 'daily', NULL, 'upload exit 2') RETURNING id",
                datetime(2099, 1, 1, tzinfo=timezone.utc))
        try:
            body = await (await client.get("/dashboard/data/overview")).json()
            assert set(body["last_backup"]) == {"at", "bytes", "latest_ok", "latest_at"}
            assert body["last_backup"]["latest_ok"] is False
            html = await (await client.get("/dashboard/")).text()
            assert 'id="last-backup"' in html and "Last backup:" in html
        finally:
            async with db.pool.acquire() as conn:
                await conn.execute("DELETE FROM backup_run WHERE id = $1", rid)
