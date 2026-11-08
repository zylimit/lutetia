# risk: high
"""部署 bug 红锁：建表脚本必须随包安装（pip install . 后可定位），migrate 对空目录不得静默成功。"""
import os
from importlib import resources
from pathlib import Path

import asyncpg
import pytest

import lutetia
import lutetia.cli
from lutetia.config import load_dotenv
from lutetia.db import Database

load_dotenv()
DB_URL = os.environ.get("DATABASE_URL", "")

EXPECTED = ["001_schema.sql", "002_raw_jsonb_fix.sql", "003_poi.sql", "004_backup_run.sql",
            "005_readonly_status_events.sql"]


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


def test_sql_files_are_package_data():
    root = resources.files("lutetia")
    for name in EXPECTED:
        assert root.joinpath("sql/" + name).is_file(), "包内缺 lutetia/sql/%s" % name


def test_cli_sql_dir_points_inside_package():
    pkg_sql = Path(lutetia.__file__).resolve().parent / "sql"
    assert lutetia.cli.SQL_DIR == pkg_sql
    assert pkg_sql.is_dir()
    assert sorted(p.name for p in pkg_sql.glob("*.sql")) == EXPECTED


async def test_migrate_refuses_empty_dir(db, tmp_path):
    with pytest.raises(SystemExit):
        await db.migrate(tmp_path)


async def test_migrate_applies_package_sql_in_order(db):
    # 必须是包内目录（pip install 后仍存在），不是仓库根 sql/
    assert Path(lutetia.cli.SQL_DIR).resolve() == Path(lutetia.__file__).resolve().parent / "sql"
    applied = await db.migrate(lutetia.cli.SQL_DIR)
    assert list(applied) == EXPECTED


async def _schema_snapshot(db):
    async with db.pool.acquire() as conn:
        cols = await conn.fetch(
            "SELECT table_name, column_name, data_type, is_nullable, column_default "
            "FROM information_schema.columns WHERE table_schema = 'public' ORDER BY 1, ordinal_position"
        )
        idx = await conn.fetch("SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' ORDER BY 1, 2")
        cons = await conn.fetch(
            "SELECT conrelid::regclass::text AS t, conname, pg_get_constraintdef(oid) AS d FROM pg_constraint "
            "WHERE connamespace = 'public'::regnamespace ORDER BY 1, 2"
        )
    return [tuple(r) for r in cols], [tuple(r) for r in idx], [tuple(r) for r in cons]


async def test_migrate_twice_leaves_schema_unchanged_and_backup_run_exists(db):
    await db.migrate(lutetia.cli.SQL_DIR)
    first = await _schema_snapshot(db)
    await db.migrate(lutetia.cli.SQL_DIR)
    second = await _schema_snapshot(db)
    assert first == second
    names = {c[0] for c in second[0]}
    assert "backup_run" in names
    backup_cols = {c[1] for c in second[0] if c[0] == "backup_run"}
    assert {"started_at", "finished_at", "ok", "kind", "object_key", "bytes", "sha256", "row_counts", "row_counts_after", "error"} <= backup_cols
    assert any(i[0] == "backup_run" and "finished_at DESC" in i[2] for i in second[1])


async def test_backup_run_rejects_unknown_kind(db):
    await db.migrate(lutetia.cli.SQL_DIR)
    async with db.pool.acquire() as conn:
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute("INSERT INTO backup_run (started_at, ok, kind) VALUES (now(), true, 'monthly')")
