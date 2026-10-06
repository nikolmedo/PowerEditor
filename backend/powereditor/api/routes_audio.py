"""Music files of a project: uploaded into `media/` so the preview and the render find them.

The upload only stores and probes the file. Adding it to the timeline is an ordinary
project edit (an `AudioTrack` of kind `music` naming the file), so it is undoable and
saved with the rest of the project.
"""

import secrets
import shutil
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, UploadFile, status

from powereditor.api.routes_projects import COPY_CHUNK_BYTES, media_url
from powereditor.api.routes_settings import ServiceDep
from powereditor.api.services import StoreDep, http_error, project_layout
from powereditor.models import CamelModel
from powereditor.pipeline.ffmpeg import FfmpegError, MediaTools, MissingToolError
from powereditor.pipeline.ingest import probe_audio_duration

router = APIRouter(prefix="/api")

MUSIC_SUFFIXES = frozenset({".mp3", ".wav", ".m4a", ".aac", ".ogg", ".opus", ".flac"})


class MusicFile(CamelModel):
    file_name: str
    """Name under the project's `media/` folder; goes into `AudioTrack.sourcePath`."""
    duration_seconds: float
    url: str


@router.post("/projects/{project_id}/music", status_code=status.HTTP_201_CREATED)
def upload_music(
    project_id: str,
    file: Annotated[UploadFile, File()],
    store: StoreDep,
    service: ServiceDep,
) -> MusicFile:
    layout = project_layout(store, project_id)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in MUSIC_SUFFIXES:
        raise http_error(
            422, ValueError(f"unsupported music file type: {suffix or 'none'}"),
            "unsupported_music_type",
        )  # fmt: skip
    try:
        tools = MediaTools.from_settings(service)
    except MissingToolError as exc:
        raise http_error(503, exc) from exc
    layout.media_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"music-{secrets.token_hex(4)}{suffix}"
    partial = layout.media_dir / f".{file_name}.part"
    try:
        with partial.open("wb") as handle:
            shutil.copyfileobj(file.file, handle, COPY_CHUNK_BYTES)
        try:
            duration = probe_audio_duration(tools.ffprobe, partial)
        except ValueError as exc:
            raise http_error(422, exc, "invalid_music") from exc
        except FfmpegError as exc:
            error = ValueError("The file is not a readable audio file.")
            raise http_error(422, error, "invalid_music") from exc
        partial.replace(layout.media_dir / file_name)
    finally:
        partial.unlink(missing_ok=True)
    return MusicFile(
        file_name=file_name, duration_seconds=duration, url=media_url(project_id, file_name)
    )
