import subprocess
import threading
from collections.abc import Sequence
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from powereditor.api.app import create_app
from powereditor.api.services import Pipelines
from powereditor.settings_store import SettingsService
from tests.api_client import make_service, wait_for_job

TIMEOUT = 10


class FakeWhisperModels:
    def __init__(self, downloaded: bool = False) -> None:
        self.downloaded = downloaded
        self.release = threading.Event()
        self.release.set()
        self.requests: list[tuple[str, Path]] = []

    def is_downloaded(self, name: str, models_dir: Path) -> bool:
        return self.downloaded

    def download(self, name: str, models_dir: Path) -> Path:
        self.requests.append((name, models_dir))
        self.release.wait(TIMEOUT)
        self.downloaded = True
        return models_dir / name


def _all_tools_found(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(list(args), 0, stdout="tool 1.0\n", stderr="")


def _client(data: Path, models: FakeWhisperModels, transcriber: str = "local") -> TestClient:
    service = make_service(data)
    service.update({"transcriber": transcriber})
    app = create_app(
        settings_service=service,
        pipelines=Pipelines(whisper_models=models),
        doctor_runner=_all_tools_found,
    )
    return TestClient(app)


@pytest.fixture(autouse=True)
def tools_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(SettingsService, "locate_executable", lambda _, name: f"/bin/{name}")


def test_local_transcriber_needs_the_model(tmp_path: Path) -> None:
    status = _client(tmp_path, FakeWhisperModels()).get("/api/setup").json()

    assert status["transcriber"] == "local"
    assert status["whisperModel"] == "small"
    assert status["whisperModelDownloaded"] is False
    assert status["transcriberReady"] is False
    assert status["ready"] is False
    assert status["doctor"]["ok"] is True


def test_ready_once_the_model_is_downloaded(tmp_path: Path) -> None:
    status = _client(tmp_path, FakeWhisperModels(downloaded=True)).get("/api/setup").json()

    assert (status["transcriberReady"], status["ready"]) == (True, True)


def test_openai_transcriber_needs_the_key(tmp_path: Path) -> None:
    client = _client(tmp_path, FakeWhisperModels(), transcriber="openai")
    before = client.get("/api/setup").json()
    client.put("/api/secrets/openai_api_key", json={"value": "sk-test"})
    after = client.get("/api/setup").json()

    assert (before["openaiKeySet"], before["transcriberReady"]) == (False, False)
    assert (after["openaiKeySet"], after["transcriberReady"]) == (True, True)


def test_download_the_whisper_model_as_a_job(tmp_path: Path) -> None:
    models = FakeWhisperModels()
    models.release.clear()
    with _client(tmp_path, models) as client:
        job = client.post("/api/setup/whisper-model").json()
        second = client.post("/api/setup/whisper-model")
        status = client.get("/api/setup").json()
        models.release.set()
        done = wait_for_job(client, job["id"])
        after = client.get("/api/setup").json()

    assert second.status_code == 409
    assert status["whisperDownloadJobId"] == job["id"]
    assert done["status"] == "succeeded"
    assert done["result"] == {"model": "small"}
    assert models.requests == [("small", tmp_path / "models")]
    assert (after["whisperModelDownloaded"], after["whisperDownloadJobId"]) == (True, None)
