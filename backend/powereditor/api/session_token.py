"""Require the desktop shell's session token on the API (sidecar mode only).

`serve --port 0` draws a random token and prints it on the READY line, so only the process
that started the server knows it. Every `/api` request and WebSocket must carry it, either
in the `X-PowerEditor-Token` header (scripts, tests) or in an HttpOnly cookie. The shell
loads `/?token=<token>` once: the answer sets the cookie and redirects to `/`, which keeps
the token out of the page's URL and away from its scripts. The web app itself (`/` and its
assets) holds no data and is served without the token.
"""

import json
import secrets
from http.cookies import SimpleCookie
from urllib.parse import parse_qs

from starlette.types import ASGIApp, Receive, Scope, Send

TOKEN_HEADER = "X-PowerEditor-Token"
TOKEN_COOKIE = "powereditor_session"
TOKEN_QUERY = "token"
WS_POLICY_VIOLATION = 1008


def _headers(scope: Scope) -> dict[bytes, str]:
    return {bytes(key): bytes(value).decode("latin-1") for key, value in scope["headers"]}


def _is_api(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


def _cookie_token(headers: dict[bytes, str]) -> str | None:
    cookies: SimpleCookie = SimpleCookie()
    try:
        cookies.load(headers.get(b"cookie", ""))
    except ValueError:
        return None
    morsel = cookies.get(TOKEN_COOKIE)
    return morsel.value if morsel is not None else None


class SessionTokenGuard:
    """ASGI middleware: `/api` answers only requests that carry the session token."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.token = token

    def _matches(self, candidate: str | None) -> bool:
        return bool(candidate) and secrets.compare_digest(
            str(candidate).encode(), self.token.encode()
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        path = str(scope["path"])
        headers = _headers(scope)
        if not _is_api(path):
            if scope["type"] == "http" and scope["method"] in ("GET", "HEAD"):
                query = parse_qs(bytes(scope["query_string"]).decode("latin-1"))
                if self._matches(next(iter(query.get(TOKEN_QUERY, [])), None)):
                    await self._bootstrap(send)
                    return
            await self.app(scope, receive, send)
            return
        presented = headers.get(TOKEN_HEADER.lower().encode()) or _cookie_token(headers)
        if self._matches(presented):
            await self.app(scope, receive, send)
        elif scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": WS_POLICY_VIOLATION})
        else:
            await _send_unauthorized(send)

    async def _bootstrap(self, send: Send) -> None:
        cookie = f"{TOKEN_COOKIE}={self.token}; Path=/; HttpOnly; SameSite=strict"
        headers = [
            (b"location", b"/"),
            (b"set-cookie", cookie.encode("latin-1")),
            (b"cache-control", b"no-store"),
            (b"content-length", b"0"),
        ]
        await send({"type": "http.response.start", "status": 303, "headers": headers})
        await send({"type": "http.response.body", "body": b""})


async def _send_unauthorized(send: Send) -> None:
    body = json.dumps(
        {
            "detail": {
                "code": "session_token_required",
                "message": "This server only answers the PowerEditor app that started it.",
            }
        }
    ).encode()
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    await send({"type": "http.response.start", "status": 401, "headers": headers})
    await send({"type": "http.response.body", "body": body})
