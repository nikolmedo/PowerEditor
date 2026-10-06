"""Media and export files of a project, with HTTP Range support for browser playback."""

import mimetypes
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse

from powereditor.api.routes_projects import media_url
from powereditor.api.services import Revealer, StoreDep, http_error, project_layout
from powereditor.models import CamelModel

router = APIRouter(prefix="/api")

_SAFE_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]*$")
CONTENT_TYPES = {
    ".mp4": "video/mp4",
    ".wav": "audio/wav",
    ".srt": "application/x-subrip",
    ".ass": "text/x-ssa",
    ".json": "application/json",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".otio": "application/json",
    ".fcpxml": "application/xml",
}


class ExportFile(CamelModel):
    name: str
    size_bytes: int
    modified_at: datetime
    url: str


def content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in CONTENT_TYPES:
        return CONTENT_TYPES[suffix]
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _visible(name: str) -> bool:
    """Hidden temporaries (`.final.video.mp4`) and partial exports are never served."""
    return bool(_SAFE_FILE.fullmatch(name)) and ".part." not in name


def contained_file(folder: Path, name: str) -> Path | None:
    """`folder/name` if it is a visible file strictly inside `folder`, else None."""
    if not _visible(name):
        return None
    base = folder.resolve()
    candidate = (folder / name).resolve()
    if not candidate.is_relative_to(base) or candidate.parent != base or not candidate.is_file():
        return None
    return candidate


@router.api_route("/projects/{project_id}/media/{file_name}", methods=["GET", "HEAD"])
def serve_media(project_id: str, file_name: str, store: StoreDep) -> FileResponse:
    """Serve a file from the project's `media/` or `exports/` folder; honors `Range`."""
    layout = project_layout(store, project_id)
    for folder in (layout.media_dir, layout.exports_dir):
        path = contained_file(folder, file_name)
        if path is not None:
            return FileResponse(path, media_type=content_type(path))
    raise HTTPException(status_code=404, detail={"code": "file_not_found", "message": file_name})


@router.get("/projects/{project_id}/exports")
def list_exports(project_id: str, store: StoreDep) -> list[ExportFile]:
    layout = project_layout(store, project_id)
    if not layout.exports_dir.is_dir():
        return []
    files = []
    for path in sorted(layout.exports_dir.iterdir()):
        if path.is_file() and _visible(path.name):
            stat = path.stat()
            files.append(
                ExportFile(
                    name=path.name,
                    size_bytes=stat.st_size,
                    modified_at=datetime.fromtimestamp(stat.st_mtime, UTC),
                    url=media_url(project_id, path.name),
                )
            )
    return files


@router.post(
    "/projects/{project_id}/exports/{file_name}/reveal", status_code=status.HTTP_204_NO_CONTENT
)
def reveal_export(project_id: str, file_name: str, store: StoreDep, request: Request) -> None:
    """Open the exports folder in the file manager with the file selected (Windows only)."""
    layout = project_layout(store, project_id)
    path = contained_file(layout.exports_dir, file_name)
    if path is None:
        raise HTTPException(
            status_code=404, detail={"code": "file_not_found", "message": file_name}
        )
    revealer = cast(Revealer | None, request.app.state.revealer)
    if revealer is None:
        raise http_error(
            501, NotImplementedError("revealing files is only supported on Windows"), "unsupported"
        )
    revealer(path)
