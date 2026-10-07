"""Shared API state: project store, job manager and the replaceable pipeline entry points."""

import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Protocol, cast

from fastapi import Depends, HTTPException, Request

from powereditor.jobs import JobManager
from powereditor.pipeline.analyze import analyze_project
from powereditor.pipeline.runner import ProgressCallback, ProjectLayout
from powereditor.projects import ProjectMeta, ProjectNotFoundError, ProjectStore
from powereditor.render.job import render_project
from powereditor.render.quality import RenderQuality
from powereditor.settings_store import SettingsService
from powereditor.transcribe.local_whisper import ensure_model, is_model_cached

type AnalyzeRunner = Callable[
    [ProjectLayout, SettingsService, ProjectMeta, ProgressCallback], dict[str, Any]
]
type RenderRunner = Callable[
    [ProjectLayout, SettingsService, str, ProgressCallback, RenderQuality], dict[str, Any]
]
type Revealer = Callable[[Path], None]


class WhisperModels(Protocol):
    def is_downloaded(self, name: str, models_dir: Path) -> bool: ...

    def download(self, name: str, models_dir: Path) -> Path: ...


class FasterWhisperModels:
    def is_downloaded(self, name: str, models_dir: Path) -> bool:
        return is_model_cached(name, models_dir)

    def download(self, name: str, models_dir: Path) -> Path:
        return ensure_model(name, models_dir)


def run_analyze(
    layout: ProjectLayout, service: SettingsService, meta: ProjectMeta, progress: ProgressCallback
) -> dict[str, Any]:
    result = analyze_project(
        layout,
        service,
        files=[Path(path) for path in meta.source_paths],
        preset=meta.options.preset,
        language=meta.options.language,
        script=meta.options.script,
        progress=progress,
    )
    return {
        "clips": len(result.project.clips),
        "originalSeconds": result.original_seconds,
        "keptSeconds": result.kept_seconds,
    }


def run_render(
    layout: ProjectLayout,
    service: SettingsService,
    name: str,
    progress: ProgressCallback,
    quality: RenderQuality = "standard",
) -> dict[str, Any]:
    result = render_project(layout, service, name=name, progress=progress, quality=quality)
    return {
        "file": result.output.name,
        "videoSeconds": result.video_seconds,
        "wallSeconds": result.wall_s,
        "quality": result.quality,
        "concurrency": result.concurrency,
    }


def explorer_revealer(path: Path) -> None:
    # explorer.exe exits with 1 even when it opened the window, so the code is ignored.
    # It is the one launch that must show a window, so it skips `hidden_console_flags`.
    subprocess.Popen(["explorer", f"/select,{path}"])


def default_revealer() -> Revealer | None:
    return explorer_revealer if sys.platform == "win32" else None


@dataclass
class Pipelines:
    analyze: AnalyzeRunner = run_analyze
    render: RenderRunner = run_render
    whisper_models: WhisperModels = FasterWhisperModels()  # noqa: RUF009 (stateless)


def get_store(request: Request) -> ProjectStore:
    return cast(ProjectStore, request.app.state.project_store)


def get_jobs(request: Request) -> JobManager:
    return cast(JobManager, request.app.state.jobs)


def get_pipelines(request: Request) -> Pipelines:
    return cast(Pipelines, request.app.state.pipelines)


StoreDep = Annotated[ProjectStore, Depends(get_store)]
JobsDep = Annotated[JobManager, Depends(get_jobs)]
PipelinesDep = Annotated[Pipelines, Depends(get_pipelines)]


def http_error(status: int, exc: Exception, code: str | None = None) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail={"code": code or getattr(exc, "code", "error"), "message": str(exc)},
    )


def project_layout(store: ProjectStore, project_id: str) -> ProjectLayout:
    try:
        return store.layout(project_id)
    except ProjectNotFoundError as exc:
        raise http_error(404, exc) from exc
