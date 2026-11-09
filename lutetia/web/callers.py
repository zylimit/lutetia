"""API caller registry (CALLERS_FILE + legacy API_KEY), scopes, per-caller token buckets, CORS and the api log line.
Only key digests are stored; no error message or log line ever carries a key or a digest."""
import hashlib
import hmac
import json
import logging
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, FrozenSet, List, Optional, Tuple
from urllib.parse import urlsplit

from aiohttp import web

log = logging.getLogger(__name__)

SCOPES = ("iot:read", "poi:read", "status:read")
SESSION_SCOPES = ("iot:read", "poi:read")  # non-admin sessions; status:read (ops internals) is admin only (Spec v1.16)
FIELDS = ("name", "key_sha256", "scopes", "origins", "rate_per_min")
LEGACY = "legacy"
API_PREFIX = "/api/v1"
_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
EMPTY_KEY_DIGEST = hashlib.sha256(b"").digest()
# Embedding systems live under digifiber.net only (user decision 2026-11-08, ADR-6); the one place this suffix is written.
ORIGIN_SUFFIX = ".digifiber.net"
API_CALLER: "web.RequestKey[str]" = web.RequestKey("api_caller", str)
API_ORIGINS: "web.RequestKey[FrozenSet[str]]" = web.RequestKey("api_origins", frozenset)


@dataclass(frozen=True)
class Caller:
    name: str
    digest: bytes  # sha256 of the key (32 raw bytes)
    scopes: FrozenSet[str]
    origins: FrozenSet[str]
    rate_per_min: int


def digest_of(key: str) -> bytes:
    return hashlib.sha256(key.encode("utf-8")).digest()


def origin_allowed(origin: Any) -> bool:
    """Exactly https://<one or more labels>.digifiber.net: no port, path, wildcard or bare apex; lowercase only."""
    if not isinstance(origin, str):
        return False
    try:
        parts = urlsplit(origin)
        host = parts.hostname or ""
    except ValueError:
        return False
    if parts.scheme != "https" or not host.endswith(ORIGIN_SUFFIX) or origin != "https://" + host:
        return False
    return all(_LABEL_RE.match(lab) for lab in host[: -len(ORIGIN_SUFFIX)].split("."))


def _check_item(i: int, item: Any, errors: List[str]) -> Optional[Caller]:
    n0 = len(errors)
    if not isinstance(item, dict):
        errors.append("item %d: must be a JSON object" % i)
        return None
    for field in sorted(set(item) - set(FIELDS)):
        errors.append("item %d: unknown field %r" % (i, field))
    for field in FIELDS:
        if field not in item:
            errors.append("item %d: missing field '%s'" % (i, field))
    name, digest, scopes, origins, rate = (item.get(f) for f in FIELDS)
    if "name" in item and not (isinstance(name, str) and _NAME_RE.match(name)):
        errors.append("item %d: field 'name' must match [A-Za-z0-9._-]{1,64}" % i)
    elif name == LEGACY:
        errors.append("item %d: field 'name' may not be 'legacy' (reserved for API_KEY)" % i)
    if "key_sha256" in item and not (isinstance(digest, str) and _DIGEST_RE.match(digest)):
        errors.append("item %d: field 'key_sha256' must be 64 lowercase hex characters" % i)
    if "scopes" in item:
        if not isinstance(scopes, list) or not scopes:
            errors.append("item %d: field 'scopes' must be a non-empty array" % i)
        elif not all(isinstance(s, str) and s in SCOPES for s in scopes):
            errors.append("item %d: field 'scopes' has an unknown scope (allowed: %s)" % (i, ", ".join(SCOPES)))
    if "origins" in item:
        if not isinstance(origins, list):
            errors.append("item %d: field 'origins' must be an array" % i)
        else:
            for j, o in enumerate(origins, 1):
                if not origin_allowed(o):
                    errors.append("item %d: field 'origins' entry %d must be https://<name>%s (no port, path or wildcard)"
                                  % (i, j, ORIGIN_SUFFIX))
    if "rate_per_min" in item and not (isinstance(rate, int) and not isinstance(rate, bool) and rate >= 1):
        errors.append("item %d: field 'rate_per_min' must be a positive integer" % i)
    if len(errors) == n0 and bytes.fromhex(digest) == EMPTY_KEY_DIGEST:
        errors.append("item %d: field 'key_sha256' is the digest of an empty key" % i)
    if len(errors) > n0:
        return None
    return Caller(name, bytes.fromhex(digest), frozenset(scopes), frozenset(origins), rate)


