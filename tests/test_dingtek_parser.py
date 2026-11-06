from lutetia.parsers.dingtek import (active_flag, parse_attributes, parse_devices, parse_timeseries, parse_ws_message)


def test_devices(dingtek_devices):
    devs = parse_devices(dingtek_devices)
    assert len(devs) == 12
    assert all(d.source == "dingtek" and d.device_type == "DC414" and len(d.device_id) == 36 for d in devs)
    assert any(d.name == "864317087586940" and d.device_id == "79702a70-9ba1-11f1-898a-012e63463e84" for d in devs)


def test_attributes_and_latest(dingtek_summary):
    uuid = "79702a70-9ba1-11f1-898a-012e63463e84"
    entry = dingtek_summary[uuid]
    attrs = parse_attributes(uuid, entry["attrs"])
    by_key = {a.key: a for a in attrs}
    assert by_key["firmware"].value == "4.4" and by_key["uploadInterval"].value == "1"
    assert by_key["active"].value == "true" and active_flag(attrs) is True
    assert by_key["latitude"].last_update_ts > 0
    latest = parse_timeseries(uuid, entry["latest"], origin="rest")
    assert len(latest) == 9
    vals = {t.key: t for t in latest}
    assert vals["volt"].value_num == 360.0 and vals["volt"].value_str is None
    assert vals["FSM"].value_num is None and vals["FSM"].value_str == "none"


def test_offline_device_flag(dingtek_summary):
    attrs = parse_attributes("x", dingtek_summary["625b8790-7f21-11f1-898a-012e63463e84"]["attrs"])
    assert active_flag(attrs) is False


def test_history(dingtek_history):
    rows = parse_timeseries("dev", dingtek_history, origin="rest")
    assert len(rows) == 826 * 5
    assert len({(r.device_id, r.key, r.ts) for r in rows}) == len(rows)
    assert {r.key for r in rows} == {"level", "temperature", "volt", "rsrp", "frameCounter"}


def test_ws_message():
    msg = {"subscriptionId": 3, "errorCode": 0, "errorMsg": None,
           "data": {"volt": [[1793895485710, "360"]], "FSM": [[1793895485710, "none"]]}}
    rows = parse_ws_message(msg, {3: "uuid-3"})
    assert len(rows) == 2 and all(r.device_id == "uuid-3" and r.origin == "ws" for r in rows)
    assert parse_ws_message(msg, {9: "other"}) == []
    assert parse_ws_message({"subscriptionId": 3, "errorCode": 3, "data": None}, {3: "u"}) == []


def test_booleans_go_to_value_str():
    rows = parse_timeseries("d", {"flag": [{"ts": 1, "value": True}]})
    assert rows[0].value_num is None and rows[0].value_str == "true"
