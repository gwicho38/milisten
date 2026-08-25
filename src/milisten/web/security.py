"""Loopback-only security middleware, following the prview pattern.

Two gates on every API request:
  1. Host and Origin must be this server's own loopback identity, which blocks
     cross-origin drivers and DNS rebinding.
  2. A per-session token (header X-Milisten-Token or ?token=) must match the one
     minted at launch.

The initial HTML and static assets skip the token gate so the browser can load
the page that carries the token; they still pass the Host/Origin gate. Audio is
exempt too: a media element issues range requests without custom headers, and
the query token cannot ride along once the browser retries internally.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

TOKEN_HEADER = "X-Milisten-Token"
_LOOPBACK = {"127.0.0.1", "localhost", "[::1]", "::1"}
_EXEMPT_PREFIXES = ("/static", "/audio")
_EXEMPT_PATHS = {"/", "/index.html", "/favicon.ico"}


def _bare_host(value: str) -> str:
    host = value.rsplit(":", 1)[0] if value.count(":") == 1 else value
    return host.strip("[]")


def host_is_loopback(host_header: str) -> bool:
    if not host_header:
        return True
    return _bare_host(host_header) in _LOOPBACK


def origin_is_loopback(origin: str) -> bool:
    if not origin:
        return True
    rest = origin.split("://", 1)[-1].split("/", 1)[0]
    return _bare_host(rest) in _LOOPBACK


def is_exempt(path: str) -> bool:
    return path in _EXEMPT_PATHS or path.startswith(_EXEMPT_PREFIXES)


def _reject(status: int, error: str, hint: str | None = None) -> JSONResponse:
    body = {"error": error}
    if hint:
        body["hint"] = hint
    return JSONResponse(body, status_code=status)


class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not host_is_loopback(request.headers.get("host", "")):
            return _reject(403, "Forbidden Host header", "requests must target 127.0.0.1")
        if not origin_is_loopback(request.headers.get("origin", "")):
            return _reject(403, "Forbidden Origin header", "cross-origin requests are blocked")

        if not is_exempt(request.url.path):
            expected = getattr(request.app.state, "session_token", None)
            supplied = request.headers.get(TOKEN_HEADER) or request.query_params.get("token")
            if not expected or supplied != expected:
                return _reject(
                    401,
                    "Missing or invalid session token",
                    "reopen the URL printed by `milisten ui`",
                )

        return await call_next(request)
