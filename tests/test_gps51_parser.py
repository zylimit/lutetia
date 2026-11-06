from lutetia.parsers.gps51 import (parse_lastposition, parse_monitorlist, parse_push_payload, parse_tracks)


def test_lastposition_records(gps51_lastposition):
    rows = parse_lastposition(gps51_lastposition)
    assert len(rows) == 4
    r = {p.device_id: p for p in rows}["4072407731"]
    assert r.origin == "poll"
    assert abs(r.lat - (-17.758552)) < 1e-5 and abs(r.lon - 31.104348) < 1e-5
    assert r.update_time == 1782840629000 and r.device_time == 1782840629000 and r.arrived_time == 1782840631608
    assert r.speed_raw == 0.0 and r.moving == 1 and r.strstatus.startswith("ACC")
    assert r.temp1 is None  # 536870911 sentinel -> NULL
    assert r.raw["positionlastid"] == 2472402


def test_lastposition_null_records_is_empty():
    assert parse_lastposition({"status": 0, "cause": "OK", "records": None}) == []


def test_tracks(gps51_tracks):
    rows = parse_tracks(gps51_tracks)
    assert len(rows) == 928
    assert {p.device_id for p in rows} == {"4072400634"}
    assert all(p.origin == "tracks" and p.device_time == p.update_time for p in rows)
    assert all(p.temp1 is None for p in rows)  # 65535 sentinel -> NULL
    assert max(p.speed_raw for p in rows) == 122232.0  # metres per hour, i.e. 122 km/h
    assert len({(p.device_id, p.update_time) for p in rows}) == len(rows)


def test_tracks_null_records():
    assert parse_tracks({"status": 0, "cause": "OK", "deviceid": "x", "records": None}) == []


def test_monitorlist(gps51_monitorlist):
    devs = parse_monitorlist(gps51_monitorlist)
    assert len(devs) == 5
    assert sum(1 for d in devs if d.expected_online) == 2
    d = {x.device_id: x for x in devs}["4072400634"]
    assert d.source == "gps51" and d.device_type == "53" and d.extra["groupname"] == "Default"


PUSH = {
    "devicename": "4072400634", "deviceid": "4072400634", "lat": 48.83, "lon": 2.26,
    "arrivedtime": 1791231963641, "updatetime": 1791231812000, "validpoistiontime": 1791231812000,
    "radius": 0.0, "speed": 25000.0, "altitude": 0.0, "course": 90, "totaldistance": 13798096,
    "status": 335548422, "strstatus": "Battery 100%", "alarm": 0, "stralarm": "", "gotsrc": "gps",
    "rxlevel": 100, "voltagev": 4.17, "voltagepercent": 100, "gpsvalidnum": 10, "iostatus": -1,
    "rotatestatus": -1, "reportmode": 0, "moving": 1, "fuledata": None, "tempdata": None,
    "parkduration": 0, "devicealarm": None,
}


def test_push_single_and_list_and_envelope():
    one = parse_push_payload(PUSH)
    assert len(one) == 1
    p = one[0]
    assert p.origin == "push" and p.lat == 48.83 and p.lon == 2.26
    assert p.update_time == 1791231812000 and p.device_time == 1791231812000
    assert parse_push_payload([PUSH, PUSH]) and len(parse_push_payload([PUSH, dict(PUSH, updatetime=1)])) == 2
    assert len(parse_push_payload({"data": [PUSH]})) == 1
    assert parse_push_payload({"foo": "bar"}) == []
    assert parse_push_payload("garbage") == []


def test_push_dedupe_key_matches_poll(gps51_lastposition):
    poll = parse_lastposition(gps51_lastposition)[0]
    pushed = parse_push_payload({"deviceid": poll.device_id, "lat": 1, "lon": 2, "updatetime": poll.update_time})[0]
    assert (pushed.device_id, pushed.update_time) == (poll.device_id, poll.update_time)


def test_push_falls_back_to_arrivedtime():
    p = parse_push_payload({"deviceid": "1", "lat": 1, "lon": 2, "arrivedtime": 5})[0]
    assert p.update_time == 5
    assert parse_push_payload({"deviceid": "1", "lat": 1, "lon": 2}) == []
