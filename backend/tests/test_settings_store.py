import json
import threading
import time
from pathlib import Path

import keyring.errors
import pytest
from pydantic import ValidationError

from powereditor.config import Settings
from powereditor.paths import AppPaths, resolve_executable
from powereditor.settings_store import InMemorySecretStore, SettingsService


def _service(
    data_dir: Path,
    env: Settings | None = None,
    secrets: InMemorySecretStore | None = None,
    cuda: bool = False,
) -> SettingsService:
    return SettingsService(
        paths=AppPaths(data_dir=data_dir),
        secrets=secrets or InMemorySecretStore(),
        env=env or Settings(_env_file=None),
        cuda_available=lambda: cuda,
    )


def test_app_paths_honours_env_override(isolated_environment: Path) -> None:
    paths = AppPaths.from_env()

    assert paths.data_dir == isolated_environment
    assert paths.settings_file == isolated_environment / "settings.json"
    assert not isolated_environment.exists()
    paths.ensure_dirs()
    assert sorted(p.name for p in isolated_environment.iterdir()) == [
        "bin",
        "logs",
        "models",
        "projects",
    ]


def test_code_defaults_apply_without_env_or_file(tmp_path: Path) -> None:
    effective = _service(tmp_path).get_effective()

    assert effective.transcriber == "local"
    assert effective.whisper_model is None
    assert effective.language == "es"
    assert effective.ui_language == "es"
    assert effective.target_lufs == -14.0


def test_env_overrides_defaults_and_file_overrides_env(tmp_path: Path) -> None:
    env = Settings(_env_file=None, transcriber="openai", whisper_language="en", target_lufs=-16.0)
    service = _service(tmp_path, env=env)

    assert service.get_effective().transcriber == "openai"
    assert service.get_effective().language == "en"

    service.update({"transcriber": "local"})

    effective = service.get_effective()
    assert effective.transcriber == "local"
    assert effective.language == "en"
    assert effective.target_lufs == -16.0


def test_update_persists_only_overrides_atomically(tmp_path: Path) -> None:
    service = _service(tmp_path)

    service.update({"silencePaddingMs": 200, "whisper_device": "cpu"})

    stored = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert stored == {"silencePaddingMs": 200, "whisperDevice": "cpu"}
    assert _service(tmp_path).get_effective().silence_padding_ms == 200
    assert [p.name for p in tmp_path.iterdir()] == ["settings.json"]


def test_update_rejects_invalid_values_without_persisting(tmp_path: Path) -> None:
    service = _service(tmp_path)

    with pytest.raises(ValidationError):
        service.update({"jevMinConfidence": 1.5})
    with pytest.raises(ValidationError):
        service.update({"notASetting": 1})

    assert not (tmp_path / "settings.json").exists()


def test_explicit_null_resets_whisper_model_to_auto(tmp_path: Path) -> None:
    env = Settings(_env_file=None, whisper_model="medium")
    service = _service(tmp_path, env=env)
    assert service.get_effective().whisper_model == "medium"

    service.update({"whisperModel": None})

    assert service.get_effective().whisper_model is None


@pytest.mark.parametrize(("cuda", "expected"), [(True, "large-v3-turbo"), (False, "small")])
def test_whisper_model_auto_depends_on_cuda(tmp_path: Path, cuda: bool, expected: str) -> None:
    assert _service(tmp_path, cuda=cuda).resolved_whisper_model() == expected


def test_configured_whisper_model_wins_over_runtime_default(tmp_path: Path) -> None:
    service = _service(tmp_path, cuda=False)
    service.update({"whisperModel": "medium"})

    assert service.resolved_whisper_model() == "medium"


def test_secrets_live_in_store_not_in_settings_file(tmp_path: Path) -> None:
    store = InMemorySecretStore()
    service = _service(tmp_path, secrets=store)

    service.set_secret("openai_api_key", "  sk-test-123  ")
    service.update({"targetLufs": -12.0})

    assert store.get("openai_api_key") == "sk-test-123"
    assert service.has_secret("openai_api_key")
    assert not service.has_secret("typesafe_api_key")
    assert "sk-test" not in (tmp_path / "settings.json").read_text(encoding="utf-8")

    service.clear_secret("openai_api_key")
    assert not service.has_secret("openai_api_key")
    service.clear_secret("openai_api_key")


