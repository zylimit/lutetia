# risk: high
"""Phase 8 Task 8.4: lutetia/web/openapi.json is the /api/v1 contract. Every GET in it is called on a synthetic database (rows named
zz-test-v1-*, removed after) and the response is checked with jsonschema (Draft 2020-12); the contract's resource set must equal the
routes the application registers; the document must be well-formed OpenAPI 3.1 (structure only: the official meta-schema is not
bundled with jsonschema, and no second dependency is added for it). A renamed field or an unlisted route turns this file red.
The published document stays open (no additionalProperties false: a client that validates strictly must not break when v1 adds a field);
the tests close the new resources' objects on a deep copy, so an extra or renamed field still turns them red."""
import copy
import dataclasses
import hashlib
import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import DummyCookieJar
from aiohttp.test_utils import TestClient, TestServer
from yarl import URL
from jsonschema import Draft202012Validator, FormatChecker

from lutetia.models import Device, Telemetry
from test_api_v1_resources import (AUTH, KEY, PFX, db, fall_events_of, gps, login, make_app, mk_bundles, mk_manhole, mk_pois,  # noqa: F401
                                   ms_ago, twelve_manholes)

OPENAPI = Path(__file__).resolve().parents[1] / "lutetia" / "web" / "openapi.json"
DOC = json.loads(OPENAPI.read_text(encoding="utf-8"))
PATHS = sorted(DOC["paths"])
SCOPES = ("iot:read", "poi:read", "status:read")
KEYS = {name: "k-" + name + "-" + secrets.token_hex(6) for name in ("iot", "poi", "status", "slow")}
ENTRIES = [{"name": "caller-" + n, "key_sha256": hashlib.sha256(k.encode()).hexdigest(), "scopes": [{"iot": "iot:read", "poi": "poi:read",
           "status": "status:read", "slow": "iot:read"}[n]], "origins": [], "rate_per_min": 1 if n == "slow" else 100000} for n, k in KEYS.items()]
LEGACY_ARRAYS = ("devices", "positions", "telemetry")  # the original three answer {"<name>": [...]}, no `items`


def bearer(key):
    return {"Authorization": "Bearer " + key}


ANY_CREDENTIAL_PATHS = ("/api/v1/openapi.json", "/api/v1/me")  # no x-scope: a key or session with any scope may call them
LEGACY_PATHS = ("/api/v1/devices", "/api/v1/positions", "/api/v1/telemetry", "/api/v1/status", "/api/v1/openapi.json")


def closed_copy(doc):
    """Deep copy with additionalProperties false on every object that lists properties, except the original four (Legacy* schemas
    and their paths), which stay open as they always were."""
    out = copy.deepcopy(doc)

    def close(node):
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
            for v in node.values():
                close(v)
        elif isinstance(node, list):
            for v in node:
                close(v)
    for name, schema in out["components"]["schemas"].items():
        if not name.startswith("Legacy"):
            close(schema)
    close(out["components"]["responses"])
    for path, item in out["paths"].items():
        if path not in LEGACY_PATHS:
            close(item)
    return out


CLOSED = closed_copy(DOC)


def deref(ref):
    node = CLOSED
    for part in ref["$ref"].lstrip("#/").split("/"):
        node = node[part]
    return node


def ok_schema(path):
    return CLOSED["paths"][path]["get"]["responses"]["200"]["content"]["application/json"]["schema"]


def validator(schema):
    # the whole components block rides along so "#/components/..." references resolve against this root
    return Draft202012Validator({**schema, "components": CLOSED["components"]}, format_checker=FormatChecker())


def check(schema, body, label):
    errors = sorted(validator(schema).iter_errors(body), key=lambda e: list(e.path))
    assert not errors, "%s: %s at %s" % (label, errors[0].message, "/".join(str(p) for p in errors[0].absolute_path))


def error_schema(name):
    return CLOSED["components"]["responses"][name]["content"]["application/json"]["schema"]


