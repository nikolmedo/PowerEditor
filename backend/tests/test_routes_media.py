from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.api_client import make_client, stored_project

CONTENT = bytes(range(256)) * 4  # 1024 bytes


@pytest.fixture
def media(tmp_path: Path) -> tuple[TestClient, str, Path]:
    data = tmp_path / "data"
    layout = stored_project(data)
    (layout.media_dir / "s1.proxy.mp4").write_bytes(CONTENT)
    layout.exports_dir.mkdir()
    (layout.exports_dir / "final.mp4").write_bytes(b"export")
    (layout.exports_dir / "subtitles.srt").write_bytes(b"1\n")
    (layout.exports_dir / ".final.video.mp4").write_bytes(b"temporary")
    (layout.exports_dir / "final.part.mp4").write_bytes(b"partial")
    (layout.root / "secret.txt").write_text("outside media", encoding="utf-8")
    url = f"/api/projects/{layout.project_id}/media"
    return make_client(data), url, layout.root


def test_full_file_advertises_ranges(media: tuple[TestClient, str, Path]) -> None:
    client, url, _ = media

    response = client.get(f"{url}/s1.proxy.mp4")

    assert response.status_code == 200
    assert response.content == CONTENT
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-type"] == "video/mp4"


@pytest.mark.parametrize(
    ("header", "start", "end"),
    [("bytes=0-99", 0, 99), ("bytes=1000-", 1000, 1023), ("bytes=-24", 1000, 1023)],
)
def test_range_requests(
    media: tuple[TestClient, str, Path], header: str, start: int, end: int
) -> None:
    client, url, _ = media

    response = client.get(f"{url}/s1.proxy.mp4", headers={"Range": header})

    assert response.status_code == 206
    assert response.content == CONTENT[start : end + 1]
    assert response.headers["content-range"] == f"bytes {start}-{end}/1024"


def test_unsatisfiable_range(media: tuple[TestClient, str, Path]) -> None:
    client, url, _ = media

    response = client.get(f"{url}/s1.proxy.mp4", headers={"Range": "bytes=5000-6000"})

    assert response.status_code == 416
    assert response.headers["content-range"] == "bytes */1024"


def test_head_reports_length_without_body(media: tuple[TestClient, str, Path]) -> None:
    client, url, _ = media

    response = client.head(f"{url}/s1.proxy.mp4")

    assert response.status_code == 200
    assert response.headers["content-length"] == "1024"
    assert response.content == b""


def test_exports_are_served_with_their_content_type(media: tuple[TestClient, str, Path]) -> None:
    client, url, _ = media

    srt = client.get(f"{url}/subtitles.srt")

    assert srt.status_code == 200
    assert srt.headers["content-type"].startswith("application/x-subrip")
    assert client.get(f"{url}/final.mp4").content == b"export"


@pytest.mark.parametrize(
    "name",
    ["..%2Fsecret.txt", "..%5Csecret.txt", "%2E%2E%2Fproject.json", ".final.video.mp4",
     "final.part.mp4", "missing.mp4", "%2E%2E", "C:%5CWindows%5Cwin.ini"],
)  # fmt: skip
def test_traversal_and_hidden_files_are_not_found(
    media: tuple[TestClient, str, Path], name: str
) -> None:
    client, url, _ = media

    assert client.get(f"{url}/{name}").status_code == 404


def test_unknown_project_media(tmp_path: Path) -> None:
    client = make_client(tmp_path / "data")

    assert client.get("/api/projects/p-none/media/a.mp4").status_code == 404


def test_list_exports_hides_temporaries(media: tuple[TestClient, str, Path]) -> None:
    client, url, root = media

    listed = client.get(f"/api/projects/{root.name}/exports").json()

    assert [(f["name"], f["sizeBytes"]) for f in listed] == [("final.mp4", 6), ("subtitles.srt", 2)]
    assert listed[0]["url"] == f"{url}/final.mp4"


def test_reveal_uses_the_injected_opener(tmp_path: Path) -> None:
    data = tmp_path / "data"
    layout = stored_project(data)
    layout.exports_dir.mkdir()
    (layout.exports_dir / "final.mp4").write_bytes(b"export")
    revealed: list[Path] = []
    client = make_client(data, revealer=revealed.append)
    base = f"/api/projects/{layout.project_id}/exports"

    ok = client.post(f"{base}/final.mp4/reveal")
    missing = client.post(f"{base}/other.mp4/reveal")

    assert ok.status_code == 204
    assert revealed == [(layout.exports_dir / "final.mp4").resolve()]
    assert missing.status_code == 404


def test_reveal_is_unsupported_without_an_opener(media: tuple[TestClient, str, Path]) -> None:
    client, _, root = media

    response = client.post(f"/api/projects/{root.name}/exports/final.mp4/reveal")

    assert response.status_code == 501
