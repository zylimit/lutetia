from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class Device:
    source: str                 # 'gps51' | 'dingtek'
    device_id: str
    name: Optional[str]
    device_type: Optional[str]
    expected_online: Optional[bool]
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GpsPosition:
    device_id: str
    update_time: int            # ms UTC, dedupe key
    device_time: Optional[int]
    arrived_time: Optional[int]
    lat: Optional[float]
    lon: Optional[float]
    speed_raw: Optional[float]  # metres per hour as delivered by the vendor
    course: Optional[int]
    altitude: Optional[float]
    total_distance: Optional[float]
    status: Optional[int]
    alarm: Optional[int]
    strstatus: Optional[str]
    stralarm: Optional[str]
    moving: Optional[int]
    temp1: Optional[int]
    temp2: Optional[int]
    temp3: Optional[int]
    temp4: Optional[int]
    origin: str                 # 'push' | 'poll' | 'tracks'
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Telemetry:
    device_id: str
    key: str
    ts: int                     # ms UTC
    value_num: Optional[float]
    value_str: Optional[str]
    origin: str                 # 'ws' | 'rest'


@dataclass
class Attribute:
    device_id: str
    key: str
    value: Optional[str]
    last_update_ts: Optional[int]