# ---- the world: every nullable field has a row with a value and a row without ---------------------------------------------

async def fill_world(db):
    ids = await twelve_manholes(db)  # open and finished fall events, names, volt / rsrp, one device with coordinates
    await db.upsert_devices([Device("dingtek", PFX + "mh-bare", None, "DC414", True, {})])  # no name, no telemetry: volt, rsrp, last_seen null
    await fall_events_of(db, ids["quiet_9"], 3)
    bundles = await mk_bundles(db)
    nameless = PFX + "b-unregistered"  # a push arrived before registration: no name; a position without a moving flag
    await db.insert_gps_positions([dataclasses.replace(gps(nameless, ms_ago(7)), moving=None)])
    track = bundles["online"]
    await db.insert_gps_positions([dataclasses.replace(gps(track, ms_ago(m)), speed_raw=None, moving=None) for m in (30, 60)]
                                  + [gps(track, ms_ago(m)) for m in (90, 120)])
    await mk_pois(db)
    async with db.pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO poi (poi_no, uci, subcon, site_ville, commune_code, category, status_raw, occ_week_from, occ_week_to, occ_date_from, "
            "occ_date_to, received_date, planned_op_date, content_sha, raw_sha) VALUES ($1, 'u', 's', 'Paris', 'c', 'Transport', 'x', 10, 12, "
            "'2026-03-02', '2026-03-20', '2026-02-20', '2026-04-01', 'c', 'r')", PFX + "p-full")
        await conn.execute("INSERT INTO poi (poi_no, content_sha, raw_sha) VALUES ($1, 'c', 'r')", PFX + "p-bare")  # everything optional null
        await conn.execute("INSERT INTO poi_cable_segment (poi_no, seq, cable_category, cable_type, infra, length_km, weight_t, ref_min_t, "
                           "ref_avg_t, ref_max_t) VALUES ($1, 1, 'DECS2', 'T1', 'aerien', 1.5, 2.0, 1.0, 2.0, 3.0)", PFX + "p-full")
        await conn.execute("INSERT INTO poi_cable_segment (poi_no, seq) VALUES ($1, 2)", PFX + "p-full")
        await conn.execute("INSERT INTO api_call (source, action, ok) VALUES ($1, 'x', true)", PFX + "src")
        for tpl in ("sla-a", "sla-b"):  # two templates so the list has a second page; one step without an SLA text
            await conn.execute("INSERT INTO sla_template_step (template, seq, step, owner, sla_text) VALUES ($1, 1, 's1', 'customer', '1 d'), "
                               "($1, 2, 's2', 'partner', NULL)", PFX + tpl)
    # the original four: a device with nothing optional, one with no name, type, flag or data; positions and telemetry with and without values
    legacy = PFX + "b-legacy"
    await db.upsert_devices([Device("gps51", legacy, legacy, "GT", True, {}), Device("gps51", PFX + "b-blank", None, None, None, {})])
    full = dataclasses.replace(gps(legacy, ms_ago(3)), temp1=2150, course=90)
    blank = dataclasses.replace(gps(legacy, ms_ago(4)), device_time=None, arrived_time=None, lat=None, lon=None, speed_raw=None, course=None,
                                altitude=None, total_distance=None, moving=None)
    await db.insert_gps_positions([full, blank])
    await db.insert_telemetry([Telemetry(ids["quiet_8"], "state", ms_ago(2), None, "IDLE", "rest"), Telemetry(ids["quiet_8"], "volt", ms_ago(2), 372.0, None, "rest")])
    await db.write_heartbeat("t", None, None, True, {"received": 3})
    return SimpleNamespace(ids=ids, bundles=bundles, legacy=legacy, track=track, manhole=ids["quiet_8"], poi=PFX + "p-full")


