"""Phase 4a review follow-ups: base URL and CLI path trust, error mapping, retries, routes."""

import sys
import time
from pathlib import Path
from typing import Any

import httpx
import keyring.errors
import pytest
from fastapi.testclient import TestClient

from powereditor.api.app import create_app
from powereditor.config import Settings
from powereditor.paths import AppPaths
from powereditor.providers.base import (
    CheckResult,
    JudgmentRequest,
    JudgmentResult,
    ModelInfo,
    ProviderContext,
    ProviderError,
    Transport,
)
from powereditor.providers.config import ProviderConfig, base_url_problem
from powereditor.providers.local_cli import base as cli_base
from powereditor.providers.local_cli.base import CliOutput, LocalCliProvider, resolve_command
from powereditor.providers.local_cli.claude import ClaudeCliProvider
from powereditor.providers.registry import default_registry
from powereditor.settings_store import InMemorySecretStore, SettingsService

FAKE_CLI = Path(__file__).parent / "fixtures" / "fake_cli.py"
KEY = "sk-hardening-key"
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"same": {"type": "boolean"}},
    "required": ["same"],
    "additionalProperties": False,
}


def _config(kind: str = "openai", **extra: Any) -> ProviderConfig:
    return ProviderConfig(id="p1", kind=kind, transport="api", label="P1", **extra)


def _request() -> JudgmentRequest:
    return JudgmentRequest(instructions="Same?", state={"a": "x"}, output_schema=SCHEMA, model="m")


# --- base_url -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "url", "confirmed", "allowed"),
    [
        ("openai", None, False, True),
        ("openai", "https://api.openai.com/v1", False, True),
        ("anthropic", "https://api.anthropic.com/v1", False, True),
        ("openai", "https://evil.example.com/v1", False, False),
        ("openai", "https://evil.example.com/v1", True, True),
        ("openai", "http://api.openai.com/v1", True, False),
        ("openai", "http://localhost:11434/v1", True, True),
        ("openai", "http://127.0.0.1:8080", False, False),
        ("openai", "https://user:pass@api.openai.com/v1", True, False),
        ("deepseek", "https://api.openai.com/v1", False, False),
    ],
)
def test_base_url_trust_rules(kind: str, url: str | None, confirmed: bool, allowed: bool) -> None:
    config = _config(kind, base_url=url, custom_base_url_confirmed=confirmed)

    assert (base_url_problem(config) is None) is allowed


def test_untrusted_base_url_never_receives_the_key() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": []})

    context = ProviderContext(api_key=KEY, http_transport=httpx.MockTransport(handler))
    config = _config(base_url="https://evil.example.com/v1")

    with pytest.raises(ProviderError) as caught:
        default_registry().create(config, context).list_models()

    assert caught.value.code == "provider_unavailable"
    assert KEY not in caught.value.message
    assert seen == []


# --- cli_path -------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["claude", "claude.exe", "Claude.CMD", "claude.bat"])
def test_cli_path_accepts_the_expected_client_name(tmp_path: Path, name: str) -> None:
    path = tmp_path / name
    path.write_text("", encoding="utf-8")

    assert resolve_command("claude", str(path), lambda _: None) == [str(path)]


@pytest.mark.parametrize("name", ["evil.exe", "claude.ps1", "claude-wrapper.exe"])
def test_cli_path_rejects_other_binaries(tmp_path: Path, name: str) -> None:
    path = tmp_path / name
    path.write_text("", encoding="utf-8")

    with pytest.raises(ProviderError) as caught:
        resolve_command("claude", str(path), lambda _: None)

    assert caught.value.code == "cli_not_found"
    assert "claude" in caught.value.message


def test_cli_path_must_be_a_file(tmp_path: Path) -> None:
    folder = tmp_path / "claude.exe"
    folder.mkdir()

    assert resolve_command("claude", str(folder), lambda _: None) is None


# --- error mapping --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("message", "code"),
    [
        ("401 Unauthorized: please login", "provider_unauthorized"),
        ("Not logged in", "provider_unauthorized"),
        ("Please log in again", "provider_unauthorized"),
        ("Invalid API key provided", "provider_unauthorized"),
        ("The author of this line is unknown", "provider_unavailable"),
        ("Failed to load auth_cache plugin; 4012 bytes read", "provider_unavailable"),
        ("Rate limit reached for login.example tokens", "provider_unavailable"),
    ],
)
def test_auth_detection_is_narrow(message: str, code: str) -> None:
    provider = ClaudeCliProvider(None)

    error = provider._failure(CliOutput(1, "", ""), message)

    assert error.code == code


def test_anthropic_malformed_model_list_is_bad_output() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"display_name": "no id"}], "has_more": False})

    context = ProviderContext(api_key=KEY, http_transport=httpx.MockTransport(handler))
    provider = default_registry().create(_config("anthropic"), context)

    with pytest.raises(ProviderError) as caught:
        provider.list_models()

    assert caught.value.code == "provider_bad_output"


# --- retries --------------------------------------------------------------------------


def _counting(error: type[httpx.TransportError]) -> tuple[list[str], Any]:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        raise error("broken", request=request)

    return calls, handler


