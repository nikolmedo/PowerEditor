import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from powereditor.config import REPO_ROOT, Settings, env_files


def test_env_example_parses_with_inline_comments() -> None:
    settings = Settings(_env_file=REPO_ROOT / ".env.example")

    assert settings.transcriber == "local"
    assert settings.whisper_model == "large-v3-turbo"
    assert settings.whisper_device == "auto"
    assert settings.decision_engine == "heuristic"
    assert settings.jev_min_confidence == 0.8
    assert settings.silence_padding_ms == 120
    assert settings.target_lufs == -14.0
    assert settings.openai_api_key is None


def test_invalid_enum_value_is_rejected(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("TRANSCRIBER=cloud\n", encoding="utf-8")

    with pytest.raises(ValidationError):
        Settings(_env_file=env_file)


def test_source_runs_read_dotenv_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("WHISPER_MODEL=tiny\n", encoding="utf-8")

    assert Settings(_env_file=env_files()).whisper_model == "tiny"


def test_frozen_builds_ignore_dotenv_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A packaged app must not pick up a stray `.env` from whatever folder it starts in."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    (tmp_path / ".env").write_text("WHISPER_MODEL=tiny\n", encoding="utf-8")

    assert env_files() == ()
    assert Settings(_env_file=env_files()).whisper_model is None
