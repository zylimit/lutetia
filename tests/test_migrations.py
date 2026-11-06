# risk: high
"""部署 bug 红锁：建表脚本必须随包安装（pip install . 后可定位），migrate 对空目录不得静默成功。"""
import os
from importlib import resources
from pathlib import Path

import pytest

import lutetia
import lutetia.cli
from lutetia.config import load_dotenv
from lutetia.db import Database

load_dotenv()
DB_URL = os.environ.get("DATABASE_URL", "")

EXPECTED = ["001_schema.sql", "002_raw_jsonb_fix.sql"]


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
