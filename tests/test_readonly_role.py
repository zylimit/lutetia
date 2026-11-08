# risk: high
"""Phase 7 Task 7.1: lutetia_ro can read but the database rejects every write (THR-8)."""
import base64
import os
import secrets
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest

import lutetia.cli
from lutetia.config import load_dotenv
from lutetia.db import Database, scram_sha256_verifier

load_dotenv()
DB_URL = os.environ.get("DATABASE_URL", "")


def ro_url(password):
    u = urlsplit(DB_URL)
    host = u.hostname + (":%d" % u.port if u.port else "")
    return urlunsplit((u.scheme, "lutetia_ro:%s@%s" % (password, host), u.path, "", ""))


async def _ro_state(conn):
    row = await conn.fetchrow("SELECT rolcanlogin, rolpassword FROM pg_authid WHERE rolname = 'lutetia_ro'")
    return (row["rolcanlogin"], row["rolpassword"]) if row else (False, None)


async def _restore(conn, state):
    can_login, verifier = state
    literal = "NULL" if not verifier else await conn.fetchval("SELECT quote_literal($1::text)", verifier)
    await conn.execute("ALTER ROLE lutetia_ro %s PASSWORD %s" % ("LOGIN" if can_login else "NOLOGIN", literal))


@pytest.fixture
async def ro():
    if not DB_URL:
        pytest.skip("DATABASE_URL not set")
    d = Database(DB_URL)
    try:
        await d.connect()
    except Exception as e:  # noqa: BLE001
        pytest.skip("database unreachable: %s" % e)
    await d.migrate(lutetia.cli.SQL_DIR)          # make sure the role exists before reading its state
    async with d.pool.acquire() as c:
        state = await _ro_state(c)
    old_env = os.environ.get("DATABASE_RO_PASSWORD")
    conn = None
    try:
        password = secrets.token_hex(16)
        os.environ["DATABASE_RO_PASSWORD"] = password
        await d.migrate(lutetia.cli.SQL_DIR)
        conn = await asyncpg.connect(ro_url(password))
        yield conn
    finally:
        if conn is not None:
            await conn.close()
        if old_env is None:
            os.environ.pop("DATABASE_RO_PASSWORD", None)
        else:
            os.environ["DATABASE_RO_PASSWORD"] = old_env
        async with d.pool.acquire() as c:
            await _restore(c, state)
        await d.close()


def test_scram_verifier_format_and_known_vector():
    v = scram_sha256_verifier("pencil", salt=bytes(range(16)))
    head, rest = v.split("$", 1)
    params, keys = rest.split("$")
    iters, salt_b64 = params.split(":")
    stored_b64, server_b64 = keys.split(":")
    assert head == "SCRAM-SHA-256" and iters == "4096"
    assert base64.b64decode(salt_b64) == bytes(range(16))
    assert len(base64.b64decode(stored_b64)) == 32 and len(base64.b64decode(server_b64)) == 32
    assert "pencil" not in v
    assert scram_sha256_verifier("pencil") != scram_sha256_verifier("pencil")      # random salt


@pytest.fixture
async def pg_hashed():
    """A connection that lets PostgreSQL itself hash a plaintext for lutetia_ro; role restored byte-for-byte afterwards."""
    if not DB_URL:
        pytest.skip("DATABASE_URL not set")
    d = Database(DB_URL)
    try:
        await d.connect()
    except Exception as e:  # noqa: BLE001
        pytest.skip("database unreachable: %s" % e)
    await d.migrate(lutetia.cli.SQL_DIR)
    async with d.pool.acquire() as conn:
        state = await _ro_state(conn)
        try:
            await conn.execute("SET password_encryption = 'scram-sha-256'")
            yield conn
        finally:
            await _restore(conn, state)
    await d.close()


@pytest.mark.parametrize("password", [
    "plain" + secrets.token_hex(8),
    "pw-ä-" + secrets.token_hex(8),                     # non-ASCII (a-umlaut), already NFKC-stable for SASLprep
    "q'b\\s;--$$\"" + secrets.token_hex(8),                  # quote, backslash, semicolon, comment, dollar quote, dquote
], ids=["ascii", "non-ascii", "special-chars"])
async def test_scram_verifier_matches_postgres_byte_for_byte(pg_hashed, password):
    literal = await pg_hashed.fetchval("SELECT quote_literal($1::text)", password)
    await pg_hashed.execute("ALTER ROLE lutetia_ro PASSWORD %s" % literal)
    pg_verifier = await pg_hashed.fetchval("SELECT rolpassword FROM pg_authid WHERE rolname = 'lutetia_ro'")
    assert pg_verifier.startswith("SCRAM-SHA-256$")
    iters, salt_b64 = pg_verifier.split("$")[1].split(":")
    ours = scram_sha256_verifier(password, salt=base64.b64decode(salt_b64), iterations=int(iters))
    assert ours == pg_verifier


@pytest.mark.parametrize("table", [
    "collector_status", "fall_event", "sensor_telemetry", "sensor_telemetry_v", "device", "backup_run",
    "api_call", "gps_position", "gps_position_v", "poi", "poi_cable_segment", "sensor_attribute"])
async def test_ro_can_select(ro, table):
    await ro.fetch("SELECT * FROM %s LIMIT 1" % table)


async def test_ro_login_with_plaintext_works_via_prehashed_verifier(ro):
    assert await ro.fetchval("SELECT current_user") == "lutetia_ro"


@pytest.mark.parametrize("sql", [
    "INSERT INTO sensor_telemetry (device_id, key, ts, origin) VALUES ('zz-test-ro', 'k', now(), 'rest')",
    "INSERT INTO collector_status (id) VALUES (1)",
    "UPDATE device SET name = name",
    "DELETE FROM sensor_telemetry WHERE device_id = 'zz-test-ro'",
    "TRUNCATE sensor_telemetry",
    "CREATE TABLE zz_test_ro_t (a int)",
])
async def test_ro_writes_are_rejected(ro, sql):
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await ro.execute(sql)


async def test_ro_has_no_sequence_usage(ro):
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await ro.fetchval("SELECT nextval('backup_run_id_seq')")