def test_read_error_on_post_is_not_retried() -> None:
    calls, handler = _counting(httpx.ReadError)
    context = ProviderContext(
        api_key=KEY, http_transport=httpx.MockTransport(handler), sleep=lambda _: None
    )

    with pytest.raises(ProviderError) as caught:
        default_registry().create(_config(), context).judge(_request())

    assert caught.value.code == "provider_unavailable"
    assert calls == ["POST"]


def test_read_error_on_get_is_retried() -> None:
    calls, handler = _counting(httpx.ReadError)
    context = ProviderContext(
        api_key=KEY, http_transport=httpx.MockTransport(handler), sleep=lambda _: None
    )

    with pytest.raises(ProviderError):
        default_registry().create(_config(), context).list_models()

    assert calls == ["GET", "GET", "GET"]


def test_connect_error_on_post_is_retried() -> None:
    calls, handler = _counting(httpx.ConnectError)
    context = ProviderContext(
        api_key=KEY, http_transport=httpx.MockTransport(handler), sleep=lambda _: None
    )

    with pytest.raises(ProviderError):
        default_registry().create(_config(), context).judge(_request())

    assert calls == ["POST", "POST", "POST"]


# --- CLI timeout ----------------------------------------------------------------------


def test_cli_timeout_returns_even_if_the_tree_survives_the_kill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_CLI_MODE", "sleep")
    monkeypatch.setattr(cli_base, "kill_tree", lambda process: None)
    monkeypatch.setattr(cli_base, "KILL_GRACE_S", 0.5)
    provider = ClaudeCliProvider([sys.executable, str(FAKE_CLI), "claude"], timeout_s=1.0)

    started = time.perf_counter()
    with pytest.raises(ProviderError) as caught:
        provider.judge(_request())

    assert caught.value.code == "provider_timeout"
    assert time.perf_counter() - started < 15


# --- routes ---------------------------------------------------------------------------


class _FailingDeleteStore(InMemorySecretStore):
    def delete(self, name: str) -> None:
        raise keyring.errors.KeyringError("locked")


def _service(tmp_path: Path, secrets: InMemorySecretStore) -> SettingsService:
    return SettingsService(
        paths=AppPaths(data_dir=tmp_path),
        secrets=secrets,
        env=Settings(_env_file=None),
        cuda_available=lambda: False,
    )


def test_delete_keeps_provider_and_assignments_when_the_secret_cannot_be_cleared(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path, _FailingDeleteStore())
    client = TestClient(create_app(settings_service=service))
    client.post("/api/providers", json={"kind": "openai", "transport": "api", "label": "O"})
    ref = {"providerId": "openai-api", "model": "gpt-a"}
    client.put("/api/features/models", json={"features": {"topic_change": ref}})

    response = client.delete("/api/providers/openai-api")

    assert response.status_code == 503
    assert service.provider("openai-api") is not None
    assert client.get("/api/features/models").json()["features"]["topic_change"] == ref


def test_create_rejects_an_untrusted_base_url(tmp_path: Path) -> None:
    client = TestClient(create_app(settings_service=_service(tmp_path, InMemorySecretStore())))
    body = {"kind": "openai", "transport": "api", "label": "O"}

    rejected = client.post("/api/providers", json={**body, "baseUrl": "https://evil.example"})
    confirmed = client.post(
        "/api/providers",
        json={**body, "baseUrl": "https://evil.example", "customBaseUrlConfirmed": True},
    )

    assert rejected.status_code == 422
    assert confirmed.status_code == 201
    assert confirmed.json()["customBaseUrlConfirmed"] is True


class _StubCli(LocalCliProvider):
    kind = "openai"
    label = "Stub CLI"
    executable = "stub"
    models = (ModelInfo(id="stub-model"),)
    transport: Transport = "local_cli"

    def check(self) -> CheckResult:
        return CheckResult(ok=True, version="stub 1.0", authenticated=True, detail="Signed in.")

    def judge(self, request: JudgmentRequest) -> JudgmentResult:
        raise AssertionError("the test endpoint must not send a prompt")


def test_test_endpoint_checks_a_local_cli_provider(tmp_path: Path) -> None:
    registry = default_registry()
    registry.register("stubkind", "local_cli", lambda config, context: _StubCli(None))
    service = _service(tmp_path, InMemorySecretStore())
    client = TestClient(create_app(settings_service=service, provider_registry=registry))
    client.post(
        "/api/providers", json={"kind": "stubkind", "transport": "local_cli", "label": "Stub"}
    )

    result = client.post("/api/providers/stubkind-local-cli/test").json()

    assert result == {
        "ok": True,
        "detail": "Signed in.",
        "code": None,
        "version": "stub 1.0",
        "authenticated": True,
    }


def test_test_endpoint_reports_a_rejected_cli_path(tmp_path: Path) -> None:
    impostor = tmp_path / "evil.exe"
    impostor.write_text("", encoding="utf-8")
    client = TestClient(create_app(settings_service=_service(tmp_path, InMemorySecretStore())))
    client.post(
        "/api/providers",
        json={
            "kind": "anthropic",
            "transport": "local_cli",
            "label": "C",
            "cliPath": str(impostor),
        },
    )

    result = client.post("/api/providers/anthropic-local-cli/test").json()

    assert result["ok"] is False
    assert result["code"] == "cli_not_found"
