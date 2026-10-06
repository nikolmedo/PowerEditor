from pathlib import Path

from powereditor.models import load_project
from tests.api_client import fixture_project, make_client, stored_project


def _source(tmp_path: Path, name: str = "take.mp4") -> Path:
    path = tmp_path / "footage" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not really a video")
    return path


def test_create_from_local_paths_and_list(tmp_path: Path) -> None:
    client = make_client(tmp_path / "data")
    source = _source(tmp_path)

    created = client.post(
        "/api/projects",
        json={"paths": [str(source)], "preset": "reel_9x16", "language": "en", "script": "Hi."},
    )
    listed = client.get("/api/projects").json()

    assert created.status_code == 201
    project_id = created.json()["id"]
    assert [(p["id"], p["name"], p["status"]) for p in listed] == [(project_id, "take", "created")]
    meta = client.get(f"/api/projects/{project_id}/meta").json()
    assert meta["sourcePaths"] == [str(source)]
    assert meta["options"] == {"preset": "reel_9x16", "language": "en", "script": "Hi."}


def test_create_rejects_missing_paths_and_directories(tmp_path: Path) -> None:
    client = make_client(tmp_path / "data")

    missing = client.post("/api/projects", json={"paths": [str(tmp_path / "nope.mp4")]})
    directory = client.post("/api/projects", json={"paths": [str(tmp_path)]})
    empty = client.post("/api/projects", json={"paths": []})

    assert missing.status_code == 422
    assert missing.json()["detail"]["code"] == "source_not_found"
    assert directory.status_code == 422
    assert empty.status_code == 422
    assert client.get("/api/projects").json() == []


def test_upload_streams_files_into_sources(tmp_path: Path) -> None:
    client = make_client(tmp_path / "data")
    content = bytes(range(256)) * 8192  # 2 MiB, larger than the in-memory spool

    created = client.post(
        "/api/projects/upload",
        files=[
            ("files", ("clip one.mp4", content, "video/mp4")),
            ("files", ("../escape.mp4", b"x", "video/mp4")),
        ],
        data={"preset": "landscape_16x9", "name": "Upload"},
    )

    assert created.status_code == 201
    project_id = created.json()["id"]
    sources = tmp_path / "data" / "projects" / project_id / "sources"
    assert sorted(path.name for path in sources.iterdir()) == ["clip one.mp4", "escape.mp4"]
    assert (sources / "clip one.mp4").read_bytes() == content
    meta = client.get(f"/api/projects/{project_id}/meta").json()
    assert meta["name"] == "Upload"
    assert meta["options"]["preset"] == "landscape_16x9"
    assert [Path(p).name for p in meta["sourcePaths"]] == ["clip one.mp4", "escape.mp4"]


def test_get_project_with_etag_and_not_analyzed(tmp_path: Path) -> None:
    data = tmp_path / "data"
    client = make_client(data)
    analyzed = stored_project(data)
    pending = stored_project(data, analyzed=False)

    response = client.get(f"/api/projects/{analyzed.project_id}")

    assert response.status_code == 200
    assert response.json()["subtitles"]["sourceWords"]
    assert response.headers["etag"].startswith('"')
    assert client.get(f"/api/projects/{pending.project_id}").status_code == 409
    assert client.get("/api/projects/p-unknown").status_code == 404
    assert client.get("/api/projects/..").status_code == 404


def test_put_saves_with_matching_etag_and_rejects_stale(tmp_path: Path) -> None:
    data = tmp_path / "data"
    client = make_client(data)
    layout = stored_project(data)
    url = f"/api/projects/{layout.project_id}"
    etag = client.get(url).headers["etag"]
    edited = fixture_project().model_copy(update={"preset": "landscape_16x9"})
    body = edited.model_dump(by_alias=True, mode="json")

    saved = client.put(url, json=body, headers={"If-Match": etag})
    stale = client.put(url, json=body, headers={"If-Match": etag})
    unconditional = client.put(url, json=body)
    invalid = client.put(url, json={**body, "fps": 0}, headers={"If-Match": saved.headers["etag"]})

    assert saved.status_code == 200
    assert saved.headers["etag"] != etag
    assert load_project(layout.project_file).preset == "landscape_16x9"
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "revision_conflict"
    assert unconditional.status_code == 428
    assert invalid.status_code == 422


def test_delete_project(tmp_path: Path) -> None:
    data = tmp_path / "data"
    client = make_client(data)
    layout = stored_project(data)

    assert client.delete(f"/api/projects/{layout.project_id}").status_code == 204
    assert not layout.root.exists()
    assert client.delete(f"/api/projects/{layout.project_id}").status_code == 404


def test_rebuild_subtitles_after_a_clip_edit(tmp_path: Path) -> None:
    data = tmp_path / "data"
    client = make_client(data)
    layout = stored_project(data)
    project = fixture_project()
    first = project.clips[0]
    slowed = project.model_copy(
        update={"clips": [first.model_copy(update={"speed": 0.5}), *project.clips[1:]]}
    )
    url = f"/api/projects/{layout.project_id}"
    etag = client.get(url).headers["etag"]
    client.put(url, json=slowed.model_dump(by_alias=True, mode="json"), headers={"If-Match": etag})
    before = load_project(layout.project_file).subtitles.words

    rebuilt = client.post(f"{url}/subtitles/rebuild")

    assert rebuilt.status_code == 200
    after = rebuilt.json()["subtitles"]["words"]
    first_clip_words = [w for w in after if w["clipId"] == first.id]
    assert first_clip_words
    assert [w["endFrame"] for w in after] != [w.end_frame for w in before]
    assert rebuilt.headers["etag"] == client.get(url).headers["etag"]


def test_edit_subtitle_text(tmp_path: Path) -> None:
    data = tmp_path / "data"
    client = make_client(data)
    layout = stored_project(data)
    url = f"/api/projects/{layout.project_id}/subtitles/text"

    edited = client.put(url, json={"fromIndex": 0, "toIndex": 2, "text": "Hello there"})
    bad = client.put(url, json={"fromIndex": 3, "toIndex": 3, "text": "x"})

    assert edited.status_code == 200
    words = edited.json()["subtitles"]["words"]
    assert [w["text"] for w in words[:2]] == ["Hello", "there"]
    assert load_project(layout.project_file).subtitles.words[0].text == "Hello"
    assert bad.status_code == 422