@pytest.fixture
async def env(db, tmp_path):
    world = await fill_world(db)
    app, cfg = make_app(db, tmp_path, ENTRIES)
    async with TestClient(TestServer(app), cookie_jar=DummyCookieJar()) as c:
        world.c, world.cfg = c, cfg
        world.session = await login(c, cfg, "admin")
        yield world
    async with db.pool.acquire() as conn:
        await conn.execute("DELETE FROM api_call WHERE source = $1", PFX + "src")
        await conn.execute("DELETE FROM sla_template_step WHERE template LIKE $1", PFX + "%")
        await conn.execute("DELETE FROM collector_status")


def requests_for(w):
    """path template -> (url, key of the array when the response is a plain list of rows)."""
    return {
        "/api/v1/openapi.json": "/api/v1/openapi.json",
        "/api/v1/me": "/api/v1/me",
        "/api/v1/summary": "/api/v1/summary",
        "/api/v1/manholes": "/api/v1/manholes",
        "/api/v1/fall-events": "/api/v1/fall-events",
        "/api/v1/bundles": "/api/v1/bundles",
        "/api/v1/bundles/{device_id}/track": "/api/v1/bundles/%s/track?days=1" % w.track,
        "/api/v1/manholes/{device_id}/series": "/api/v1/manholes/%s/series?days=7" % w.manhole,
        "/api/v1/pois": "/api/v1/pois",
        "/api/v1/pois/{poi_no}/segments": "/api/v1/pois/%s/segments" % w.poi,
        "/api/v1/sla-templates": "/api/v1/sla-templates",
        "/api/v1/collector-status": "/api/v1/collector-status",
        "/api/v1/devices": "/api/v1/devices",
        "/api/v1/positions": "/api/v1/positions?device_id=" + w.legacy,
        "/api/v1/telemetry": "/api/v1/telemetry?device_id=" + w.manhole,
        "/api/v1/status": "/api/v1/status",
    }


async def fetch(c, url, headers, status=200):
    r = await c.get(url, headers=headers)
    assert r.status == status, (url, r.status, await r.text())
    return await r.json()


async def pages(c, url, headers):
    """Every page of a list resource (limit 1), each one a response body."""
    out, cursor = [], None
    while True:
        sep = "&" if "?" in url else "?"
        body = await fetch(c, url + sep + "limit=1" + ("&cursor=" + cursor if cursor else ""), headers)
        out.append(body)
        cursor = body["next"]
        assert len(out) < 200
        if cursor is None:
            return out


def both_branches(schema, rows, label):
    """Each field the contract says may be null must be null in some row and set in another: the data covers the null branch."""
    item = deref(schema) if "$ref" in schema else schema
    for field, spec in item["properties"].items():
        if isinstance(spec.get("type"), list) and "null" in spec["type"]:
            assert {r[field] is None for r in rows} == {True, False}, "%s.%s: test data lacks a null or a non-null example" % (label, field)


def ok_schema_props(path):
    s = ok_schema(path)
    return (deref(s) if "$ref" in s else s).get("properties", {})


def row_schema(path):
    """Schema of one row of a list resource: `items` for the new ones, the array named after the path for the original three."""
    props = ok_schema_props(path)
    prop = props.get("items") or props.get(path.rsplit("/", 1)[-1])
    return prop["items"] if prop and prop.get("type") == "array" else None


# ---- every GET in the contract against a real response ---------------------------------------------------------------------

@pytest.mark.parametrize("path", PATHS)
async def test_every_get_in_the_contract_returns_what_it_declares(env, path):
    url = requests_for(env)[path]  # a contract path with no entry here has no test data: red on purpose
    for who, headers in (("key", AUTH), ("session", env.session)):  # SC-14: both ways in see the same shapes
        label = "%s via %s" % (path, who)
        if "items" in ok_schema_props(path):
            bodies = await pages(env.c, url, headers)
            rows = [i for b in bodies for i in b["items"]]
            assert len(bodies) >= 2 and rows, label  # more than one page, never empty
            for n, b in enumerate(bodies):
                check(ok_schema(path), b, "%s page %d" % (label, n))
            both_branches(row_schema(path), rows, label)
        else:
            body = await fetch(env.c, url, headers)
            check(ok_schema(path), body, label)
            for key in LEGACY_ARRAYS:
                assert body.get(key, [None]), label  # an array that is present is not empty
    if path == "/api/v1/openapi.json":
        assert await fetch(env.c, url, AUTH) == DOC
        assert (await env.c.get(url, headers=AUTH)).headers["Content-Type"] == "application/json; charset=utf-8"


