"""Response envelopes, opaque keyset cursors and query-parameter parsing shared by every /api/v1 resource.
List resources: {"items", "as_of", "next"} (+ "source" for snapshots). Single objects: {"data", "as_of"}. Errors: {"error": text}."""
import base64
import binascii
import json
import re
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

from aiohttp import web

from ...db import ms_to_dt
from ..jsonutil import _dumps

DEFAULT_LIMIT, MAX_LIMIT = 100, 1000
CURSOR_MAX_LEN = 512
_B64URL_RE = re.compile(r"[A-Za-z0-9_-]+")
Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


class BadParam(Exception):
    """A malformed query parameter or cursor: answered 400."""


class NotFound(Exception):
    """An unknown id in the path: answered 404."""


def json_response(obj: Any, status: int = 200) -> web.Response:
    return web.json_response(obj, status=status, dumps=_dumps)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def errors_as_responses(handler: Handler) -> Handler:
    """BadParam -> 400, NotFound -> 404, both in the existing {"error": text} shape; any other exception is left to the server."""
    async def wrapper(request: web.Request) -> web.StreamResponse:
        try:
            return await handler(request)
        except BadParam as e:
            return json_response({"error": str(e)}, 400)
        except NotFound as e:
            return json_response({"error": str(e)}, 404)
    return wrapper


def no_nul(name: str, value: str) -> str:
    """Text parameters go to Postgres as bound values, which cannot hold a NUL byte: refuse it here (400), not as a 500 later."""
    if "\x00" in value:
        raise BadParam("%s contains a NUL character" % name)
    return value


def parse_time(name: str, raw: Optional[str]) -> Optional[datetime]:
    if raw is None or raw == "":
        return None
    try:
        raw = raw.replace(" ", "+")  # an unencoded "+" in a query string arrives as a space
        if raw.lstrip("-").isdigit():
            return ms_to_dt(int(raw))
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        # normalise to UTC here: a year-1 or year-9999 instant with an offset overflows on conversion (OverflowError), which must be a 400
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    except (ValueError, OverflowError, OSError):
        raise BadParam("%s must be ISO 8601 or epoch milliseconds" % name)


def parse_limit(request: web.Request) -> int:
    raw = request.query.get("limit", str(DEFAULT_LIMIT))
    try:
        limit = int(raw)
    except ValueError:
        raise BadParam("limit must be an integer between 1 and %d" % MAX_LIMIT)
    if limit < 1 or limit > MAX_LIMIT:
        raise BadParam("limit must be an integer between 1 and %d" % MAX_LIMIT)
    return limit


def parse_days(request: web.Request, default: int, low: int, high: int) -> int:
    raw = request.query.get("days", str(default))
    try:
        days = int(raw)
    except ValueError:
        raise BadParam("days must be an integer between %d and %d" % (low, high))
    if days < low or days > high:
        raise BadParam("days must be an integer between %d and %d" % (low, high))
    return days


def encode_cursor(key: Sequence[Any]) -> str:
    """Opaque to callers: base64url (no padding) of a JSON array holding the keyset of the last item returned."""
    raw = json.dumps(list(key), separators=(",", ":"), default=_cursor_default).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _cursor_default(o: Any) -> Any:
    if isinstance(o, datetime):
        return o.astimezone(timezone.utc).isoformat()
    raise TypeError("not a cursor value: %s" % type(o).__name__)


def c_str(v: Any) -> str:
    if not isinstance(v, str) or len(v) > 256 or "\x00" in v:
        raise ValueError("not a string")
    return v


def c_int_in(low: int, high: int) -> Callable[[Any], int]:
    """Converter for an integer cursor element bounded by the range of the column it is compared with (a value outside it would be a database error)."""
    def conv(v: Any) -> int:
        if not isinstance(v, int) or isinstance(v, bool) or v < low or v > high:
            raise ValueError("not an integer in range")
        return v
    return conv


c_int32 = c_int_in(-2 ** 31, 2 ** 31 - 1)  # poi_cable_segment.seq is int
c_int64 = c_int_in(-2 ** 63, 2 ** 63 - 1)  # the track bucket is bigint


def c_dt(v: Any) -> datetime:
    dt = datetime.fromisoformat(c_str(v))
    if dt.tzinfo is None:
        raise ValueError("naive timestamp")
    return dt.astimezone(timezone.utc)  # OverflowError (a ValueError-class failure for the caller) when the instant leaves datetime's range


def decode_cursor(request: web.Request, shape: Sequence[Callable[[Any], Any]]) -> Optional[Tuple[Any, ...]]:
    """The request's `cursor` parameter as a typed keyset (one converter per element), None when absent; anything else -> BadParam."""
    raw = request.query.get("cursor")
    if raw is None or raw == "":
        return None
    try:
        if len(raw) > CURSOR_MAX_LEN or not _B64URL_RE.fullmatch(raw):
            raise ValueError("bad characters")
        arr = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8"))
        if not isinstance(arr, list) or len(arr) != len(shape):
            raise ValueError("bad shape")
        return tuple(conv(v) for conv, v in zip(shape, arr))
    except (ValueError, TypeError, OverflowError, binascii.Error):  # UnicodeDecodeError and JSONDecodeError are ValueErrors
        raise BadParam("invalid cursor")


def list_response(items: List[Any], as_of: Optional[datetime], next_key: Optional[Sequence[Any]] = None,
                  source: Optional[str] = None) -> web.Response:
    body: Dict[str, Any] = {"items": items, "as_of": as_of, "next": encode_cursor(next_key) if next_key is not None else None}
    if source is not None:
        body["source"] = source
    return json_response(body)


def data_response(data: Any, as_of: datetime) -> web.Response:
    return json_response({"data": data, "as_of": as_of})