def parse_callers(text: str, legacy_digest: Optional[bytes] = None) -> List[Caller]:
    """Validate the whole file; raise SystemExit listing every problem (item numbers start at 1)."""
    try:
        data = json.loads(text)
    except ValueError as e:
        raise SystemExit("CALLERS_FILE is not valid JSON: %s" % e.__class__.__name__)
    if not isinstance(data, list):
        raise SystemExit("CALLERS_FILE must hold a JSON array")
    errors: List[str] = []
    callers = [_check_item(i, item, errors) for i, item in enumerate(data, 1)]
    for field, getter in (("name", lambda c: c.name), ("key_sha256", lambda c: c.digest)):
        seen: Dict[Any, int] = {}
        for i, c in enumerate(callers, 1):
            if c is None:
                continue
            if getter(c) in seen:
                errors.append("items %d and %d: duplicate '%s'" % (seen[getter(c)], i, field))
            seen.setdefault(getter(c), i)
    if legacy_digest is not None:
        for i, c in enumerate(callers, 1):
            if c is not None and c.digest == legacy_digest:
                errors.append("item %d: 'key_sha256' duplicates the legacy API_KEY" % i)
    if errors:
        raise SystemExit("invalid CALLERS_FILE:\n  " + "\n  ".join(errors))
    return [c for c in callers if c is not None]


class CallerRegistry:
    def __init__(self, callers: List[Caller], session_rate_per_min: int = 600,
                 clock: Callable[[], float] = time.monotonic):
        self.callers = list(callers)
        self.session_rate_per_min = session_rate_per_min
        self.clock = clock  # tests may replace it
        self._buckets: Dict[str, Tuple[float, float]] = {}  # name -> (tokens, last refill time)

    @classmethod
    def from_config(cls, cfg: Any, clock: Callable[[], float] = time.monotonic) -> "CallerRegistry":
        if cfg.legacy_rate_per_min < 1 or cfg.session_rate_per_min < 1:
            raise SystemExit("LEGACY_RATE_PER_MIN and SESSION_RATE_PER_MIN must be positive integers")
        callers: List[Caller] = []
        if cfg.api_key:
            callers.append(Caller(LEGACY, digest_of(cfg.api_key), frozenset(SCOPES), frozenset(), cfg.legacy_rate_per_min))
        if cfg.callers_file:
            try:
                text = Path(cfg.callers_file).read_text(encoding="utf-8")
            except OSError as e:
                raise SystemExit("cannot read CALLERS_FILE (%s)" % e.__class__.__name__)
            callers += parse_callers(text, callers[0].digest if callers else None)
        return cls(callers, cfg.session_rate_per_min, clock)

    def authenticate(self, key: str) -> Optional[Caller]:
        """Constant-time compare against every caller's digest; never returns early."""
        given = digest_of(key)
        found: Optional[Caller] = None
        for c in self.callers:
            if hmac.compare_digest(given, c.digest):
                found = c
        return found

    def origin_registered(self, origin: str) -> bool:
        return any(origin in c.origins for c in self.callers)

    def take(self, name: str, rate_per_min: int) -> int:
        """Token bucket (capacity = refill per minute = rate). 0 if a token was taken, else whole seconds to wait (>= 1)."""
        now = self.clock()
        per_sec = rate_per_min / 60.0
        tokens, last = self._buckets.get(name, (float(rate_per_min), now))
        tokens = min(float(rate_per_min), tokens + max(0.0, now - last) * per_sec)
        if tokens >= 1.0:
            self._buckets[name] = (tokens - 1.0, now)
            return 0
        self._buckets[name] = (tokens, now)
        return max(1, int(math.ceil((1.0 - tokens) / per_sec)))


