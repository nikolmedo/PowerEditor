from pathlib import Path

import pytest
from pydantic import ValidationError

from autocut.config import REPO_ROOT, Settings


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
