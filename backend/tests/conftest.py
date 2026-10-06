from collections.abc import Iterator
from pathlib import Path

import pytest

from autocut import settings_store
from autocut.config import Settings
from autocut.paths import ENV_DATA_DIR

ENV_SETTING_NAMES = (
    "TRANSCRIBER",
    "WHISPER_MODEL",
    "WHISPER_DEVICE",
    "WHISPER_LANGUAGE",
    "OPENAI_API_KEY",
    "DECISION_ENGINE",
    "TYPESAFE_API_KEY",
    "JEV_MODEL",
    "JEV_MIN_CONFIDENCE",
    "SILENCE_PADDING_MS",
    "AUDIO_CROSSFADE_MS",
    "TARGET_LUFS",
    "PUNCH_IN_SCALE",
    "FFMPEG_PATH",
    "FFPROBE_PATH",
)


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    data_dir = tmp_path / "autocut-data"
    monkeypatch.setenv(ENV_DATA_DIR, str(data_dir))
    for name in ENV_SETTING_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(settings_store, "default_secret_store", settings_store.InMemorySecretStore)
    monkeypatch.setattr(settings_store, "default_env_settings", lambda: Settings(_env_file=None))
    yield data_dir
