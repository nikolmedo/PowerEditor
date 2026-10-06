import re
from pathlib import Path
from typing import Any

import pytest

from powereditor.api import routes_overlays
from tests.api_client import make_client, stored_project

# A 1x1 transparent PNG.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)
JPEG_HEAD = b"\xff\xd8\xff\xe0" + b"\x00" * 16
WEBP_HEAD = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 16


def _upload(tmp_path: Path, name: str, content: bytes) -> tuple[int, dict[str, Any], Path]:
    data = tmp_path / "data"
    layout = stored_project(data)
    client = make_client(data)
    response = client.post(
        f"/api/projects/{layout.project_id}/overlay-assets",
        files={"file": (name, content, "application/octet-stream")},
    )
    return response.status_code, response.json(), layout.media_dir


@pytest.mark.parametrize(
    ("name", "content", "suffix"),
    [
        ("Logo.PNG", PNG, ".png"),
        ("photo.jpeg", JPEG_HEAD, ".jpg"),
        ("pic.webp", WEBP_HEAD, ".webp"),
    ],
)
def test_overlay_images_are_stored_in_media(
    tmp_path: Path, name: str, content: bytes, suffix: str
) -> None:
    status, body, media_dir = _upload(tmp_path, name, content)

    assert status == 201
    file_name = str(body["fileName"])
    assert re.fullmatch(rf"overlay-[0-9a-f]{{8}}\{suffix}", file_name)
    assert body["url"].endswith(f"/media/{file_name}")
    assert [p.name for p in media_dir.iterdir()] == [file_name]
    assert (media_dir / file_name).read_bytes() == content


def test_files_that_are_not_the_image_they_claim_are_refused(tmp_path: Path) -> None:
    status, body, media_dir = _upload(tmp_path, "logo.png", b"<svg onload=alert(1)>")

    assert status == 422
    assert body["detail"]["code"] == "invalid_image"
    assert list(media_dir.iterdir()) == []


@pytest.mark.parametrize("name", ["logo.svg", "logo.gif", "logo"])
def test_unsupported_image_types_are_refused(tmp_path: Path, name: str) -> None:
    status, body, _ = _upload(tmp_path, name, PNG)

    assert status == 422
    assert body["detail"]["code"] == "unsupported_image_type"


def test_images_over_the_size_limit_are_refused_and_not_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(routes_overlays, "MAX_IMAGE_BYTES", 64)

    status, body, media_dir = _upload(tmp_path, "big.png", PNG + b"\x00" * 64)

    assert status == 413
    assert body["detail"]["code"] == "image_too_large"
    assert list(media_dir.iterdir()) == []


def test_unknown_projects_are_not_found(tmp_path: Path) -> None:
    client = make_client(tmp_path / "data")
    response = client.post(
        "/api/projects/p-missing/overlay-assets", files={"file": ("a.png", PNG, "image/png")}
    )
    assert response.status_code == 404
