"""Session cookie signing, login throttling and request guards. Credentials come from Config only."""
import base64
import hashlib
import hmac
import ipaddress
import json
import secrets
import time
from typing import Awaitable, Callable, Dict, List, Optional
from urllib.parse import quote

from aiohttp import web

COOKIE_NAME = "lutetia_session"


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class SessionSigner:
    def __init__(self, secret: bytes, ttl_seconds: int = 43200):
        self.secret, self.ttl = secret, ttl_seconds
        self._revoked: Dict[str, int] = {}  # signature -> exp, kept until the token would expire anyway

    def _sign(self, payload: str) -> str:
        return hmac.new(self.secret, payload.encode("ascii"), hashlib.sha256).hexdigest()

    def issue(self, user: str, now: Optional[float] = None) -> str:
        now = time.time() if now is None else now
        payload = _b64e(json.dumps({"u": user, "iat": int(now), "n": secrets.token_hex(8), "exp": int(now + self.ttl)}).encode("utf-8"))
        return payload + "." + self._sign(payload)

    def revoke(self, token: str, now: Optional[float] = None) -> None:
        """Server-side logout: remember the signature of a valid token until its exp."""
        now = time.time() if now is None else now
        self._revoked = {s: e for s, e in self._revoked.items() if e >= now}
        payload, sep, sig = (token or "").partition(".")
        if not sep or self.verify(token, now) is None:
            return
        self._revoked[sig] = json.loads(_b64d(payload).decode("utf-8"))["exp"]

    def verify(self, token: str, now: Optional[float] = None) -> Optional[str]:
        now = time.time() if now is None else now
        payload, sep, sig = (token or "").partition(".")
        if not sep or not payload:
            return None
        try:
            if not hmac.compare_digest(self._sign(payload), sig):
                return None
            data = json.loads(_b64d(payload).decode("utf-8"))
            user, exp = data["u"], data["exp"]
        except (ValueError, KeyError, TypeError, UnicodeError):
            return None
        if not isinstance(user, str) or not isinstance(exp, int) or now > exp:
            return None
        if sig in self._revoked:
            return None
        return user


class LoginLimiter:
    """In-memory failure counter. Per IP: the max_failures-th failure locks it for lock_seconds.
    Global: global_max_failures failures from any source within global_window_seconds lock all logins for 60 s."""

    MAX_ENTRIES = 10000

    def __init__(self, max_failures: int = 5, lock_seconds: int = 300, window_seconds: int = 900,
                 global_max_failures: int = 50, global_window_seconds: int = 300):
        self.max_failures, self.lock_seconds, self.window_seconds = max_failures, lock_seconds, window_seconds
        self.global_max_failures, self.global_window_seconds = global_max_failures, global_window_seconds
        self._failures: Dict[str, int] = {}
        self._last_failure: Dict[str, float] = {}
        self._locked_until: Dict[str, float] = {}
        self._recent: List[float] = []
        self._global_locked_until = 0.0

    def is_locked(self, ip: str, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        until = self._locked_until.get(ip)
        if until is None:
            return False
        if now >= until:
            self.reset(ip)
            return False
        return True

    def is_globally_locked(self, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        return now < self._global_locked_until

    def _evict(self, now: float) -> None:
        for ip in [i for i, t in self._last_failure.items() if now - t > self.window_seconds]:
            self.reset(ip)
        while len(self._last_failure) > self.MAX_ENTRIES:
            self.reset(min(self._last_failure, key=self._last_failure.get))

    def record_failure(self, ip: str, now: Optional[float] = None) -> None:
        now = time.time() if now is None else now
        self._evict(now)
        self._failures[ip] = self._failures.get(ip, 0) + 1
        self._last_failure[ip] = now
        self._evict(now)
        if self._failures[ip] >= self.max_failures:
            self._locked_until[ip] = now + self.lock_seconds
        self._recent = [t for t in self._recent if now - t < self.global_window_seconds] + [now]
        if len(self._recent) >= self.global_max_failures:
            self._global_locked_until = now + 60

    def reset(self, ip: str) -> None:
        self._failures.pop(ip, None)
        self._last_failure.pop(ip, None)
        self._locked_until.pop(ip, None)


def check_password(given: str, expected: str) -> bool:
    if not expected:
        return False
    return hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))


_INTERNAL_NETS = [ipaddress.ip_network(n) for n in
                  ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "::1/128")]


def _is_internal(addr: Optional[str]) -> bool:
    try:
        ip = ipaddress.ip_address(addr or "")
    except ValueError:
        return False
    return any(ip.version == n.version and ip in n for n in _INTERNAL_NETS)


def client_ip(request: web.Request, trust_proxy: bool = False) -> str:
    """X-Forwarded-For (last value, appended by the trusted proxy) counts only when the proxy is trusted AND the peer is loopback/private."""
    if trust_proxy and _is_internal(request.remote):
        last = request.headers.get("X-Forwarded-For", "").split(",")[-1].strip()
        if last:
            return last
    return request.remote or "unknown"


Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


def require_session(handler: Handler) -> Handler:
    async def wrapper(request: web.Request) -> web.StreamResponse:
        user = request.app["ctx"].signer.verify(request.cookies.get(COOKIE_NAME, ""))
        if user is None:
            raise web.HTTPFound("/login?next=" + quote(request.path))
        request["user"] = user
        return await handler(request)
    return wrapper


def require_session_json(handler: Handler) -> Handler:
    async def wrapper(request: web.Request) -> web.StreamResponse:
        user = request.app["ctx"].signer.verify(request.cookies.get(COOKIE_NAME, ""))
        if user is None:
            return web.json_response({"error": "login required"}, status=401)
        request["user"] = user
        return await handler(request)
    return wrapper


def require_api_key(handler: Handler) -> Handler:
    async def wrapper(request: web.Request) -> web.StreamResponse:
        expected = request.app["ctx"].cfg.api_key
        header = request.headers.get("Authorization", "")
        parts = header.split(None, 1)
        given = parts[1].strip() if len(parts) == 2 and parts[0].lower() == "bearer" else ""
        if not expected or not check_password(given, expected):
            return web.json_response({"error": "unauthorized"}, status=401, headers={"WWW-Authenticate": "Bearer"})
        return await handler(request)
    return wrapper
