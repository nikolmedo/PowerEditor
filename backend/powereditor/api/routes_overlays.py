"""Images for overlays (logos, pictures): uploaded into `media/` beside the project's media.

The Player loads them through the media route and the render through the loopback media
server, exactly like the clips. Only PNG, JPEG and WebP are accepted, and the file must
start with its format's signature: SVG is refused because it can carry scripts. Placing an
image on the timeline is an ordinary project edit (an overlay whose `props.src` is the
returned file name).
"""

import secrets
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, UploadFile, status

from powereditor.api.routes_projects import COPY_CHUNK_BYTES, media_url
from powereditor.api.services import StoreDep, http_error, project_layout
from powereditor.models import CamelModel

router = APIRouter(prefix="/api")

MAX_IMAGE_BYTES = 20 * 1024 * 1024
# Stored suffix per accepted suffix.
IMAGE_SUFFIXES = {".png": ".png", ".jpg": ".jpg", ".jpeg": ".jpg", ".webp": ".webp"}


class OverlayAsset(CamelModel):
    file_name: str
    """Name under the project's `media/` folder; goes into the overlay's `props.src`."""
    url: str


def has_image_signature(suffix: str, head: bytes) -> bool:
    """Whether `head` (the first bytes of a file) starts like a `suffix` image."""
    if suffix == ".png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if suffix == ".jpg":
        return head.startswith(b"\xff\xd8\xff")
    return head[:4] == b"RIFF" and head[8:12] == b"WEBP"


class ImageTooLargeError(ValueError):
    code = "image_too_large"


def _copy_capped(upload: UploadFile, target: Path) -> bytes:
    """Copy the upload to `target` in chunks; returns its first 12 bytes."""
    head = b""
    written = 0
    with target.open("wb") as handle:
        while chunk := upload.file.read(COPY_CHUNK_BYTES):
            written += len(chunk)
            if written > MAX_IMAGE_BYTES:
                limit = MAX_IMAGE_BYTES // (1024 * 1024)
                raise ImageTooLargeError(f"images are limited to {limit} MB")
            if len(head) < 12:
                head += chunk[: 12 - len(head)]
            handle.write(chunk)
    return head


@router.post("/projects/{project_id}/overlay-assets", status_code=status.HTTP_201_CREATED)
def upload_overlay_asset(
    project_id: str, file: Annotated[UploadFile, File()], store: StoreDep
) -> OverlayAsset:
    layout = project_layout(store, project_id)
    suffix = IMAGE_SUFFIXES.get(Path(file.filename or "").suffix.lower())
    if suffix is None:
        error = ValueError("Use a PNG, JPEG or WebP image.")
        raise http_error(422, error, "unsupported_image_type")
    layout.media_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"overlay-{secrets.token_hex(4)}{suffix}"
    partial = layout.media_dir / f".{file_name}.part"
    try:
        try:
            head = _copy_capped(file, partial)
        except ImageTooLargeError as exc:
            raise http_error(413, exc) from exc
        if not has_image_signature(suffix, head):
            error = ValueError(f"The file is not a {suffix.removeprefix('.').upper()} image.")
            raise http_error(422, error, "invalid_image")
        partial.replace(layout.media_dir / file_name)
    finally:
        partial.unlink(missing_ok=True)
    return OverlayAsset(file_name=file_name, url=media_url(project_id, file_name))
