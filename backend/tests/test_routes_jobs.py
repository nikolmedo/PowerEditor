import threading
from pathlib import Path
from typing import Any

import pytest
from starlette.websockets import WebSocketDisconnect

from powereditor.api.services import Pipelines
from powereditor.pipeline.runner import ProgressCallback, ProjectLayout
from powereditor.projects import ProjectMeta
from powereditor.render.quality import RenderQuality
from powereditor.render.remotion_render import RenderTimeoutError
from powereditor.settings_store import SettingsService
from powereditor.transcribe.factory import TranscriberConfigError
from tests.api_client import LOCAL_WS_URL, make_client, stored_project, wait_for_job

TIMEOUT = 10


class GatedPipelines(Pipelines):
    """Analyze/render fakes that report progress and wait for the test to release them."""

    def __init__(self, error: Exception | None = None) -> None:
        super().__init__(analyze=self.fake_analyze, render=self.fake_render)
        self.started = threading.Event()
        self.release = threading.Event()
        self.error = error
        self.calls: list[tuple[Any, ...]] = []

    def _run(self, progress: ProgressCallback) -> None:
        progress("ingest", 0.0, "running")
        self.started.set()
        self.release.wait(TIMEOUT)
        progress("ingest", 0.5, "running")
        if self.error is not None:
            raise self.error

    def fake_analyze(
        self,
        layout: ProjectLayout,
        _: SettingsService,
        meta: ProjectMeta,
        progress: ProgressCallback,
    ) -> dict[str, Any]:
        self.calls.append(("analyze", meta.options.language))
        self._run(progress)
        return {"clips": 4}

    def fake_render(
        self,
        layout: ProjectLayout,
        _: SettingsService,
        name: str,
        progress: ProgressCallback,
        quality: RenderQuality,
    ) -> dict[str, Any]:
        self.calls.append(("render", name, quality))
        self._run(progress)
        return {"file": f"{name}.mp4"}


def test_analyze_streams_progress_until_done(tmp_path: Path) -> None:
    data = tmp_path / "data"
    pipelines = GatedPipelines()
    layout = stored_project(data, analyzed=False)
    with make_client(data, pipelines=pipelines) as client:
        started = client.post(f"/api/projects/{layout.project_id}/analyze")
        job_id = started.json()["id"]
        assert pipelines.started.wait(TIMEOUT)
        with client.websocket_connect(f"{LOCAL_WS_URL}/api/jobs/{job_id}/events") as socket:
            first = socket.receive_json()
            pipelines.release.set()
            events = [first]
            while events[-1]["status"] not in ("succeeded", "failed", "cancelled"):
                events.append(socket.receive_json())

        assert started.status_code == 202
        assert first == {
            "jobId": job_id, "status": "running", "stage": "ingest", "fraction": 0.0,
            "message": "running", "error": None, "result": None,
        }  # fmt: skip
        assert ("ingest", 0.5) in [(e["stage"], e["fraction"]) for e in events]
        assert events[-1]["status"] == "succeeded"
        assert events[-1]["result"] == {"clips": 4}
        assert client.get(f"/api/jobs/{job_id}").json()["status"] == "succeeded"


def test_second_job_on_a_project_conflicts(tmp_path: Path) -> None:
    data = tmp_path / "data"
    pipelines = GatedPipelines()
    layout = stored_project(data)
    base = f"/api/projects/{layout.project_id}"
    with make_client(data, pipelines=pipelines) as client:
        first = client.post(f"{base}/render", json={"exportName": "draft"}).json()
        assert pipelines.started.wait(TIMEOUT)

        conflict = client.post(f"{base}/analyze")
        delete = client.delete(base)
        listed = client.get("/api/projects").json()
        pipelines.release.set()
        done = wait_for_job(client, first["id"])

    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "job_active"
    assert delete.status_code == 409
    assert listed[0]["activeJobId"] == first["id"]
    assert done["result"] == {"file": "draft.mp4"}
    assert pipelines.calls == [("render", "draft", "standard")]


def test_saving_is_refused_while_analyzing(tmp_path: Path) -> None:
    data = tmp_path / "data"
    pipelines = GatedPipelines()
    layout = stored_project(data)
    url = f"/api/projects/{layout.project_id}"
    with make_client(data, pipelines=pipelines) as client:
        loaded = client.get(url)
        job = client.post(f"{url}/analyze").json()
        assert pipelines.started.wait(TIMEOUT)

        saved = client.put(url, json=loaded.json(), headers={"If-Match": loaded.headers["etag"]})
        pipelines.release.set()
        wait_for_job(client, job["id"])

    assert saved.status_code == 409
    assert saved.json()["detail"]["code"] == "analysis_running"


def test_job_errors_keep_their_codes(tmp_path: Path) -> None:
    data = tmp_path / "data"
    cases = [
        (TranscriberConfigError("missing_openai_key", "Set an OpenAI API key"), "analyze"),
        (RenderTimeoutError("Remotion render timed out after 60s"), "render"),
    ]
    for error, action in cases:
        pipelines = GatedPipelines(error=error)
        pipelines.release.set()
        layout = stored_project(data)
        with make_client(data, pipelines=pipelines) as client:
            job = client.post(f"/api/projects/{layout.project_id}/{action}").json()
            done = wait_for_job(client, job["id"])

        assert done["status"] == "failed"
        assert done["error"]["code"] == getattr(error, "code", None)
        assert done["error"]["message"] == str(error)