def bearer_key(request: web.Request) -> str:
    parts = request.headers.get("Authorization", "").split(None, 1)
    return parts[1].strip() if len(parts) == 2 and parts[0].lower() == "bearer" else ""


def _deny(status: int, error: str, headers: Optional[Dict[str, str]] = None) -> web.Response:
    return web.json_response({"error": error}, status=status, headers=headers)


def check_access(request: web.Request, scope: str, session_user: Optional[str], session_admin: bool = False) -> Optional[web.Response]:
    """None = let the handler run; otherwise the 401 / 429 / 403 response. Order: key or session, each 401, 429, 403.
    An Authorization header that is not `Bearer <non-empty>` is 401 at once (no lookup, no session fallback).
    A session holds iot:read + poi:read, plus status:read when session_admin (the caller decides with auth.is_admin)."""
    reg: CallerRegistry = request.app["ctx"].callers
    if "Authorization" in request.headers:
        key = bearer_key(request)
        caller = reg.authenticate(key) if key else None
        if caller is None:
            return _deny(401, "unauthorized", {"WWW-Authenticate": "Bearer"})
        request[API_CALLER], request[API_ORIGINS] = caller.name, caller.origins
        wait = reg.take(caller.name, caller.rate_per_min)
        if wait:
            return _deny(429, "rate limit exceeded", {"Retry-After": str(wait)})
        if scope not in caller.scopes:
            return _deny(403, "forbidden")
        return None
    if session_user is None:
        return _deny(401, "unauthorized", {"WWW-Authenticate": "Bearer"})
    request[API_CALLER] = "session:" + session_user
    wait = reg.take(request[API_CALLER], reg.session_rate_per_min)
    if wait:
        return _deny(429, "rate limit exceeded", {"Retry-After": str(wait)})
    if scope not in (SCOPES if session_admin else SESSION_SCOPES):
        return _deny(403, "forbidden")
    return None


def _cors(resp: web.StreamResponse, origin: str) -> None:
    resp.headers["Access-Control-Allow-Origin"] = origin  # always the one registered origin, never "*"
    resp.headers["Vary"] = "Origin"
    resp.headers["Access-Control-Allow-Credentials"] = "true"
    resp.headers["Access-Control-Expose-Headers"] = "Retry-After"  # lets the browser read the 429 wait


def _preflight(request: web.Request, reg: CallerRegistry) -> web.Response:
    origin = request.headers.get("Origin", "")
    method = request.headers.get("Access-Control-Request-Method", "GET")
    resp = web.Response(status=204)
    if origin and method.upper() == "GET" and reg.origin_registered(origin):
        _cors(resp, origin)
        resp.headers["Access-Control-Allow-Methods"] = "GET"
        resp.headers["Access-Control-Allow-Headers"] = "Authorization"
        resp.headers["Access-Control-Max-Age"] = "600"
    return resp


@web.middleware
async def api_middleware(request: web.Request, handler: Any) -> web.StreamResponse:
    """For /api/v1 only: answer preflights, add CORS headers for an authenticated caller's own origins, log one line."""
    if request.path != API_PREFIX and not request.path.startswith(API_PREFIX + "/"):
        return await handler(request)
    status = 500
    try:
        if request.method == "OPTIONS":
            resp: web.StreamResponse = _preflight(request, request.app["ctx"].callers)
        else:
            try:
                resp = await handler(request)
            except web.HTTPException as exc:
                resp = exc
            origin = request.headers.get("Origin", "")
            if origin and origin in request.get(API_ORIGINS, ()):
                _cors(resp, origin)
        status = resp.status
        return resp
    finally:
        log.info("api caller=%s resource=%s status=%d", request.get(API_CALLER, "-"),
                 re.sub(r"[^\x21-\x7e]", "?", request.path), status)
