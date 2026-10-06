import json
import sys
from pathlib import Path
from typing import Any

import pytest

from powereditor.providers.base import JudgmentRequest, ProviderError
from powereditor.providers.config import ProviderConfig
from powereditor.providers.local_cli.base import LocalCliProvider
from powereditor.providers.local_cli.claude import ClaudeCliProvider
from powereditor.providers.local_cli.codex import CodexCliProvider
from powereditor.providers.local_cli.gemini import GeminiCliProvider
from powereditor.providers.registry import ProviderContext, default_registry

FAKE_CLI = Path(__file__).parent / "fixtures" / "fake_cli.py"
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"same": {"type": "boolean"}, "confidence": {"type": "number"}},
    "required": ["same", "confidence"],
    "additionalProperties": False,
}
PROVIDERS: dict[str, type[LocalCliProvider]] = {
    "codex": CodexCliProvider,
    "gemini": GeminiCliProvider,
    "claude": ClaudeCliProvider,
}


@pytest.fixture
def record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "record.json"
    monkeypatch.setenv("FAKE_CLI_RECORD", str(path))
    return path


def _fake(flavor: str, timeout_s: float = 60.0) -> LocalCliProvider:
    command = [sys.executable, str(FAKE_CLI), flavor]
    return PROVIDERS[flavor](command, timeout_s=timeout_s)


def _request() -> JudgmentRequest:
    return JudgmentRequest(
        instructions="Same line?",
        state={"a": "¿se oye?", "b": "hola"},
        output_schema=SCHEMA,
        model="model-1",
    )


@pytest.mark.parametrize("flavor", ["codex", "gemini", "claude"])
def test_judge_sends_prompt_on_stdin_and_validates_output(flavor: str, record: Path) -> None:
    result = _fake(flavor).judge(_request())

    invocation = json.loads(record.read_text(encoding="utf-8"))
    assert result.output == {"same": True, "confidence": 0.9}
    assert result.usage is not None
    assert result.usage.input_tokens is not None
    assert "¿se oye?" in invocation["stdin"]
    assert "model-1" in invocation["args"]
    assert all("¿se oye?" not in arg for arg in invocation["args"])


def test_codex_runs_read_only_with_output_schema(record: Path) -> None:
    _fake("codex").judge(_request())

    args = json.loads(record.read_text(encoding="utf-8"))["args"]
    assert args[:2] == ["exec", "--json"]
    assert args[args.index("--sandbox") + 1] == "read-only"
    assert "--output-schema" in args
    assert "--ephemeral" in args
    assert args[-1] == "-"


def test_claude_disables_tools_and_passes_json_schema(record: Path) -> None:
    _fake("claude").judge(_request())

    args = json.loads(record.read_text(encoding="utf-8"))["args"]
    assert args[0] == "-p"
    assert args[args.index("--tools") + 1] == ""
    assert json.loads(args[args.index("--json-schema") + 1]) == SCHEMA
    assert "--no-session-persistence" in args
    assert "--bare" not in args


def test_gemini_runs_in_read_only_plan_mode_with_schema_in_prompt(record: Path) -> None:
    _fake("gemini").judge(_request())

    invocation = json.loads(record.read_text(encoding="utf-8"))
    assert invocation["args"][invocation["args"].index("--approval-mode") + 1] == "plan"
    assert '"additionalProperties": false' in invocation["stdin"]


def test_claude_falls_back_to_result_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_CLI_MODE", "text_only")

    assert _fake("claude").judge(_request()).output == {"same": True, "confidence": 0.9}


@pytest.mark.parametrize("flavor", ["codex", "gemini", "claude"])
def test_garbage_output_is_bad_output(flavor: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_CLI_MODE", "garbage")

    with pytest.raises(ProviderError) as caught:
        _fake(flavor).judge(_request())

    assert caught.value.code == "provider_bad_output"


@pytest.mark.parametrize("flavor", ["codex", "gemini", "claude"])
def test_auth_failures_are_unauthorized(flavor: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_CLI_MODE", "auth_error")

    with pytest.raises(ProviderError) as caught:
        _fake(flavor).judge(_request())

    assert caught.value.code == "provider_unauthorized"


def test_timeout_kills_the_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_CLI_MODE", "sleep")

    with pytest.raises(ProviderError) as caught:
        _fake("claude", timeout_s=1.0).judge(_request())

    assert caught.value.code == "provider_timeout"


def test_unsafe_model_names_are_rejected_before_running() -> None:
    request = _request().model_copy(update={"model": "gpt & calc"})

    with pytest.raises(ProviderError) as caught:
        _fake("gemini").judge(request)

    assert caught.value.code == "provider_unavailable"
    assert "model" in caught.value.message


@pytest.mark.parametrize(
    ("flavor", "authenticated"), [("codex", True), ("claude", True), ("gemini", None)]
)
def test_check_reports_version_and_auth(flavor: str, authenticated: bool | None) -> None:
    check = _fake(flavor).check()

    assert check.ok is True
    assert check.version == f"{flavor} 9.9.9"
    assert check.authenticated is authenticated


@pytest.mark.parametrize("flavor", ["codex", "claude"])
def test_check_reports_logged_out(flavor: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAKE_CLI_MODE", "auth_error")

    check = _fake(flavor).check()

    assert check.ok is False
    assert check.authenticated is False


def test_missing_executable_is_cli_not_found(tmp_path: Path) -> None:
    config = ProviderConfig(
        id="codex-cli",
        kind="openai",
        transport="local_cli",
        label="Codex",
        cli_path=str(tmp_path / "missing" / "codex.exe"),
    )
    provider = default_registry().create(config, ProviderContext(which=lambda name: None))

    with pytest.raises(ProviderError) as caught:
        provider.judge(_request())
    check = provider.check()

    assert caught.value.code == "cli_not_found"
    assert check.ok is False
    assert "not found" in check.detail


def test_static_model_lists_are_offered() -> None:
    models = _fake("claude").list_models()

    assert [m.id for m in models][:3] == ["sonnet", "opus", "haiku"]
    assert models[0].note