def test_cancel_a_running_job(tmp_path: Path) -> None:
    data = tmp_path / "data"
    pipelines = GatedPipelines()
    layout = stored_project(data)
    with make_client(data, pipelines=pipelines) as client:
        job = client.post(f"/api/projects/{layout.project_id}/render").json()
        assert pipelines.started.wait(TIMEOUT)

        client.post(f"/api/jobs/{job['id']}/cancel")
        pipelines.release.set()
        done = wait_for_job(client, job["id"])

        assert done["status"] == "cancelled"
        assert done["error"] is None
        assert client.post(f"/api/projects/{layout.project_id}/render").status_code == 202
        pipelines.release.set()


def test_render_needs_an_analyzed_project(tmp_path: Path) -> None:
    data = tmp_path / "data"
    layout = stored_project(data, analyzed=False)
    with make_client(data, pipelines=GatedPipelines()) as client:
        render = client.post(f"/api/projects/{layout.project_id}/render")
        bad_name = client.post(
            f"/api/projects/{stored_project(data).project_id}/render",
            json={"exportName": "../evil"},
        )

    assert render.status_code == 409
    assert bad_name.status_code == 422


def test_export_subtitles_job_writes_the_file(tmp_path: Path) -> None:
    data = tmp_path / "data"
    layout = stored_project(data)
    with make_client(data) as client:
        job = client.post(
            f"/api/projects/{layout.project_id}/export/subtitles", json={"format": "ass"}
        ).json()
        done = wait_for_job(client, job["id"])

    assert done["status"] == "succeeded"
    assert done["result"] == {"file": "subtitles.ass"}
    assert "[Events]" in (layout.exports_dir / "subtitles.ass").read_text(encoding="utf-8")


def test_unknown_jobs(tmp_path: Path) -> None:
    with make_client(tmp_path / "data") as client:
        assert client.get("/api/jobs/nope").status_code == 404
        assert client.post("/api/jobs/nope/cancel").status_code == 404
        assert client.post("/api/projects/p-none/analyze").status_code == 404


def test_events_of_an_unknown_job_close_with_4404(tmp_path: Path) -> None:
    with (
        make_client(tmp_path / "data") as client,
        pytest.raises(WebSocketDisconnect) as closed,
        client.websocket_connect(f"{LOCAL_WS_URL}/api/jobs/nope/events") as socket,
    ):
        socket.receive_json()

    assert closed.value.code == 4404


def test_analyze_start_waits_for_a_save_in_progress(tmp_path: Path) -> None:
    """A save checks "not analyzing" and writes under the project lock; an analyze that
    starts meanwhile must wait for it instead of slipping between the check and the write."""
    data = tmp_path / "data"
    pipelines = GatedPipelines()
    pipelines.release.set()
    layout = stored_project(data)
    with make_client(data, pipelines=pipelines) as client:
        store = client.app.state.project_store  # type: ignore[attr-defined]
        responses: list[int] = []
        with store.locked(layout.project_id):
            starter = threading.Thread(
                target=lambda: responses.append(
                    client.post(f"/api/projects/{layout.project_id}/analyze").status_code
                )
            )
            starter.start()
            starter.join(0.5)
            assert responses == []
            assert not pipelines.started.is_set()
        starter.join(TIMEOUT)

    assert responses == [202]


def test_project_list_reports_the_active_job_kind_and_last_error(tmp_path: Path) -> None:
    data = tmp_path / "data"
    failing = GatedPipelines(error=RenderTimeoutError("render timed out"))
    failing.release.set()
    layout = stored_project(data)
    with make_client(data, pipelines=failing) as client:
        job = client.post(f"/api/projects/{layout.project_id}/render").json()
        wait_for_job(client, job["id"])
        failed = client.get("/api/projects").json()[0]

    gated = GatedPipelines()
    with make_client(data, pipelines=gated) as client:
        job = client.post(f"/api/projects/{layout.project_id}/analyze").json()
        assert gated.started.wait(TIMEOUT)
        running = client.get("/api/projects").json()[0]
        gated.release.set()
        wait_for_job(client, job["id"])
        finished = client.get("/api/projects").json()[0]

    assert failed["activeJobKind"] is None
    assert failed["lastError"] == {"code": "render_timeout", "message": "render timed out"}
    assert (running["activeJobId"], running["activeJobKind"]) == (job["id"], "analyze")
    assert finished["lastError"] is None


def test_render_takes_a_quality_preset_and_refuses_unknown_ones(tmp_path: Path) -> None:
    data = tmp_path / "data"
    pipelines = GatedPipelines()
    pipelines.release.set()
    layout = stored_project(data)
    base = f"/api/projects/{layout.project_id}"
    with make_client(data, pipelines=pipelines) as client:
        refused = client.post(f"{base}/render", json={"quality": "ultra"})
        job = client.post(f"{base}/render", json={"exportName": "quick", "quality": "draft"})
        assert job.status_code == 202
        assert wait_for_job(client, job.json()["id"])["status"] == "succeeded"

    assert refused.status_code == 422
    assert pipelines.calls == [("render", "quick", "draft")]