async def test_original_four_rows_cover_their_null_branches(env):
    urls = requests_for(env)
    devices = [d for d in (await fetch(env.c, urls["/api/v1/devices"], AUTH))["devices"] if d["device_id"].startswith(PFX)]
    both_branches(row_schema("/api/v1/devices"), devices, "devices")
    both_branches(row_schema("/api/v1/positions"), (await fetch(env.c, urls["/api/v1/positions"], AUTH))["positions"], "positions")
    tele = (await fetch(env.c, urls["/api/v1/telemetry"] + "&limit=50", AUTH))["telemetry"]
    both_branches(row_schema("/api/v1/telemetry"), tele, "telemetry")
    assert any(r["value_str"] == "IDLE" and r["value_num"] is None for r in tele)


async def test_summary_and_collector_status_in_each_state(env, db):
    iot = bearer(KEYS["iot"])
    narrow = await fetch(env.c, "/api/v1/summary", iot)
    check(ok_schema("/api/v1/summary"), narrow, "summary without poi:read")
    assert narrow["data"]["pois"] is None  # the null branch the contract allows
    wide = await fetch(env.c, "/api/v1/summary", AUTH)
    assert wide["data"]["pois"] is not None and wide["data"]["bundles"]["last_position_at"] is not None
    async with db.pool.acquire() as conn:
        await conn.execute("DELETE FROM collector_status")
    for path in ("/api/v1/summary", "/api/v1/collector-status", "/api/v1/status"):
        body = await fetch(env.c, path, AUTH)
        check(ok_schema(path), body, path + " without a heartbeat")
        collector = body["data"]["collector"] if "data" in body else body["collector"]
        assert collector["updated_at"] is None and collector["stale"] is True
    assert (await fetch(env.c, "/api/v1/collector-status", AUTH))["data"]["receiver"] is None
    await db.write_heartbeat("1.2.3", datetime.now(timezone.utc), True, False, {"received": 5, "collector_started_at": "2026-11-10T00:00:00+00:00"})
    for path in ("/api/v1/summary", "/api/v1/collector-status", "/api/v1/status"):
        check(ok_schema(path), await fetch(env.c, path, AUTH), path + " with a heartbeat")
    assert (await fetch(env.c, "/api/v1/collector-status", AUTH))["data"]["receiver"]["received"] == 5


TIME = re.compile(r"\d{4}-\d{2}-\d{2}T")
TIME_Z = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z")


def time_strings(node):
    if isinstance(node, dict):
        for v in node.values():
            yield from time_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from time_strings(v)
    elif isinstance(node, str) and TIME.match(node):
        yield node


@pytest.mark.parametrize("written", ["2026-11-10T00:00:00+00:00", "2026-11-10T00:00:00.123456+00:00", "2026-11-10T00:00:00Z",
                                     "2026-11-10T02:00:00+02:00"])
async def test_every_timestamp_in_a_response_ends_in_z(env, db, written):
    """The collector writes collector_started_at with isoformat (+00:00); the API prints it like every other timestamp."""
    await db.write_heartbeat("1.2.3", datetime.now(timezone.utc), True, False, {"received": 5, "collector_started_at": written})
    for path in ("/api/v1/summary", "/api/v1/collector-status", "/api/v1/status"):
        body = await fetch(env.c, path, AUTH)
        stamps = list(time_strings(body))
        assert len(stamps) >= 2, path
        assert all(TIME_Z.fullmatch(t) for t in stamps), (path, [t for t in stamps if not TIME_Z.fullmatch(t)])
        collector = body["data"]["collector"] if "data" in body else body["collector"]
        if path == "/api/v1/summary":
            continue  # its collector object has no start time
        started = collector["collector_started_at"]
        assert started == ("2026-11-10T00:00:00.123456Z" if ".123456" in written else "2026-11-10T00:00:00Z"), (path, started)


