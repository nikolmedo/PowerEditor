"""The local API only answers its own loopback host and refuses cross-site writes."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from powereditor.api.app import create_app
from tests.api_client import LOCAL_BASE_URL, LOCAL_WS_URL, local_client, make_service

SELF_ORIGIN = LOCAL_BASE_URL
VITE_ORIGIN = "http://localhost:5173"
WS_POLICY_VIOLATION = 1008


def _client(tmp_path: Path, *, dev: bool = False) -> TestClient:
    return local_client(create_app(settings_service=make_service(tmp_path), dev_cors=dev))


def _post_settings(client: TestClient, origin: str | None) -> int:
    headers = {"Origin": origin} if origin is not None else {}
    response = client.patch("/api/settings", json={"language": "en"}, headers=headers)
    return int(response.status_code)


@pytest.mark.parametrize("host", ["127.0.0.1:8765", "localhost:8765", "[::1]:8765"])
def test_loopback_hosts_on_the_server_port_are_served(tmp_path: Path, host: str) -> None:
    response = _client(tmp_path).get("/api/health", headers={"Host": host})

    assert response.status_code == 200


@pytest.mark.parametrize(
    "host", ["evil.example:8765", "127.0.0.1:9999", "localhost", "evil.example"]
)
def test_other_hosts_are_refused(tmp_path: Path, host: str) -> None:
    response = _client(tmp_path).get("/api/health", headers={"Host": host})

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "forbidden_host"


@pytest.mark.parametrize(
    "origin", [None, SELF_ORIGIN, "http://localhost:8765", "http://[::1]:8765"]
)
def test_same_origin_or_no_origin_writes_pass(tmp_path: Path, origin: str | None) -> None:
    assert _post_settings(_client(tmp_path), origin) == 200


@pytest.mark.parametrize(
    "origin", ["http://evil.example", "null", "http://127.0.0.1:9999", "https://127.0.0.1:8765"]
)
def test_cross_origin_writes_are_refused(tmp_path: Path, origin: str) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/projects", json={"paths": ["C:/x.mp4"]}, headers={"Origin": origin}
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "forbidden_origin"
    assert client.get("/api/projects").json() == []


def test_cross_origin_reads_are_left_to_cors(tmp_path: Path) -> None:
    response = _client(tmp_path).get("/api/health", headers={"Origin": "http://evil.example"})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize(("dev", "status"), [(False, 403), (True, 200)])
def test_vite_origin_writes_only_in_dev(tmp_path: Path, dev: bool, status: int) -> None:
    assert _post_settings(_client(tmp_path, dev=dev), VITE_ORIGIN) == status


def test_cross_origin_websocket_is_refused(tmp_path: Path) -> None:
    client = _client(tmp_path)

    with (
        pytest.raises(WebSocketDisconnect) as closed,
        client.websocket_connect(
            f"{LOCAL_WS_URL}/api/jobs/unknown/events", headers={"Origin": "http://evil.example"}
        ) as socket,
    ):
        socket.receive_json()

    assert closed.value.code == WS_POLICY_VIOLATION


def test_same_origin_websocket_reaches_the_route(tmp_path: Path) -> None:
    client = _client(tmp_path)

    with (
        pytest.raises(WebSocketDisconnect) as closed,
        client.websocket_connect(
            f"{LOCAL_WS_URL}/api/jobs/unknown/events", headers={"Origin": SELF_ORIGIN}
        ) as socket,
    ):
        socket.receive_json()

    assert closed.value.code == 4404
