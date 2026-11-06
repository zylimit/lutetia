"""GPS51 payload parsers. Three shapes carry positions:
- lastposition records (poll):   callat/callon, devicetime, arrivedtime, updatetime
- querytracks records (manual):  callat/callon, updatetime, no devicetime
- forwarded push messages:       lat/lon, validpoistiontime, arrivedtime, updatetime
All three collapse into GpsPosition keyed on (deviceid, updatetime)."""
from typing import Any, Dict, List, Optional

from ..models import Device, GpsPosition

# Vendor sentinels meaning "no temperature sensor": 65535 in track records, 536870911 in last positions.
TEMP_SENTINELS = {65535, 536870911}


def _int(v: Any) -> Optional[int]:
    if v is None or isinstance(v, bool):
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _float(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _temp(v: Any) -> Optional[int]:
    i = _int(v)
    if i is None or i in TEMP_SENTINELS:
        return None
    return i


def _str(v: Any) -> Optional[str]:
    return None if v is None else str(v)


def _position(device_id: str, rec: Dict[str, Any], update_time: int, device_time: Optional[int],
              lat_key: str, lon_key: str, origin: str) -> GpsPosition:
    return GpsPosition(
        device_id=device_id,
        update_time=update_time,
        device_time=device_time,
        arrived_time=_int(rec.get("arrivedtime")),
        lat=_float(rec.get(lat_key)),
        lon=_float(rec.get(lon_key)),
        speed_raw=_float(rec.get("speed")),
        course=_int(rec.get("course")),
        altitude=_float(rec.get("altitude")),
        total_distance=_float(rec.get("totaldistance")),
        status=_int(rec.get("status")),
        alarm=_int(rec.get("alarm")),
        strstatus=_str(rec.get("strstatus")),
        stralarm=_str(rec.get("stralarm")),
        moving=_int(rec.get("moving")),
        temp1=_temp(rec.get("temp1")),
        temp2=_temp(rec.get("temp2")),
        temp3=_temp(rec.get("temp3")),
        temp4=_temp(rec.get("temp4")),
        origin=origin,
        raw=rec,
    )


def parse_lastposition_record(rec: Dict[str, Any]) -> Optional[GpsPosition]:
    device_id, update_time = _str(rec.get("deviceid")), _int(rec.get("updatetime"))
    if not device_id or update_time is None:
        return None
    return _position(device_id, rec, update_time, _int(rec.get("devicetime")), "callat", "callon", "poll")


def parse_lastposition(resp: Dict[str, Any]) -> List[GpsPosition]:
    out = []
    for rec in resp.get("records") or []:        # vendor returns null, not [], when empty
        p = parse_lastposition_record(rec)
        if p:
            out.append(p)
    return out


def parse_track_record(device_id: str, rec: Dict[str, Any]) -> Optional[GpsPosition]:
    update_time = _int(rec.get("updatetime"))
    if update_time is None:
        return None
    return _position(device_id, rec, update_time, update_time, "callat", "callon", "tracks")


def parse_tracks(resp: Dict[str, Any]) -> List[GpsPosition]:
    device_id = _str(resp.get("deviceid")) or ""
    out = []
    for rec in resp.get("records") or []:
        p = parse_track_record(device_id, rec)
        if p:
            out.append(p)
    return out


def parse_push_message(msg: Dict[str, Any]) -> Optional[GpsPosition]:
    device_id = _str(msg.get("deviceid"))
    update_time = _int(msg.get("updatetime"))
    if update_time is None:
        update_time = _int(msg.get("arrivedtime"))
    if not device_id or update_time is None:
        return None
    lat_key, lon_key = ("lat", "lon") if "lat" in msg else ("callat", "callon")
    device_time = _int(msg.get("validpoistiontime")) or _int(msg.get("devicetime"))
    return _position(device_id, msg, update_time, device_time, lat_key, lon_key, "push")


def is_alarm_message(msg: Dict[str, Any]) -> bool:
    """Alarm forwards carry alarmtype; they are counted, never stored as positions."""
    return "alarmtype" in msg


def push_items(payload: Any) -> List[Dict[str, Any]]:
    """Splits a push body (one message, a list, or an envelope with a list) into dict items."""
    items: List[Any] = []
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        if "deviceid" in payload:
            items = [payload]
        else:
            for key in ("records", "data", "list", "positions", "messages"):
                if isinstance(payload.get(key), list):
                    items = payload[key]
                    break
    return [m for m in items if isinstance(m, dict)]


def parse_push_payload(payload: Any) -> List[GpsPosition]:
    out = []
    for m in push_items(payload):
        if is_alarm_message(m):
            continue
        p = parse_push_message(m)
        if p:
            out.append(p)
    return out


def parse_monitorlist(resp: Dict[str, Any]) -> List[Device]:
    out = []
    for g in resp.get("groups") or []:
        for d in g.get("devices") or []:
            device_id = _str(d.get("deviceid"))
            if not device_id:
                continue
            out.append(Device(
                source="gps51",
                device_id=device_id,
                name=_str(d.get("devicename")),
                device_type=_str(d.get("devicetype")),
                expected_online=(d.get("isfree") == 1),
                extra=dict(d, groupid=g.get("groupid"), groupname=g.get("groupname")),
            ))
    return out
