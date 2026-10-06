import json
import logging
import threading
from collections.abc import Callable, Mapping
from functools import cache
from pathlib import Path
from typing import Any, Literal, Protocol, get_args

import keyring
import keyring.errors
from pydantic import AliasChoices, Field, ValidationError, field_validator

from powereditor import doctor
from powereditor.config import DecisionEngine, Settings, Transcriber, WhisperDevice
from powereditor.models import CamelModel, write_text_atomic
from powereditor.paths import AppPaths
from powereditor.providers.config import (
    FeatureId,
    ModelRef,
    ProviderConfig,
    provider_secret_name,
)
from powereditor.resources import Resources, resolve_tool

logger = logging.getLogger(__name__)

KEYRING_SERVICE = "PowerEditor"
GPU_WHISPER_MODEL = "large-v3-turbo"
CPU_WHISPER_MODEL = "small"

SecretName = Literal["openai_api_key", "typesafe_api_key"]
SECRET_NAMES: tuple[SecretName, ...] = get_args(SecretName)
SecretSource = Literal["env", "keyring"]
TakeSimilarity = Literal["text", "embeddings"]

_ENV_FIELD_TO_SETTING = {
    "whisper_language": "language",
    "jev_min_confidence": "model_min_confidence",
}

_FILE_LOCKS: dict[str, threading.Lock] = {}
_FILE_LOCKS_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _FILE_LOCKS_GUARD:
        return _FILE_LOCKS.setdefault(key, threading.Lock())


class TakeWeights(CamelModel):
    """Weights of the heuristic take score; penalties are subtracted."""

    completeness: float = Field(default=4.0, ge=0.0)
    fillers: float = Field(default=0.5, ge=0.0)
    repetitions: float = Field(default=0.5, ge=0.0)
    cut_off: float = Field(default=2.0, ge=0.0)
    speech_rate: float = Field(default=0.5, ge=0.0)
    word_prob: float = Field(default=1.0, ge=0.0)
    clipping: float = Field(default=1.0, ge=0.0)
    face_centered: float = Field(default=0.5, ge=0.0)
    sharpness: float = Field(default=0.5, ge=0.0)
    last_take: float = Field(default=0.75, ge=0.0)
    fluency: float = Field(default=1.0, ge=0.0)
    """Model fluency score (0-1); only counts when a model answers `fluency_score`."""


class UserSettings(CamelModel):
    transcriber: Transcriber = "local"
    whisper_model: str | None = None
    whisper_device: WhisperDevice = "auto"
    language: str | None = "es"
    decision_engine: DecisionEngine = "heuristic"
    jev_model: str = "jev-1.13"
    model_min_confidence: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        validation_alias=AliasChoices(
            "modelMinConfidence", "model_min_confidence", "jevMinConfidence", "jev_min_confidence"
        ),
        serialization_alias="modelMinConfidence",
    )
    """A model answer is applied only at or above this confidence (formerly
    `jevMinConfidence`, still accepted and migrated on the next save)."""
    take_weights: TakeWeights = Field(default_factory=TakeWeights)
    take_similarity: TakeSimilarity = "text"
    silence_padding_ms: int = Field(default=120, ge=0)
    audio_crossfade_ms: int = Field(default=15, ge=0)
    target_lufs: float = -14.0
    punch_in_scale: float = Field(default=1.1, gt=0.0)
    auto_cta: bool = True
    render_max_concurrency: int = Field(default=0, ge=0, le=32)
    """Browser tabs per render; 0 picks them from the cores and free memory."""
    """Add a call-to-action graphic over segments that ask the viewer to act (`cta_detection`)."""
    ffmpeg_path: str | None = None
    ffprobe_path: str | None = None
    node_path: str | None = None
    ui_language: str = "es"
    providers: list[ProviderConfig] = Field(default_factory=list)
    feature_models: dict[FeatureId, ModelRef | None] = Field(default_factory=dict)
    """Unassigned features (missing or None) use the heuristic engine."""

    @field_validator("providers")
    @classmethod
    def _unique_provider_ids(cls, providers: list[ProviderConfig]) -> list[ProviderConfig]:
        ids = [provider.id for provider in providers]
        duplicates = sorted({provider_id for provider_id in ids if ids.count(provider_id) > 1})
        if duplicates:
            raise ValueError(f"duplicate provider id: {', '.join(duplicates)}")
        return providers


class SecretStore(Protocol):
    def get(self, name: str) -> str | None: ...

    def set(self, name: str, value: str) -> None: ...

    def delete(self, name: str) -> None: ...


class KeyringSecretStore:
    def __init__(self, service: str = KEYRING_SERVICE) -> None:
        self._service = service

    def get(self, name: str) -> str | None:
        return keyring.get_password(self._service, name)

    def set(self, name: str, value: str) -> None:
        keyring.set_password(self._service, name, value)

    def delete(self, name: str) -> None:
        try:
            keyring.delete_password(self._service, name)
        except keyring.errors.PasswordDeleteError:
            return


class InMemorySecretStore:
    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        return self._values.get(name)

    def set(self, name: str, value: str) -> None:
        self._values[name] = value

    def delete(self, name: str) -> None:
        self._values.pop(name, None)


def default_secret_store() -> SecretStore:
    return KeyringSecretStore()


def default_env_settings() -> Settings:
    return Settings()


