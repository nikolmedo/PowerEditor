"""Background jobs (analyze, render, subtitle export) and their WebSocket event stream."""

import asyncio
from typing import cast

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from pydantic import Field

from powereditor.api.routes_settings import ServiceDep
from powereditor.api.services import (
    JobsDep,
    PipelinesDep,
    StoreDep,
    http_error,
    project_layout,
)
from powereditor.export.subtitle_files import SubtitleFormat, write_subtitles
from powereditor.export.subtitles import rebuild_subtitles
from powereditor.jobs import (
    TERMINAL_STATUSES,
    JobConflictError,
    JobEvent,
    JobInfo,
    JobKind,
    JobManager,
    JobNotFoundError,
    JobWork,
)
from powereditor.models import CamelModel, load_project, write_text_atomic
from powereditor.pipeline.runner import ProgressCallback
from powereditor.render.job import ProjectNotFoundError as RenderProjectNotFoundError

router = APIRouter(prefix="/api")

EXPORT_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._ -]*$"
WS_JOB_NOT_FOUND = 4404


class RenderRequest(CamelModel):
    export_name: str = Field(default="final", pattern=EXPORT_NAME_PATTERN, max_length=100)


class SubtitleExportRequest(CamelModel):
    format: SubtitleFormat = "srt"
    name: str = Field(default="subtitles", pattern=EXPORT_NAME_PATTERN, max_length=100)


def _submit(
    jobs: JobManager, kind: JobKind, key: str, project_id: str | None, work: JobWork
) -> JobInfo:
    try:
        return jobs.submit(kind, key, project_id, work)
    except JobConflictError as exc:
        raise http_error(409, exc) from exc


@router.post("/projects/{project_id}/analyze", status_code=status.HTTP_202_ACCEPTED)
def start_analyze(
    project_id: str, store: StoreDep, jobs: JobsDep, pipelines: PipelinesDep, service: ServiceDep
) -> JobInfo:
    layout = project_layout(store, project_id)
    meta = store.meta(project_id)

    def work(progress: ProgressCallback) -> dict[str, object]:
        return pipelines.analyze(layout, service, meta, progress)

    return _submit(jobs, "analyze", project_id, project_id, work)


@router.post("/projects/{project_id}/render", status_code=status.HTTP_202_ACCEPTED)
def start_render(
    project_id: str,
    store: StoreDep,
    jobs: JobsDep,
    pipelines: PipelinesDep,
    service: ServiceDep,
    body: RenderRequest | None = None,
) -> JobInfo:
    layout = project_layout(store, project_id)
    if not layout.project_file.is_file():
        raise http_error(409, RenderProjectNotFoundError("the project is not analyzed yet"))
    name = (body or RenderRequest()).export_name

    def work(progress: ProgressCallback) -> dict[str, object]:
        return pipelines.render(layout, service, name, progress)

    return _submit(jobs, "render", project_id, project_id, work)


@router.post("/projects/{project_id}/export/subtitles", status_code=status.HTTP_202_ACCEPTED)
def start_subtitle_export(
    project_id: str, body: SubtitleExportRequest, store: StoreDep, jobs: JobsDep
) -> JobInfo:
    layout = project_layout(store, project_id)
    if not layout.project_file.is_file():
        raise http_error(409, RenderProjectNotFoundError("the project is not analyzed yet"))

    def work(progress: ProgressCallback) -> dict[str, object]:
        progress("subtitles", 0.0, body.format)
        project = rebuild_subtitles(load_project(layout.project_file))
        target = layout.exports_dir / f"{body.name}.{body.format}"
        write_text_atomic(target, write_subtitles(project, body.format))
        return {"file": target.name}

    return _submit(jobs, "export_subtitles", project_id, project_id, work)


@router.get("/jobs/{job_id}")
def read_job(job_id: str, jobs: JobsDep) -> JobInfo:
    try:
        return jobs.get(job_id)
    except JobNotFoundError as exc:
        raise http_error(404, exc) from exc


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, jobs: JobsDep) -> JobInfo:
    try:
        return jobs.cancel(job_id)
    except JobNotFoundError as exc:
        raise http_error(404, exc) from exc


def _event_json(event: JobEvent) -> dict[str, object]:
    return event.model_dump(by_alias=True, mode="json")


@router.websocket("/jobs/{job_id}/events")
async def job_events(websocket: WebSocket, job_id: str) -> None:
    """Send the job's current state, then every change, ending with the terminal event."""
    jobs = cast(JobManager, websocket.app.state.jobs)
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[JobEvent] = asyncio.Queue()

    def forward(event: JobEvent) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, event)

    try:
        # Events arrive on worker threads; only the loop may touch the queue.
        snapshot, unsubscribe = jobs.subscribe(job_id, forward)
    except JobNotFoundError:
        # Accept first: a close before the handshake reaches browsers as a bare HTTP 403.
        await websocket.accept()
        await websocket.close(code=WS_JOB_NOT_FOUND)
        return
    await websocket.accept()
    try:
        event = snapshot
        while True:
            await websocket.send_json(_event_json(event))
            if event.status in TERMINAL_STATUSES:
                break
            event = await queue.get()
        await websocket.close()
    except WebSocketDisconnect:
        pass
    finally:
        unsubscribe()
