"""First-run checklist: external tools and whether a transcriber can run."""

from collections.abc import Sequence
from typing import cast

import httpx
from fastapi import APIRouter, Request, status

from powereditor import doctor
from powereditor.api.routes_settings import ServiceDep
from powereditor.api.services import JobsDep, PipelinesDep, http_error
from powereditor.jobs import JobConflictError, JobInfo
from powereditor.models import CamelModel, TranscriberProvider
from powereditor.pipeline.runner import ProgressCallback
from powereditor.resources import Resources
from powereditor.runtime.manager import (
    RuntimeManager,
    RuntimeStatus,
    UnknownRuntimeError,
    manager_for,
)
from powereditor.runtime.manifest import RuntimeDownload
from powereditor.settings_store import SettingsService

router = APIRouter(prefix="/api")

WHISPER_JOB_KEY = "setup:whisper-model"


def runtime_manager(request: Request, service: SettingsService) -> RuntimeManager:
    return manager_for(
        service,
        cast(Sequence[RuntimeDownload] | None, request.app.state.runtime_downloads),
        cast(httpx.BaseTransport | None, request.app.state.runtime_transport),
    )


class SetupStatus(CamelModel):
    doctor: doctor.DoctorReport
    transcriber: TranscriberProvider
    whisper_model: str
    whisper_model_downloaded: bool
    openai_key_set: bool
    transcriber_ready: bool
    """The configured transcriber can run: local model downloaded, or OpenAI key set."""
    ready: bool
    """Every required tool was found and the transcriber is ready."""
    whisper_download_job_id: str | None
    runtimes: list[RuntimeStatus]
    """Runtimes the app can download into its data dir (ffmpeg, Node, the render browser)."""


@router.get("/setup")
def setup_status(
    request: Request, service: ServiceDep, pipelines: PipelinesDep, jobs: JobsDep
) -> SetupStatus:
    runner = cast(doctor.Runner | None, request.app.state.doctor_runner)
    report = doctor.run_checks(
        runner=runner, locate=service.locate_executable, frozen=Resources.current().frozen
    )
    settings = service.get_effective()
    model = service.resolved_whisper_model()
    downloaded = pipelines.whisper_models.is_downloaded(model, service.paths.models_dir)
    key_set = service.get_secret("openai_api_key") is not None
    transcriber_ready = key_set if settings.transcriber == "openai" else downloaded
    active = jobs.active_job(WHISPER_JOB_KEY)
    return SetupStatus(
        doctor=report,
        transcriber=settings.transcriber,
        whisper_model=model,
        whisper_model_downloaded=downloaded,
        openai_key_set=key_set,
        transcriber_ready=transcriber_ready,
        ready=report.ok and transcriber_ready,
        whisper_download_job_id=active.id if active else None,
        runtimes=runtime_manager(request, service).statuses(),
    )


@router.post("/setup/whisper-model", status_code=status.HTTP_202_ACCEPTED)
def download_whisper_model(service: ServiceDep, pipelines: PipelinesDep, jobs: JobsDep) -> JobInfo:
    """Download the configured Whisper model in the background."""
    model = service.resolved_whisper_model()
    models_dir = service.paths.models_dir

    def work(progress: ProgressCallback) -> dict[str, object]:
        # The downloader reports no progress of its own, so only the start and end show.
        progress("download", 0.0, model)
        pipelines.whisper_models.download(model, models_dir)
        return {"model": model}

    try:
        return jobs.submit("whisper_model", WHISPER_JOB_KEY, None, work)
    except JobConflictError as exc:
        raise http_error(409, exc) from exc


@router.post("/setup/runtime/{name}", status_code=status.HTTP_202_ACCEPTED)
def install_runtime(name: str, request: Request, service: ServiceDep, jobs: JobsDep) -> JobInfo:
    """Download and install one runtime (`GET /api/setup` lists them) in the background."""
    manager = runtime_manager(request, service)
    if name not in manager.names():
        raise http_error(404, UnknownRuntimeError(f"unknown runtime {name!r}"))

    def work(progress: ProgressCallback) -> dict[str, object]:
        progress(name, 0.0, "download")
        installed = manager.install(name, lambda fraction: progress(name, fraction, "download"))
        return installed.model_dump(by_alias=True, mode="json")

    try:
        return jobs.submit("runtime", f"setup:runtime:{name}", None, work)
    except JobConflictError as exc:
        raise http_error(409, exc) from exc
