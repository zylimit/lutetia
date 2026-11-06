import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GPS51 = ROOT / "docs" / "vendor" / "gps51" / "samples"
DINGTEK = ROOT / "docs" / "vendor" / "dingtek" / "samples"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def gps51_lastposition():
    return load(GPS51 / "webapi" / "lastposition.json")


@pytest.fixture
def gps51_monitorlist():
    return load(GPS51 / "webapi" / "monitorlist.json")


@pytest.fixture
def gps51_tracks():
    return load(GPS51 / "openapi" / "tracks_634_1006.json")


@pytest.fixture
def dingtek_devices():
    return load(DINGTEK / "devices.json")


@pytest.fixture
def dingtek_summary():
    return load(DINGTEK / "device_summary.json")


@pytest.fixture
def dingtek_history():
    return load(DINGTEK / "history_7d_586940.json")
