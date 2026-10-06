import re
import shutil
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, Header, Response, UploadFile, status
from pydantic import Field

from powereditor.api.services import JobsDep, StoreDep, http_error, project_layout
from powereditor.export.subtitles import edit_subtitle_text, rebuild_subtitles
from powereditor.models import CamelModel, Project, ProjectPreset
from powereditor.projects import (
    ProjectMeta,
    ProjectNotAnalyzedError,
    ProjectNotFoundError,
    ProjectOptions,
    ProjectStore,
    ProjectSummary,
    RevisionConflictError,
)

router = APIRouter(prefix="/api")

COPY_CHUNK_BYTES = 1024 * 1024
_UNSAFE_FILE_CHARS = re.compile(r"[^A-Za-z0-9._ -]")


class CreateFromPaths(ProjectOptions):
    paths: list[str] = Field(min_length=1)
    name: str | None = None


class CreatedProject(CamelModel):
    id: str


class ProjectListItem(ProjectSummary):
    thumbnail_url: str | None
    active_job_id: str | None


class SubtitleTextEdit(CamelModel):
    from_index: int = Field(ge=0)
    to_index: int = Field(gt=0)
    """Exclusive end in `subtitles.words`."""
    text: str


def media_url(project_id: str, file_name: str) -> str:
    return f"/api/projects/{project_id}/media/{file_name}"


def _read(store: ProjectStore, project_id: str) -> tuple[Project, str]:
    try:
        return store.read(project_id)
    except ProjectNotFoundError as exc:
        raise http_error(404, exc) from exc
    except ProjectNotAnalyzedError as exc:
        raise http_error(409, exc) from exc


def _save(store: ProjectStore, project_id: str, project: Project, etag: str) -> str:
    try:
        return store.save(project_id, project, etag)
    except RevisionConflictError as exc:
        raise http_error(409, exc) from exc


def _project_response(response: Response, project: Project, etag: str) -> Project:
    response.headers["ETag"] = etag
    return project


def _ensure_not_analyzing(jobs: JobsDep, project_id: str) -> None:
    active = jobs.active_job(project_id)
    if active is not None and active.kind == "analyze":
        raise http_error(
            409, RuntimeError("the project is being analyzed"), code="analysis_running"
        )


@router.post("/projects", status_code=status.HTTP_201_CREATED)
def create_project(body: CreateFromPaths, store: StoreDep) -> CreatedProject:
    paths = [Path(raw).expanduser() for raw in body.paths]
    for path in paths:
        if not path.is_file():
            raise http_error(422, FileNotFoundError(f"not a file: {path}"), code="source_not_found")
    options = ProjectOptions(preset=body.preset, language=body.language, script=body.script)
    meta = store.create(body.name or paths[0].stem, [p.resolve() for p in paths], options)
    return CreatedProject(id=meta.id)


def _safe_file_name(raw: str | None, taken: set[str]) -> str:
    name = _UNSAFE_FILE_CHARS.sub("_", Path((raw or "").replace("\\", "/")).name).lstrip(". ")
    name = name or "source"
    stem, suffix = Path(name).stem, Path(name).suffix
    candidate, counter = name, 1
    while candidate.lower() in taken:
        counter += 1
        candidate = f"{stem}-{counter}{suffix}"
    taken.add(candidate.lower())
    return candidate


@router.post("/projects/upload", status_code=status.HTTP_201_CREATED)
def upload_project(
    files: Annotated[list[UploadFile], File(min_length=1)],
    store: StoreDep,
    name: Annotated[str | None, Form()] = None,
    preset: Annotated[ProjectPreset | None, Form()] = None,
    language: Annotated[str | None, Form()] = None,
    script: Annotated[str | None, Form()] = None,
) -> CreatedProject:
    """Create a project from uploaded files, copied to `sources/` in chunks."""
    options = ProjectOptions(preset=preset, language=language, script=script)
    first_name = Path(files[0].filename or "project").stem
    meta = store.create(name or first_name, [], options)
    layout = store.layout(meta.id)
    try:
        layout.sources_dir.mkdir(parents=True)
        taken: set[str] = set()
        saved: list[Path] = []
        for upload in files:
            target = layout.sources_dir / _safe_file_name(upload.filename, taken)
            with target.open("wb") as handle:
                shutil.copyfileobj(upload.file, handle, COPY_CHUNK_BYTES)
            saved.append(target.resolve())
        store.set_sources(meta.id, saved)
    except BaseException:
        store.delete(meta.id)
        raise
    return CreatedProject(id=meta.id)


@router.get("/projects")
def list_projects(store: StoreDep, jobs: JobsDep) -> list[ProjectListItem]:
    items = []
    for summary in store.list():
        active = jobs.active_job(summary.id)
        items.append(
            ProjectListItem(
                **summary.model_dump(),
                thumbnail_url=media_url(summary.id, summary.proxy_file)
                if summary.proxy_file
                else None,
                active_job_id=active.id if active else None,
            )
        )
    return items


@router.get("/projects/{project_id}/meta")
def read_meta(project_id: str, store: StoreDep) -> ProjectMeta:
    project_layout(store, project_id)
    return store.meta(project_id)


@router.get("/projects/{project_id}")
def read_project(project_id: str, store: StoreDep, response: Response) -> Project:
    project, etag = _read(store, project_id)
    return _project_response(response, project, etag)


@router.put("/projects/{project_id}")
def save_project(
    project_id: str,
    project: Project,
    store: StoreDep,
    jobs: JobsDep,
    response: Response,
    if_match: Annotated[str | None, Header()] = None,
) -> Project:
    """Save an edited project; `If-Match` must carry the ETag it was loaded with."""
    _read(store, project_id)
    if if_match is None:
        raise http_error(428, ValueError("send the project's ETag in If-Match"), "etag_required")
    _ensure_not_analyzing(jobs, project_id)
    etag = _save(store, project_id, project, if_match)
    return _project_response(response, project, etag)


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: str, store: StoreDep, jobs: JobsDep) -> None:
    project_layout(store, project_id)
    active = jobs.active_job(project_id)
    if active is not None:
        raise http_error(409, RuntimeError(f"job {active.id} is still running"), "job_active")
    store.delete(project_id)


@router.post("/projects/{project_id}/subtitles/rebuild")
def rebuild_project_subtitles(
    project_id: str, store: StoreDep, jobs: JobsDep, response: Response
) -> Project:
    """Recompute the timeline words from the clips, as after any clip edit."""
    project, etag = _read(store, project_id)
    _ensure_not_analyzing(jobs, project_id)
    rebuilt = rebuild_subtitles(project)
    return _project_response(response, rebuilt, _save(store, project_id, rebuilt, etag))


@router.put("/projects/{project_id}/subtitles/text")
def edit_project_subtitle_text(
    project_id: str, body: SubtitleTextEdit, store: StoreDep, jobs: JobsDep, response: Response
) -> Project:
    """Replace the text of `subtitles.words[fromIndex:toIndex]`, keeping the timing."""
    project, etag = _read(store, project_id)
    _ensure_not_analyzing(jobs, project_id)
    line = project.subtitles.words[body.from_index : body.to_index]
    try:
        if not line:
            raise ValueError("the word range is empty")
        edited = edit_subtitle_text(project, line, body.text)
    except ValueError as exc:
        raise http_error(422, exc, code="invalid_subtitle_edit") from exc
    return _project_response(response, edited, _save(store, project_id, edited, etag))
