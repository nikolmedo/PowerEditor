"""Helpers for API tests: an isolated app, a stored project and job waiting."""

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from powereditor.api.app import create_app
from powereditor.api.services import Pipelines, Revealer
from powereditor.config import Settings
from powereditor.export.subtitles import rebuild_subtitles
from powereditor.models import Project, save_project
from powereditor.paths import AppPaths
from powereditor.pipeline.runner import ProjectLayout
from powereditor.projects import ProjectOptions, ProjectStore
from powereditor.settings_store import InMemorySecretStore, SettingsService

SUBTITLES_FIXTURE = (
    Path(__file__).parents[2] / "packages" / "composition" / "test" / "fixtures" / "subtitles.json"
)


def fixture_project() -> Project:
    data: dict[str, Any] = json.loads(SUBTITLES_FIXTURE.read_text(encoding="utf-8"))
    return Project.model_validate(data["project"])


LOCAL_BASE_URL = "http://127.0.0.1:8765"
LOCAL_WS_URL = "ws://127.0.0.1:8765"
"""Tests talk to the app as the browser does: through the loopback host the server binds.
`websocket_connect` ignores the base URL, so WebSocket tests pass `LOCAL_WS_URL` paths."""


def local_client(app: FastAPI) -> TestClient:
    return TestClient(app, base_url=LOCAL_BASE_URL)


def make_service(data_dir: Path) -> SettingsService:
    return SettingsService(
        paths=AppPaths(data_dir=data_dir),
        secrets=InMemorySecretStore(),
        env=Settings(_env_file=None),
        cuda_available=lambda: False,
    )


def make_client(
    data_dir: Path,
    *,
    pipelines: Pipelines | None = None,
    revealer: Revealer | None = None,
    web_dir: Path | None = None,
) -> TestClient:
    app = create_app(
        settings_service=make_service(data_dir),
        pipelines=pipelines or Pipelines(),
        web_dir=web_dir or data_dir / "no-web-build",
    )
    app.state.revealer = revealer
    return local_client(app)


def stored_project(data_dir: Path, *, analyzed: bool = True) -> ProjectLayout:
    store = ProjectStore(AppPaths(data_dir=data_dir))
    meta = store.create("Demo", [], ProjectOptions())
    layout = store.layout(meta.id)
    layout.ensure()
    if analyzed:
        save_project(rebuild_subtitles(fixture_project()), layout.project_file)
    return layout


def wait_for_job(client: TestClient, job_id: str) -> dict[str, Any]:
    """Follow the job's event stream to its terminal event."""
    with client.websocket_connect(f"{LOCAL_WS_URL}/api/jobs/{job_id}/events") as socket:
        while True:
            event: dict[str, Any] = socket.receive_json()
            if event["status"] in ("succeeded", "failed", "cancelled"):
                return event