async def test_limits_days_and_enums_in_the_contract_are_what_the_code_enforces(env):
    """Each constraint the contract states on a parameter: just inside it answers 2xx, just outside it answers 400. Either side
    changing its range alone turns this red."""
    urls = requests_for(env)
    cases = []  # (label, url with the parameter appended, expected status)
    for path in PATHS:
        for p in DOC["paths"][path]["get"].get("parameters", []):
            if p["in"] != "query":
                continue
            sch = p["schema"]
            inside, outside = [], []
            if sch.get("type") == "integer":
                inside += [sch["minimum"], sch["maximum"]]
                outside += [sch["minimum"] - 1, sch["maximum"] + 1]
            if "enum" in sch:
                inside += sch["enum"]
                outside += ["not-" + str(sch["enum"][0])]
            if "maxLength" in sch:
                inside += ["x" * sch["maxLength"]]
                outside += ["x" * (sch["maxLength"] + 1)]
            for v in inside + outside:
                cases.append(("%s %s=%.20s" % (path, p["name"], v), str(URL(urls[path]).update_query({p["name"]: str(v)})),  # replaces days=1
                              200 if v in inside else 400))
    assert {c[0].split(" ")[1].split("=")[0] for c in cases} >= {"limit", "days", "include_removed"}, "the loop found no constraints"
    wrong = []
    for label, url, expected in cases:
        status = (await env.c.get(url, headers=AUTH)).status
        if status != expected:
            wrong.append("%s: %d, contract says %d" % (label, status, expected))
    assert not wrong, wrong


async def test_error_bodies_and_headers_match_the_contract(env):
    c = env.c
    r = await c.get("/api/v1/manholes?limit=0", headers=AUTH)
    assert r.status == 400
    check(error_schema("BadRequest"), await r.json(), "400")
    r = await c.get("/api/v1/manholes", headers=bearer(KEYS["poi"]))  # a valid key without the scope
    assert r.status == 403
    check(error_schema("Forbidden"), await r.json(), "403")
    r = await c.get("/api/v1/manholes")
    assert r.status == 401 and r.headers["WWW-Authenticate"] == "Bearer"
    check(error_schema("Unauthorized"), await r.json(), "401")
    r = await c.get("/api/v1/pois/%snobody/segments" % PFX, headers=AUTH)
    assert r.status == 404
    check(error_schema("NotFound"), await r.json(), "404")
    slow = bearer(KEYS["slow"])
    assert (await c.get("/api/v1/manholes", headers=slow)).status == 200
    r = await c.get("/api/v1/manholes", headers=slow)  # the second call inside the minute is over the 1 per minute limit
    assert r.status == 429
    check(error_schema("RateLimited"), await r.json(), "429")
    declared = DOC["components"]["responses"]["RateLimited"]["headers"]["Retry-After"]
    check(declared["schema"], int(r.headers["Retry-After"]), "Retry-After")
    assert declared["required"] is True
    for path in PATHS:  # every status code an operation lists is one the document defines
        for code, resp in DOC["paths"][path]["get"]["responses"].items():
            assert "$ref" in resp or "description" in resp, (path, code)


