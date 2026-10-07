import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from powereditor import app_version
from powereditor.api.app import create_app
from powereditor.updates import LATEST_RELEASE_URL, UpdateChecker, is_newer
from tests.api_client import local_client, make_service

RELEASES = "https://github.com/nikolmedo/PowerEditor/releases"


def release(tag: str = "v9.0.0") -> dict[str, Any]:
    version = tag.removeprefix("v")
    download = f"{RELEASES}/download/{tag}"
    return {
        "tag_name": tag,
        "html_url": f"{RELEASES}/tag/{tag}",
        "body": "## What's new",
        "draft": False,
        "assets": [
            {
                "name": f"PowerEditor-Setup-{version}-x64.exe",
                "browser_download_url": f"{download}/PowerEditor-Setup-{version}-x64.exe",
            },
            {
                "name": "SHA256SUMS.txt",
                "browser_download_url": f"{download}/SHA256SUMS.txt",
            },
        ],
    }


class FakeGitHub:
    def __init__(self, response: httpx.Response | Exception) -> None:
        self.response = response
        self.requests: list[httpx.Request] = []
        self.transport = httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def checker(tmp_path: Path, github: FakeGitHub, clock: Clock | None = None) -> UpdateChecker:
    return UpdateChecker(
        tmp_path / "update-check.json", transport=github.transport, now=clock or Clock()
    )


def test_a_newer_published_release_is_an_available_update(tmp_path: Path) -> None:
    github = FakeGitHub(httpx.Response(200, json=release("v9.0.0")))

    status = checker(tmp_path, github).status("0.1.0")

    assert status.model_dump(by_alias=True) == {
        "current": "0.1.0",
        "latest": "9.0.0",
        "updateAvailable": True,
        "releaseUrl": f"{RELEASES}/tag/v9.0.0",
        "installerUrl": f"{RELEASES}/download/v9.0.0/PowerEditor-Setup-9.0.0-x64.exe",
        "sha256Url": f"{RELEASES}/download/v9.0.0/SHA256SUMS.txt",
        "notes": "## What's new",
        "checkedAt": datetime(2026, 10, 6, 12, 0, tzinfo=UTC),
        "enabled": True,
        "error": None,
    }
    [sent] = github.requests
    assert str(sent.url) == LATEST_RELEASE_URL
    assert sent.headers["Accept"] == "application/vnd.github+json"
    assert sent.headers["User-Agent"] == "PowerEditor/0.1.0"


@pytest.mark.parametrize(
    ("latest", "current", "newer"),
    [("0.2.0", "0.1.0", True), ("0.1.0", "0.1.0", False), ("0.1.9", "0.1.10", False)],
)
def test_versions_compare_numerically(latest: str, current: str, newer: bool) -> None:
    assert is_newer(latest, current) is newer


def test_the_same_version_is_not_an_update(tmp_path: Path) -> None:
    github = FakeGitHub(httpx.Response(200, json=release("v0.1.0")))

    status = checker(tmp_path, github).status("0.1.0")

    assert (status.latest, status.update_available) == ("0.1.0", False)


def test_no_published_release_yet_is_not_an_error(tmp_path: Path) -> None:
    github = FakeGitHub(httpx.Response(404, json={"message": "Not Found"}))
    updates = checker(tmp_path, github)

    first = updates.status("0.1.0")
    second = updates.status("0.1.0")

    assert (first.latest, first.update_available, first.error) == (None, False, None)
    assert first.checked_at == datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
    assert second == first
    assert len(github.requests) == 1


def test_no_release_is_checked_again_after_fifteen_minutes(tmp_path: Path) -> None:
    # A private repository also answers 404, and becoming public must show up soon.
    github = FakeGitHub(httpx.Response(404, json={"message": "Not Found"}))
    clock = Clock()
    updates = checker(tmp_path, github, clock)

    updates.status("0.1.0")
    clock.now += timedelta(minutes=14)
    updates.status("0.1.0")
    github.response = httpx.Response(200, json=release("v0.2.0"))
    clock.now += timedelta(minutes=2)
    found = updates.status("0.1.0")

    assert len(github.requests) == 2
    assert (found.latest, found.update_available) == ("0.2.0", True)


def test_an_answer_is_reused_for_six_hours(tmp_path: Path) -> None:
    github = FakeGitHub(httpx.Response(200, json=release()))
    clock = Clock()
    updates = checker(tmp_path, github, clock)

    updates.status("0.1.0")
    clock.now += timedelta(hours=5, minutes=59)
    cached = updates.status("0.1.0")
    clock.now += timedelta(minutes=2)
    refreshed = updates.status("0.1.0")

    assert len(github.requests) == 2
    assert cached.checked_at == datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
    assert refreshed.checked_at == clock.now


def test_force_skips_the_cache(tmp_path: Path) -> None:
    github = FakeGitHub(httpx.Response(200, json=release()))
    clock = Clock()
    updates = checker(tmp_path, github, clock)

    updates.status("0.1.0")
    clock.now += timedelta(seconds=61)
    forced = updates.status("0.1.0", force=True)

    assert len(github.requests) == 2
    assert forced.checked_at == clock.now


