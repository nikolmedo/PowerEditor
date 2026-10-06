"""In sidecar mode the API answers only the desktop shell's own session."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from powereditor.api.app import create_app
from powereditor.api.session_token import TOKEN_COOKIE, TOKEN_HEADER
from tests.api_client import LOCAL_WS_URL, local_client, make_service

TOKEN = "s3cret-session-token"
WS_POLICY_VIOLATION = 1008
UNKNOWN_JOB_CLOSE = 4404


def _client(tmp_path: Path, token: str | None = TOKEN) -> TestClient:
    web_dir = tmp_path / "web"
    web_dir.mkdir(exist_ok=True)
    (web_dir / "index.html").write_text("<!doctype html><title>app</title>", encoding="utf-8")
    app = create_app(
        settings_service=make_service(tmp_path / "data"), web_dir=web_dir, session_token=token
    )
    return local_client(app)


def test_api_requests_without_the_token_are_refused(tmp_path: Path) -> None:
    response = _client(tmp_path).get("/api/health")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "session_token_required"


@pytest.mark.parametrize("value", ["wrong", ""])
def test_a_wrong_token_header_is_refused(tmp_path: Path, value: str) -> None:
    response = _client(tmp_path).get("/api/health", headers={TOKEN_HEADER: value})

    assert response.status_code == 401


def test_the_token_header_opens_the_api(tmp_path: Path) -> None:
    response = _client(tmp_path).get("/api/health", headers={TOKEN_HEADER: TOKEN})

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_the_bootstrap_url_sets_the_cookie_and_drops_the_token(tmp_path: Path) -> None:
    client = _client(tmp_path)

    bootstrap = client.get(f"/?token={TOKEN}", follow_redirects=False)

    assert bootstrap.status_code == 303
    assert bootstrap.headers["location"] == "/"
    cookie = bootstrap.headers["set-cookie"]
    assert cookie.startswith(f"{TOKEN_COOKIE}={TOKEN};")
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert client.get("/api/health").status_code == 200


def test_a_wrong_bootstrap_token_sets_no_cookie(tmp_path: Path) -> None:
    client = _client(tmp_path)

    page = client.get("/?token=guess", follow_redirects=False)

    assert page.status_code == 200
    assert "set-cookie" not in page.headers
    assert client.get("/api/health").status_code == 401


def test_the_web_app_itself_needs_no_token(tmp_path: Path) -> None:
    page = _client(tmp_path).get("/projects/demo/review")

    assert page.status_code == 200
    assert "<title>app</title>" in page.text


def test_websockets_need_the_token(tmp_path: Path) -> None:
    client = _client(tmp_path)

    with (
        pytest.raises(WebSocketDisconnect) as refused,
        client.websocket_connect(f"{LOCAL_WS_URL}/api/jobs/unknown/events") as socket,
    ):
        socket.receive_json()
    assert refused.value.code == WS_POLICY_VIOLATION

    client.cookies.set(TOKEN_COOKIE, TOKEN)
    with (
        pytest.raises(WebSocketDisconnect) as reached,
        client.websocket_connect(f"{LOCAL_WS_URL}/api/jobs/unknown/events") as socket,
    ):
        socket.receive_json()
    assert reached.value.code == UNKNOWN_JOB_CLOSE


def test_without_a_session_token_the_api_stays_open(tmp_path: Path) -> None:
    assert _client(tmp_path, token=None).get("/api/health").status_code == 200