class SettingsService:
    def __init__(
        self,
        paths: AppPaths,
        secrets: SecretStore,
        env: Settings,
        cuda_available: Callable[[], bool] = doctor.cuda_available,
    ) -> None:
        self.paths = paths
        self._secrets = secrets
        self._env = env
        self._cuda_available = cache(cuda_available)

    @classmethod
    def default(cls) -> "SettingsService":
        return cls(
            paths=AppPaths.from_env(),
            secrets=default_secret_store(),
            env=default_env_settings(),
        )

    def _env_overrides(self) -> dict[str, Any]:
        explicit = self._env.model_dump(
            include=set(self._env.model_fields_set),
            exclude={"openai_api_key", "typesafe_api_key"},
        )
        fields = UserSettings.model_fields
        return {
            fields[_ENV_FIELD_TO_SETTING.get(key, key)].alias or key: value
            for key, value in explicit.items()
        }

    def _file_overrides(self) -> dict[str, Any]:
        path = self.paths.settings_file
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Ignoring unreadable settings file %s: %s", path, exc)
            return {}
        if not isinstance(data, dict):
            logger.warning("Ignoring settings file %s: expected a JSON object", path)
            return {}
        return data

    def _merge(self, file_overrides: Mapping[str, Any]) -> UserSettings:
        return UserSettings.model_validate({**self._env_overrides(), **file_overrides})

    def get_effective(self) -> UserSettings:
        return self._merge(self._normalized_file_overrides())

    def update(self, partial: Mapping[str, Any]) -> UserSettings:
        return self.mutate(lambda _current: partial)

    def mutate(self, change: Callable[[UserSettings], Mapping[str, Any]]) -> UserSettings:
        """Read-modify-write under the settings lock: `change` receives the effective
        settings and returns the fields to store (by field name or alias)."""
        with _lock_for(self.paths.settings_file):
            stored = self._normalized_file_overrides()
            validated_partial = UserSettings.model_validate(change(self._merge(stored)))
            changes = validated_partial.model_dump(
                by_alias=True, mode="json", include=set(validated_partial.model_fields_set)
            )
            stored.update(changes)
            effective = self._merge(stored)
            write_text_atomic(
                self.paths.settings_file, json.dumps(stored, indent=2, sort_keys=True) + "\n"
            )
        return effective

    def cuda_available(self) -> bool:
        return self._cuda_available()

    def _normalized_file_overrides(self) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key, value in self._file_overrides().items():
            try:
                parsed = UserSettings.model_validate({key: value})
            except ValidationError:
                logger.warning("Ignoring invalid settings file entry %r", key)
                continue
            normalized.update(
                parsed.model_dump(by_alias=True, mode="json", include=set(parsed.model_fields_set))
            )
        return normalized

    def resolved_whisper_model(self) -> str:
        configured = self.get_effective().whisper_model
        if configured:
            return configured
        return GPU_WHISPER_MODEL if self._cuda_available() else CPU_WHISPER_MODEL

    def locate_executable(self, name: str) -> str | None:
        effective = self.get_effective()
        configured = {
            "ffmpeg": effective.ffmpeg_path,
            "ffprobe": effective.ffprobe_path,
            "node": effective.node_path,
        }
        return resolve_tool(
            name, configured.get(name), self.paths.bin_dir, Resources.current().runtime_dir
        )

    def _env_secret(self, name: SecretName) -> str | None:
        value = getattr(self._env, name)
        if value is None:
            return None
        secret: str = value.get_secret_value()
        return secret or None

    def _stored_secret(self, name: SecretName) -> str | None:
        try:
            return self._secrets.get(name)
        except keyring.errors.KeyringError as exc:
            logger.warning("Secure storage unavailable while reading %s: %s", name, exc)
            return None

    def get_secret(self, name: SecretName) -> str | None:
        return self._env_secret(name) or self._stored_secret(name)

    def secret_source(self, name: SecretName) -> SecretSource | None:
        if self._env_secret(name):
            return "env"
        if self._stored_secret(name):
            return "keyring"
        return None

    def has_secret(self, name: SecretName) -> bool:
        return self.secret_source(name) is not None

    def set_secret(self, name: SecretName, value: str) -> None:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("secret value must not be empty")
        self._secrets.set(name, cleaned)

    def clear_secret(self, name: SecretName) -> None:
        self._secrets.delete(name)

    def provider(self, provider_id: str) -> ProviderConfig | None:
        return next((p for p in self.get_effective().providers if p.id == provider_id), None)

    def feature_model(self, feature: FeatureId) -> tuple[ProviderConfig, str] | None:
        """The provider and model assigned to `feature`, or None for the heuristic."""
        ref = self.get_effective().feature_models.get(feature)
        if ref is None:
            return None
        provider = self.provider(ref.provider_id)
        return (provider, ref.model) if provider is not None else None

    def provider_api_key(self, provider_id: str) -> str | None:
        name = provider_secret_name(provider_id)
        try:
            return self._secrets.get(name)
        except keyring.errors.KeyringError as exc:
            logger.warning("Secure storage unavailable while reading %s: %s", name, exc)
            return None

    def set_provider_api_key(self, provider_id: str, value: str) -> None:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("secret value must not be empty")
        self._secrets.set(provider_secret_name(provider_id), cleaned)

    def clear_provider_api_key(self, provider_id: str) -> None:
        self._secrets.delete(provider_secret_name(provider_id))