def test_forced_checks_ask_github_at_most_once_a_minute(tmp_path: Path) -> None:
    github = FakeGitHub(httpx.Response(200, json=release()))
    clock = Clock()
    first = checker(tmp_path, github, clock).status("0.1.0", force=True)
    clock.now += timedelta(seconds=59)
    # A new checker per request, as in the route: the limit lives in the cache file.
    again = checker(tmp_path, github, clock).status("0.1.0", force=True)
    clock.now += timedelta(seconds=2)
    later = checker(tmp_path, github, clock).status("0.1.0", force=True)

    assert len(github.requests) == 2
    assert again == first
    assert later.checked_at == clock.now


def test_a_failed_forced_check_is_not_retried_within_a_minute(tmp_path: Path) -> None:
    clock = Clock()
    limited = FakeGitHub(httpx.Response(403, json={"message": "API rate limit exceeded"}))
    failed = checker(tmp_path, limited, clock).status("0.1.0", force=True)
    clock.now += timedelta(seconds=30)
    github = FakeGitHub(httpx.Response(200, json=release()))
    again = checker(tmp_path, github, clock).status("0.1.0", force=True)
    clock.now += timedelta(seconds=31)
    retried = checker(tmp_path, github, clock).status("0.1.0", force=True)

    assert failed.error == again.error == "update_check_failed"
    assert (retried.error, retried.update_available, len(github.requests)) == (None, True, 1)


def test_a_failed_forced_check_does_not_hide_a_fresh_answer(tmp_path: Path) -> None:
    clock = Clock()
    checker(tmp_path, FakeGitHub(httpx.Response(200, json=release())), clock).status("0.1.0")
    clock.now += timedelta(minutes=5)
    offline = FakeGitHub(httpx.ConnectError("offline"))
    checker(tmp_path, offline, clock).status("0.1.0", force=True)

    automatic = checker(tmp_path, offline, clock).status("0.1.0")

    assert (automatic.error, automatic.update_available, len(offline.requests)) == (None, True, 1)


@pytest.mark.parametrize(
    "answer",
    [
        httpx.ConnectError("offline"),
        httpx.ReadTimeout("slow"),
        httpx.Response(403, json={"message": "API rate limit exceeded"}),
        httpx.Response(200, json={"tag_name": "nightly", "html_url": RELEASES, "assets": []}),
        httpx.Response(200, text="<html>"),
    ],
)
def test_a_failed_check_reports_an_error_and_is_not_cached(
    tmp_path: Path, answer: httpx.Response | Exception
) -> None:
    failed = checker(tmp_path, FakeGitHub(answer)).status("0.1.0")
    github = FakeGitHub(httpx.Response(200, json=release()))
    retried = checker(tmp_path, github).status("0.1.0")

    assert (failed.update_available, failed.error, failed.latest) == (
        False,
        "update_check_failed",
        None,
    )
    assert (retried.update_available, len(github.requests)) == (True, 1)


def test_a_corrupt_cache_file_is_ignored(tmp_path: Path) -> None:
    (tmp_path / "update-check.json").write_text("{not json", encoding="utf-8")
    github = FakeGitHub(httpx.Response(200, json=release()))

    status = checker(tmp_path, github).status("0.1.0")

    assert (status.update_available, len(github.requests)) == (True, 1)
    assert json.loads((tmp_path / "update-check.json").read_text())["release"]["version"] == "9.0.0"


def _client(data_dir: Path, github: FakeGitHub, check: bool = True) -> Any:
    service = make_service(data_dir)
    service.update({"checkForUpdates": check})
    app = create_app(
        settings_service=service, web_dir=data_dir / "none", update_transport=github.transport
    )
    return local_client(app)


def test_the_route_reports_the_running_version(tmp_path: Path) -> None:
    github = FakeGitHub(httpx.Response(200, json=release()))

    body = _client(tmp_path, github).get("/api/updates").json()

    assert (body["current"], body["latest"], body["updateAvailable"]) == (
        app_version(),
        "9.0.0",
        True,
    )


def test_the_route_answers_offline_without_failing(tmp_path: Path) -> None:
    response = _client(tmp_path, FakeGitHub(httpx.ConnectError("offline"))).get("/api/updates")

    assert response.status_code == 200
    assert (response.json()["updateAvailable"], response.json()["error"]) == (
        False,
        "update_check_failed",
    )


def test_turning_checks_off_stops_automatic_checks_but_not_check_now(tmp_path: Path) -> None:
    github = FakeGitHub(httpx.Response(200, json=release()))
    client = _client(tmp_path, github, check=False)

    automatic = client.get("/api/updates").json()
    manual = client.get("/api/updates", params={"force": "true"}).json()

    assert (automatic["enabled"], automatic["updateAvailable"], automatic["latest"]) == (
        False,
        False,
        None,
    )
    assert (manual["enabled"], manual["updateAvailable"]) == (False, True)
    assert len(github.requests) == 1
