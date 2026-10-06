import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from powereditor.api.app import create_app
from powereditor.config import Settings
from powereditor.paths import AppPaths
from powereditor.settings_store import InMemorySecretStore, SettingsService

SECRET = "sk-super-secret-value"


def _service(data_dir: Path, env: Settings | None = None) -> SettingsService:
    return SettingsService(
        paths=AppPaths(data_dir=data_dir),
        secrets=InMemorySecretStore(),
        env=env or Settings(_env_file=None),
        cuda_available=lambda: False,
    )


def _client(
    service: SettingsService,
    handler: Callable[[httpx.Request], httpx.Response] | None = None,
) -> TestClient:
    transport = httpx.MockTransport(handler) if handler is not None else None
    return TestClient(create_app(settings_service=service, openai_transport=transport))


def test_health(tmp_path: Path) -> None:
    response = _client(_service(tmp_path)).get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_get_settings_returns_camel_case_effective_values(tmp_path: Path) -> None:
    body = _client(_service(tmp_path)).get("/api/settings").json()

    assert body["settings"]["silencePaddingMs"] == 120
    assert body["settings"]["whisperModel"] is None
    assert body["resolvedWhisperModel"] == "small"
    assert body["secrets"] == {
        "openaiApiKey": {"set": False, "source": None},
        "typesafeApiKey": {"set": False, "source": None},
    }


def test_patch_settings_persists_partial_update(tmp_path: Path) -> None:
    service = _service(tmp_path)
    client = _client(service)

    response = client.patch("/api/settings", json={"transcriber": "openai", "targetLufs": -16})

    assert response.status_code == 200
    assert response.json()["settings"]["transcriber"] == "openai"
    assert service.get_effective().target_lufs == -16.0
    assert client.get("/api/settings").json()["settings"]["transcriber"] == "openai"


def test_patch_settings_rejects_invalid_values(tmp_path: Path) -> None:
    client = _client(_service(tmp_path))

    assert client.patch("/api/settings", json={"whisperDevice": "tpu"}).status_code == 422
    assert client.patch("/api/settings", json={"bogus": True}).status_code == 422
    assert client.get("/api/settings").json()["settings"]["whisperDevice"] == "auto"


def test_secret_lifecycle_never_exposes_value(tmp_path: Path) -> None:
    service = _service(tmp_path)
    client = _client(service)

    put = client.put("/api/secrets/openai_api_key", json={"value": SECRET})
    settings = client.get("/api/settings")

    assert put.status_code == 200
    assert put.json() == {"set": True, "source": "keyring"}
    assert settings.json()["secrets"]["openaiApiKey"] == {"set": True, "source": "keyring"}
    assert SECRET not in put.text + settings.text
    assert service.get_secret("openai_api_key") == SECRET

    deleted = client.delete("/api/secrets/openai_api_key")
    assert deleted.json() == {"set": False, "source": None}
    assert service.get_secret("openai_api_key") is None


def test_unknown_secret_name_is_not_found(tmp_path: Path) -> None:
    client = _client(_service(tmp_path))

    assert client.put("/api/secrets/aws_key", json={"value": "x"}).status_code == 404
    assert client.delete("/api/secrets/aws_key").status_code == 404


def test_blank_secret_is_rejected_without_echo(tmp_path: Path) -> None:
    response = _client(_service(tmp_path)).put(
        "/api/secrets/typesafe_api_key", json={"value": "   "}
    )

    assert response.status_code == 422


def test_openai_key_test_reports_success_and_sends_bearer(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": []})

    service = _service(tmp_path)
    service.set_secret("openai_api_key", SECRET)

    response = _client(service, handler).post("/api/secrets/openai_api_key/test")

    assert response.json()["ok"] is True
    assert len(seen) == 1
    assert str(seen[0].url) == "https://api.openai.com/v1/models"
    assert seen[0].headers["Authorization"] == f"Bearer {SECRET}"
    assert SECRET not in response.text


@pytest.mark.parametrize(
    ("handler_result", "detail_fragment"),
    [
        (httpx.Response(401, json={"error": {"message": f"bad key {SECRET}"}}), "rejected"),
        (httpx.Response(503), "HTTP 503"),
        (httpx.ConnectError("offline"), "Could not reach"),
    ],
)
def test_openai_key_test_reports_failures(
    tmp_path: Path, handler_result: httpx.Response | Exception, detail_fragment: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if isinstance(handler_result, Exception):
            raise handler_result
        return handler_result

    service = _service(tmp_path)
    service.set_secret("openai_api_key", SECRET)

    response = _client(service, handler).post("/api/secrets/openai_api_key/test")

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert detail_fragment in response.json()["detail"]
    assert SECRET not in response.text


def test_openai_key_test_without_key_skips_network(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("network must not be called")

    response = _client(_service(tmp_path), handler).post("/api/secrets/openai_api_key/test")

    assert response.json() == {"ok": False, "detail": "No OpenAI API key is configured."}


def test_doctor_endpoint_returns_camel_case_report(tmp_path: Path) -> None:
    def runner(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(list(args), 0, stdout="tool 1.0", stderr="")

    app = create_app(settings_service=_service(tmp_path), doctor_runner=runner)

    body = TestClient(app).get("/api/doctor").json()

    assert "pythonVersion" in body
    assert isinstance(body["ok"], bool)
    assert [check["name"] for check in body["checks"]] == [
        "ffmpeg",
        "ffprobe",
        "node",
        "pnpm",
        "cuda",
    ]


def test_validation_errors_do_not_echo_request_body(tmp_path: Path) -> None:
    response = _client(_service(tmp_path)).put("/api/secrets/openai_api_key", json={"val": SECRET})

    assert response.status_code == 422
    assert SECRET not in response.text


def test_default_app_uses_isolated_stores(isolated_environment: Path) -> None:
    body = TestClient(create_app()).get("/api/settings").json()

    assert body["secrets"]["openaiApiKey"] == {"set": False, "source": None}
    assert body["secrets"]["typesafeApiKey"] == {"set": False, "source": None}
