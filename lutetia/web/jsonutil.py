"""JSON serialisation shared by the API and the dashboard data endpoints."""
import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

DEVICE_ID_RE = re.compile(r"[A-Za-z0-9_.:-]{1,128}")


def validate_device_id(s: str) -> Optional[str]:
    """Error message for a malformed device_id, None when acceptable."""
    return None if DEVICE_ID_RE.fullmatch(s or "") else "invalid device_id"


def _json_default(o: Any) -> Any:
    if isinstance(o, datetime):
        return o.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f").rstrip("0").rstrip(".") + "Z"
    if isinstance(o, Decimal):
        return float(o)
    raise TypeError("not JSON serializable: %s" % type(o).__name__)


def _dumps(obj: Any) -> str:
    return json.dumps(obj, default=_json_default)