def test_empty_secret_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="empty"):
        _service(tmp_path).set_secret("openai_api_key", "   ")


def test_env_secret_overrides_store(tmp_path: Path) -> None:
    store = InMemorySecretStore()
    store.set("typesafe_api_key", "from-keyring")
    env = Settings(_env_file=None, typesafe_api_key="from-env")
    service = _service(tmp_path, env=env, secrets=store)

    assert service.get_secret("typesafe_api_key") == "from-env"
    assert service.secret_source("typesafe_api_key") == "env"
    service.clear_secret("typesafe_api_key")
    assert service.has_secret("typesafe_api_key")


def test_corrupt_settings_file_falls_back_to_defaults(tmp_path: Path) -> None:
    (tmp_path / "settings.json").write_text("{not json", encoding="utf-8")

    assert _service(tmp_path).get_effective().transcriber == "local"


def test_resolve_executable_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda cmd: f"/usr/bin/{cmd}")
    bin_dir = tmp_path / "bin"
    configured = tmp_path / "custom" / "ffmpeg.exe"

    assert resolve_executable("ffmpeg", None, bin_dir) == "/usr/bin/ffmpeg"

    bin_dir.mkdir()
    bundled = bin_dir / "ffmpeg.exe"
    bundled.write_bytes(b"")
    assert resolve_executable("ffmpeg", None, bin_dir) == str(bundled)

    configured.parent.mkdir()
    configured.write_bytes(b"")
    assert resolve_executable("ffmpeg", str(configured), bin_dir) == str(configured)
    assert resolve_executable("ffmpeg", str(tmp_path / "nope.exe"), bin_dir) == str(bundled)


def test_locate_executable_uses_configured_ffprobe(tmp_path: Path) -> None:
    probe = tmp_path / "tools" / "ffprobe.exe"
    probe.parent.mkdir()
    probe.write_bytes(b"")
    service = _service(tmp_path / "data")
    service.update({"ffprobePath": str(probe)})

    assert service.locate_executable("ffprobe") == str(probe)


def test_env_file_values_override_defaults_only_when_set(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("TRANSCRIBER=openai\nWHISPER_LANGUAGE=en\n", encoding="utf-8")
    service = _service(tmp_path / "data", env=Settings(_env_file=env_file))

    effective = service.get_effective()

    assert effective.transcriber == "openai"
    assert effective.language == "en"
    assert effective.whisper_model is None
    assert effective.silence_padding_ms == 120


class _BrokenSecretStore(InMemorySecretStore):
    def get(self, name: str) -> str | None:
        raise keyring.errors.KeyringError("vault locked")


def test_unavailable_keyring_reads_as_unset(tmp_path: Path) -> None:
    service = SettingsService(
        paths=AppPaths(data_dir=tmp_path),
        secrets=_BrokenSecretStore(),
        env=Settings(_env_file=None),
        cuda_available=lambda: False,
    )

    assert service.get_secret("openai_api_key") is None
    assert not service.has_secret("openai_api_key")


def test_update_keeps_valid_overrides_when_file_has_bad_keys(tmp_path: Path) -> None:
    (tmp_path / "settings.json").write_text(
        json.dumps({"silencePaddingMs": 300, "notASetting": 1, "jevMinConfidence": 7}),
        encoding="utf-8",
    )
    service = _service(tmp_path)

    assert service.get_effective().silence_padding_ms == 300

    service.update({"whisperDevice": "cpu"})

    stored = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert stored == {"silencePaddingMs": 300, "whisperDevice": "cpu"}


def test_concurrent_updates_do_not_lose_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(tmp_path)
    original = SettingsService._file_overrides

    def slow_read(self: SettingsService) -> dict[str, object]:
        data = original(self)
        time.sleep(0.05)
        return data

    monkeypatch.setattr(SettingsService, "_file_overrides", slow_read)
    threads = [
        threading.Thread(target=service.update, args=({"silencePaddingMs": 250},)),
        threading.Thread(target=service.update, args=({"audioCrossfadeMs": 30},)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    stored = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert stored == {"audioCrossfadeMs": 30, "silencePaddingMs": 250}