async def test_x_scope_is_what_the_code_enforces(env):
    urls = requests_for(env)
    for path in PATHS:
        scope = DOC["paths"][path]["get"].get("x-scope")
        if path in ANY_CREDENTIAL_PATHS:
            assert scope is None  # any valid credential, whatever its scopes
            for name in ("iot", "poi", "status"):
                assert (await env.c.get(urls[path], headers=bearer(KEYS[name]))).status == 200, name
            continue
        assert scope in SCOPES, path
        for name in ("iot", "poi", "status"):
            status = (await env.c.get(urls[path], headers=bearer(KEYS[name]))).status
            assert (status == 403) == (SCOPES[("iot", "poi", "status").index(name)] != scope), (path, name, status)


# ---- the document itself --------------------------------------------------------------------------------------------------

async def test_contract_paths_equal_the_registered_v1_get_routes(db, tmp_path):
    app, _ = make_app(db, tmp_path)
    routes = {r.resource.canonical for r in app.router.routes() if r.method == "GET" and r.resource.canonical.startswith("/api/v1/")}
    assert routes == set(DOC["paths"]), {"route without contract": sorted(routes - set(DOC["paths"])),
                                          "contract without route": sorted(set(DOC["paths"]) - routes)}
    assert all(set(item) == {"get"} for item in DOC["paths"].values())  # read-only: GET and nothing else


def refs_of(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "$ref":
                yield v
            else:
                yield from refs_of(v)
    elif isinstance(node, list):
        for v in node:
            yield from refs_of(v)


def test_document_is_well_formed_openapi_3_1():
    assert re.fullmatch(r"3\.1\.\d+", DOC["openapi"])
    assert isinstance(DOC["info"]["title"], str) and isinstance(DOC["info"]["version"], str)
    assert DOC["paths"], "no paths"
    schemes = DOC["components"]["securitySchemes"]
    assert schemes["bearerKey"]["type"] == "http" and schemes["bearerKey"]["scheme"] == "bearer"
    assert schemes["sessionCookie"]["type"] == "apiKey" and schemes["sessionCookie"]["in"] == "cookie"
    for ref in refs_of(DOC):
        assert ref.startswith("#/") and deref({"$ref": ref}) is not None, ref  # every reference points at something
    assert len({o["operationId"] for p in DOC["paths"].values() for o in p.values()}) == len(DOC["paths"]), "operationId must be unique"
    for path, item in DOC["paths"].items():
        assert path.startswith("/")
        for method, op in item.items():
            assert method in ("get", "put", "post", "delete", "options", "head", "patch", "trace"), (path, method)
            assert op["responses"], (path, method)  # an operation without responses is not an operation
            assert all(re.fullmatch(r"[1-5]\d\d|default", code) for code in op["responses"]), path
            declared = {p["name"] for p in op.get("parameters", []) if p["in"] == "path"}
            assert declared == set(re.findall(r"\{(\w+)\}", path)), path
            for p in op.get("parameters", []):
                assert p["in"] in ("query", "path", "header", "cookie") and "schema" in p, (path, p["name"])
                assert p["in"] != "path" or p["required"] is True, (path, p["name"])
            for req in op.get("security", []):
                assert set(req) <= set(schemes), (path, req)
    for name, schema in DOC["components"]["schemas"].items():
        Draft202012Validator.check_schema(schema)  # each schema object is a valid Draft 2020-12 schema (the OpenAPI 3.1 dialect)


def test_published_contract_is_open_and_the_test_copy_is_closed():
    """Published: no additionalProperties false anywhere, and the document tells clients to ignore unknown fields. Test copy: every
    object of the new resources is closed, the original four stay open."""
    assert '"additionalProperties": false' not in json.dumps(DOC)
    assert "ignore unknown fields" in DOC["info"]["description"] and "never removes or renames" in DOC["info"]["description"]
    assert "ignore unknown fields" in DOC["info"]["description"] and "enum values they do not know" in DOC["info"]["description"]
    for name, schema in CLOSED["components"]["schemas"].items():
        for sub in walk_objects(schema):
            assert (sub.get("additionalProperties") is False) == (not name.startswith("Legacy")), name


def walk_objects(node):
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            yield node
        for v in node.values():
            yield from walk_objects(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk_objects(v)
