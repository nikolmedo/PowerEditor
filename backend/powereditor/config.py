import sys
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

Transcriber = Literal["local", "openai"]
WhisperDevice = Literal["auto", "cuda", "cpu"]
DecisionEngine = Literal["heuristic", "jev"]


def env_files() -> tuple[Path, ...]:
    """The `.env` files a source run reads; a frozen build reads none (env variables only)."""
    if getattr(sys, "frozen", False):
        return ()
    return (REPO_ROOT / ".env", Path(".env"))


class Settings(BaseSettings):
    """Developer overrides read from `.env` (source runs only) and environment variables.

    Every field defaults to None: only explicitly set values override the code
    defaults in `settings_store.UserSettings`, and the user settings file wins
    over this layer.
    """

    model_config = SettingsConfigDict(
        env_file=env_files(),
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    transcriber: Transcriber | None = None
    whisper_model: str | None = None
    whisper_device: WhisperDevice | None = None
    whisper_language: str | None = None
    openai_api_key: SecretStr | None = None

    decision_engine: DecisionEngine | None = None
    typesafe_api_key: SecretStr | None = None
    jev_model: str | None = None
    jev_min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    """Legacy name of `model_min_confidence`; the new name wins when both are set."""
    model_min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    silence_padding_ms: int | None = Field(default=None, ge=0)
    audio_crossfade_ms: int | None = Field(default=None, ge=0)
    target_lufs: float | None = None
    punch_in_scale: float | None = Field(default=None, gt=0.0)

    ffmpeg_path: str | None = None
    ffprobe_path: str | None = None
