"""Keep other web pages away from the local API.

Any site the user visits can send requests to `127.0.0.1`. Two checks close that door:

- **Host:** only the loopback names on the server's own port are answered, which defeats
  DNS rebinding (a foreign name that resolves to 127.0.0.1).
- **Origin:** state-changing requests and WebSocket upgrades that carry an `Origin` must
  come from the app itself (or the Vite dev server in dev mode). Browsers always send
  `Origin` on cross-site POSTs and WebSocket handshakes, so a foreign page is refused even
  when its request needs no CORS preflight.
"""

import json
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Receive, Scope, Send

LOOPBACK_NAMES = frozenset({"127.0.0.1", "localhost", "::1"})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
WS_POLICY_VIOLATION = 1008


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key == name:
            return bytes(value).decode("latin-1")
    return None


def _server_port(scope: Scope) -> int | None:
    server = scope.get("server")
    return int(server[1]) if server and server[1] is not None else None


def _split_host(host: str) -> tuple[str, int | None] | None:
    try:
        parts = urlsplit("//" + host)
        return (parts.hostname or "").lower(), parts.port
    except ValueError:
        return None


def host_allowed(host: str | None, port: int | None) -> bool:
    parsed = _split_host(host) if host else None
    return parsed is not None and parsed[0] in LOOPBACK_NAMES and parsed[1] == port


def origin_allowed(origin: str, port: int | None, extra_origins: frozenset[str]) -> bool:
    if origin in extra_origins:
        return True
    parts = urlsplit(origin)
    try:
        origin_port = parts.port
    except ValueError:
        return False
    return (
        parts.scheme == "http"
        and (parts.hostname or "").lower() in LOOPBACK_NAMES
        and origin_port == port
        and parts.path == ""
    )


class LocalOriginGuard:
    """ASGI middleware: refuse foreign hosts, and writes or WebSockets from foreign origins."""

    def __init__(self, app: ASGIApp, extra_origins: frozenset[str] = frozenset()) -> None:
        self.app = app
        self.extra_origins = extra_origins

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        port = _server_port(scope)
        problem: tuple[str, str] | None = None
        if not host_allowed(_header(scope, b"host"), port):
            problem = ("forbidden_host", "The local API only answers its loopback address.")
        elif scope["type"] == "websocket" or scope["method"] not in SAFE_METHODS:
            origin = _header(scope, b"origin")
            if origin is not None and not origin_allowed(origin, port, self.extra_origins):
                problem = ("forbidden_origin", "Requests from other sites are not allowed.")
        if problem is None:
            await self.app(scope, receive, send)
        elif scope["type"] == "websocket":
            # Closing before the handshake reaches the browser as a plain HTTP 403.
            await send({"type": "websocket.close", "code": WS_POLICY_VIOLATION})
        else:
            await _send_forbidden(send, *problem)


async def _send_forbidden(send: Send, code: str, message: str) -> None:
    body = json.dumps({"detail": {"code": code, "message": message}}).encode()
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    await send({"type": "http.response.start", "status": 403, "headers": headers})
    await send({"type": "http.response.body", "body": body})
