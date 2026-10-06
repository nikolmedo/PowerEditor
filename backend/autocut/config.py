from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

Transcriber = Literal["local", "openai"]
WhisperDevice = Literal["auto", "cuda", "cpu"]
DecisionEngine = Literal["heuristic", "jev"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", Path(".env")),
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    transcriber: Transcriber = "local"
    whisper_model: str = "large-v3-turbo"
    whisper_device: WhisperDevice = "auto"
    whisper_language: str | None = "es"
    openai_api_key: SecretStr | None = None

    decision_engine: DecisionEngine = "heuristic"
    typesafe_api_key: SecretStr | None = None
    jev_model: str = "jev-1.13"
    jev_min_confidence: float = Field(default=0.8, ge=0.0, le=1.0)

    silence_padding_ms: int = Field(default=120, ge=0)
    audio_crossfade_ms: int = Field(default=15, ge=0)
    target_lufs: float = -14.0
    punch_in_scale: float = Field(default=1.1, gt=0.0)
