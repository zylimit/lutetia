"""Dingtek Cloud is a ThingsBoard instance; these parse its REST and WebSocket shapes."""
import math
from typing import Any, Dict, List, Optional

from ..models import Attribute, Device, Telemetry


def _as_num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _as_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _telemetry(device_id: str, key: str, ts: Any, value: Any, origin: str) -> Optional[Telemetry]:
    try:
        ts_ms = int(ts)
    except (TypeError, ValueError):
        return None
    num = _as_num(value)
    return Telemetry(device_id=device_id, key=key, ts=ts_ms, value_num=num,
                     value_str=None if num is not None else _as_str(value), origin=origin)


def parse_devices(resp: Dict[str, Any]) -> List[Device]:
    out = []
    for d in resp.get("data") or []:
        ident = d.get("id") or {}
        uuid = ident.get("id") if isinstance(ident, dict) else None
        if not uuid:
            continue
        out.append(Device(source="dingtek", device_id=uuid, name=d.get("name"), device_type=d.get("type"),
                          expected_online=None, extra=d))
    return out


def parse_attributes(device_id: str, resp: Any) -> List[Attribute]:
    out = []
    for a in resp or []:
        if not isinstance(a, dict) or not a.get("key"):
            continue
        ts = a.get("lastUpdateTs")
        out.append(Attribute(device_id=device_id, key=a["key"], value=_as_str(a.get("value")),
                             last_update_ts=int(ts) if ts is not None else None))
    return out


def parse_timeseries(device_id: str, resp: Any, origin: str = "rest") -> List[Telemetry]:
    """REST shape, used for both latest values and history: {key: [{"ts": ms, "value": v}, ...]}"""
    out = []
    if not isinstance(resp, dict):
        return out
    for key, points in resp.items():
        for p in points or []:
            if isinstance(p, dict):
                t = _telemetry(device_id, key, p.get("ts"), p.get("value"), origin)
                if t:
                    out.append(t)
    return out


def parse_ws_message(msg: Dict[str, Any], sub_map: Dict[int, str]) -> List[Telemetry]:
    """WebSocket shape: {"subscriptionId": n, "errorCode": 0, "data": {key: [[ts, value], ...]}}"""
    device_id = sub_map.get(msg.get("subscriptionId"))
    data = msg.get("data")
    if not device_id or not isinstance(data, dict):
        return []
    out = []
    for key, pairs in data.items():
        for pair in pairs or []:
            if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                t = _telemetry(device_id, key, pair[0], pair[1], "ws")
                if t:
                    out.append(t)
    return out


def active_flag(attrs: List[Attribute]) -> Optional[bool]:
    for a in attrs:
        if a.key == "active":
            return (a.value or "").lower() == "true"
    return None
