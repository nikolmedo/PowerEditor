import re
from pathlib import Path
from typing import Any

import pytest

from tests.api_client import make_client, stored_project
from tests.media import ffmpeg_lavfi, needs_ffmpeg

pytestmark = [pytest.mark.ffmpeg, needs_ffmpeg]


def _upload(tmp_path: Path, name: str, content: bytes) -> tuple[int, dict[str, Any], Path]:
    data = tmp_path / "data"
    layout = stored_project(data)
    client = make_client(data)
    response = client.post(
        f"/api/projects/{layout.project_id}/music",
        files={"file": (name, content, "application/octet-stream")},
    )
    return response.status_code, response.json(), layout.media_dir


def test_music_upload_is_stored_in_media_and_probed(tmp_path: Path) -> None:
    song = ffmpeg_lavfi(tmp_path / "song.wav", "-f", "lavfi", "-i", "sine=frequency=220:duration=2")

    status, body, media_dir = _upload(tmp_path, "My Song.wav", song.read_bytes())

    assert status == 201
    file_name = str(body["fileName"])
    assert re.fullmatch(r"music-[0-9a-f]{8}\.wav", file_name)
    assert body["durationSeconds"] == pytest.approx(2.0, abs=0.05)
    assert body["url"].endswith(f"/media/{file_name}")
    assert (media_dir / file_name).read_bytes() == song.read_bytes()
    assert [p.name for p in media_dir.iterdir()] == [file_name]


def test_a_file_without_audio_is_rejected_and_not_kept(tmp_path: Path) -> None:
    silent_video = ffmpeg_lavfi(
        tmp_path / "video.mp4",
        "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=10:duration=1", "-pix_fmt", "yuv420p",
    )  # fmt: skip

    for name, content in (("video.m4a", silent_video.read_bytes()), ("fake.mp3", b"no audio")):
        status, body, media_dir = _upload(tmp_path / name, name, content)
        assert status == 422
        assert body["detail"]["code"] == "invalid_music"
        assert ".part" not in body["detail"]["message"]
        assert list(media_dir.iterdir()) == []
    status, body, _ = _upload(tmp_path / "again", "video.m4a", silent_video.read_bytes())
    assert body["detail"]["message"] == "The file has no audio stream."


def test_unsupported_music_types_are_refused(tmp_path: Path) -> None:
    status, body, _ = _upload(tmp_path, "tool.exe", b"MZ")
    assert status == 422
    assert body["detail"]["code"] == "unsupported_music_type"


def test_uploaded_music_is_served_with_an_audio_type(tmp_path: Path) -> None:
    data = tmp_path / "data"
    layout = stored_project(data)
    (layout.media_dir / "music-0011aabb.mp3").write_bytes(b"ID3")
    response = make_client(data).get(f"/api/projects/{layout.project_id}/media/music-0011aabb.mp3")
    assert response.headers["content-type"] == "audio/mpeg"
