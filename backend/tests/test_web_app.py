import os
import socket
import time
import webbrowser
from pathlib import Path

import httpx
import pytest
import uvicorn
from typer.testing import CliRunner

from powereditor import cli
from powereditor.api.app import ENV_DEV_CORS, create_app, resolve_web_dir
from powereditor.config import REPO_ROOT
from powereditor.resources import ENV_WEB_DIR
from tests.api_client import local_client, make_client, make_service


@pytest.fixture
def web_dir(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>", encoding="utf-8")
    (dist / "assets" / "main-1a2b.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("secret", encoding="utf-8")
    return dist


def test_serves_index_assets_and_spa_fallback(tmp_path: Path, web_dir: Path) -> None:
    client = make_client(tmp_path / "data", web_dir=web_dir)

    index = client.get("/")
    asset = client.get("/assets/main-1a2b.js")
    deep_link = client.get("/projects/p-1/review")

    assert index.text == "<html>app</html>"
    assert index.headers["content-type"].startswith("text/html")
    assert asset.text == "console.log(1)"
    assert "javascript" in asset.headers["content-type"]
    assert deep_link.text == "<html>app</html>"


def test_api_paths_never_fall_back_to_the_app(tmp_path: Path, web_dir: Path) -> None:
    client = make_client(tmp_path / "data", web_dir=web_dir)

    missing = client.get("/api/does-not-exist")
    health = client.get("/api/health")

    assert missing.status_code == 404
    assert missing.headers["content-type"] == "application/json"
    assert health.json()["status"] == "ok"


def test_web_files_cannot_escape_the_build(tmp_path: Path, web_dir: Path) -> None:
    client = make_client(tmp_path / "data", web_dir=web_dir)

    escaped = client.get("/%2E%2E/outside.txt")

    assert "secret" not in escaped.text


def test_missing_build_is_reported(tmp_path: Path) -> None:
    response = make_client(tmp_path / "data").get("/")

    assert response.status_code == 404
    assert "not built" in response.json()["detail"]


def test_web_dir_resolution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_WEB_DIR, str(tmp_path / "custom"))
    assert resolve_web_dir() == tmp_path / "custom"
    monkeypatch.delenv(ENV_WEB_DIR)
    assert resolve_web_dir() == REPO_ROOT / "web" / "dist"


@pytest.mark.parametrize(("dev", "allowed"), [(True, "http://localhost:5173"), (False, None)])
def test_cors_only_for_the_vite_dev_server(tmp_path: Path, dev: bool, allowed: str | None) -> None:
    client = local_client(create_app(settings_service=make_service(tmp_path), dev_cors=dev))

    vite = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    other = client.get("/api/health", headers={"Origin": "http://evil.example"})

    assert vite.headers.get("access-control-allow-origin") == allowed
    assert "access-control-allow-origin" not in other.headers


def test_serve_open_and_dev_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    started: list[int] = []

    def fake_run(self: uvicorn.Server, sockets: list[socket.socket]) -> None:
        started.append(sockets[0].getsockname()[1])
        sockets[0].close()

    monkeypatch.setattr(cli, "open_when_ready", opened.append)
    monkeypatch.setattr(uvicorn.Server, "run", fake_run)
    monkeypatch.setenv(ENV_DEV_CORS, "0")  # restored after the test, as serve sets it

    result = CliRunner().invoke(cli.app, ["serve", "--port", "0", "--open", "--dev"])

    assert result.exit_code == 0, result.output
    assert len(started) == 1 and started[0] > 0
    assert opened == [f"http://127.0.0.1:{started[0]}"]
    assert os.environ[ENV_DEV_CORS] == "1"


def test_open_when_ready_waits_for_health(monkeypatch: pytest.MonkeyPatch) -> None:
    answers: list[httpx.Response | httpx.HTTPError] = [
        httpx.ConnectError("refused"),
        httpx.Response(200),
    ]
    opened: list[str] = []

    def fake_get(url: str, timeout: float) -> httpx.Response:
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(time, "sleep", lambda _: None)
    monkeypatch.setattr(webbrowser, "open", opened.append)

    cli.open_when_ready("http://127.0.0.1:1").join(5)

    assert opened == ["http://127.0.0.1:1/"]
