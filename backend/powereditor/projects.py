"""Project folders on disk: creation, listing, metadata and guarded `project.json` writes."""

import hashlib
import secrets
import shutil
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from powereditor.models import (
    CamelModel,
    Project,
    ProjectPreset,
    parse_project,
    save_project,
    write_text_atomic,
)
from powereditor.paths import AppPaths
from powereditor.pipeline.ingest import load_manifest
from powereditor.pipeline.runner import ProjectLayout
from powereditor.timeline import timeline_layout

ProjectStatus = Literal["created", "ingested", "analyzed"]


class ProjectNotFoundError(LookupError):
    code = "project_not_found"


class ProjectNotAnalyzedError(LookupError):
    code = "project_not_analyzed"


class RevisionConflictError(RuntimeError):
    code = "revision_conflict"


class ProjectOptions(CamelModel):
    preset: ProjectPreset | None = None
    language: str | None = None
    script: str | None = None


class ProjectMeta(CamelModel):
    id: str
    name: str
    created_at: datetime
    source_paths: list[str]
    options: ProjectOptions


class ProjectSummary(CamelModel):
    id: str
    name: str
    created_at: datetime
    status: ProjectStatus
    proxy_file: str | None
    """File name of the first source's preview proxy under `media/`, when it exists."""
    duration_seconds: float | None
    """Edited timeline length once analyzed, the sources' total length before."""


def project_etag(content: bytes) -> str:
    return '"' + hashlib.sha256(content).hexdigest()[:20] + '"'


class ProjectStore:
    """All projects under `<data dir>/projects`. Writes to one project are serialized."""

    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self._locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()

    def _lock(self, project_id: str) -> threading.RLock:
        with self._locks_guard:
            return self._locks.setdefault(project_id, threading.RLock())

    @contextmanager
    def locked(self, project_id: str) -> Iterator[None]:
        """Hold the project's write lock so a check and the action it allows are atomic,
        for example "no analysis is running" and a save. Re-entrant within one thread."""
        with self._lock(project_id):
            yield

    def layout(self, project_id: str) -> ProjectLayout:
        """The layout of an existing project; unknown or malformed ids are not found."""
        try:
            layout = ProjectLayout.for_project(self.paths, project_id)
        except ValueError as exc:
            raise ProjectNotFoundError(f"project {project_id!r} does not exist") from exc
        if not layout.meta_file.is_file():
            raise ProjectNotFoundError(f"project {project_id!r} does not exist")
        return layout

    def create(
        self, name: str, source_paths: Sequence[Path], options: ProjectOptions
    ) -> ProjectMeta:
        project_id = datetime.now().strftime("p-%Y%m%d-%H%M%S-") + secrets.token_hex(3)
        layout = ProjectLayout.for_project(self.paths, project_id)
        layout.root.mkdir(parents=True, exist_ok=False)
        meta = ProjectMeta(
            id=project_id,
            name=name,
            created_at=datetime.now(UTC),
            source_paths=[str(path) for path in source_paths],
            options=options,
        )
        self._write_meta(layout, meta)
        return meta

    def set_sources(self, project_id: str, source_paths: Sequence[Path]) -> ProjectMeta:
        layout = self.layout(project_id)
        with self._lock(project_id):
            meta = self.meta(project_id).model_copy(
                update={"source_paths": [str(path) for path in source_paths]}
            )
            self._write_meta(layout, meta)
        return meta

    @staticmethod
    def _write_meta(layout: ProjectLayout, meta: ProjectMeta) -> None:
        write_text_atomic(layout.meta_file, meta.model_dump_json(by_alias=True, indent=2) + "\n")

    def meta(self, project_id: str) -> ProjectMeta:
        layout = self.layout(project_id)
        return ProjectMeta.model_validate_json(layout.meta_file.read_bytes())

    def list(self) -> list[ProjectSummary]:
        if not self.paths.projects_dir.is_dir():
            return []
        summaries = []
        for folder in self.paths.projects_dir.iterdir():
            try:
                summaries.append(self.summary(folder.name))
            except (ProjectNotFoundError, ValidationError, OSError):
                continue  # not a project created through the store, or unreadable
        return sorted(summaries, key=lambda summary: summary.created_at, reverse=True)

    def summary(self, project_id: str) -> ProjectSummary:
        meta = self.meta(project_id)
        layout = self.layout(project_id)
        sources = load_manifest(layout).sources
        proxies = [Path(s.proxy_path).name for s in sources if Path(s.proxy_path).is_file()]
        status: ProjectStatus = "created"
        duration: float | None = sum(s.probe.duration for s in sources) if sources else None
        if sources:
            status = "ingested"
        if layout.project_file.is_file():
            status = "analyzed"
            project, _ = self.read(project_id)
            duration = timeline_layout(project).duration_in_frames / project.fps
        return ProjectSummary(
            id=meta.id,
            name=meta.name,
            created_at=meta.created_at,
            status=status,
            proxy_file=proxies[0] if proxies else None,
            duration_seconds=duration,
        )

    def read(self, project_id: str) -> tuple[Project, str]:
        """The project and its ETag (a hash of the stored bytes)."""
        layout = self.layout(project_id)
        try:
            content = layout.project_file.read_bytes()
        except FileNotFoundError as exc:
            raise ProjectNotAnalyzedError(f"project {project_id!r} is not analyzed yet") from exc
        return parse_project(content), project_etag(content)

    def save(self, project_id: str, project: Project, if_match: str) -> str:
        """Write `project` only if the stored one still has the ETag `if_match`."""
        layout = self.layout(project_id)
        with self._lock(project_id):
            _, current = self.read(project_id)
            if if_match != current:
                raise RevisionConflictError("the project changed since it was loaded")
            save_project(project, layout.project_file)
            return project_etag(layout.project_file.read_bytes())

    def delete(self, project_id: str) -> None:
        layout = self.layout(project_id)
        with self._lock(project_id):
            shutil.rmtree(layout.root)
