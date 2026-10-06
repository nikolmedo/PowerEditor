"""Check GitHub Releases for a newer PowerEditor.

`releases/latest` returns the newest *published* release only (never a draft or a
prerelease), so a draft made by the release workflow stays invisible until a maintainer
publishes it. Answers are cached for six hours; a failed check is reported, not raised, and
not cached, so the next automatic check tries again. A forced check ("Check now") asks GitHub
at most once a minute and otherwise repeats the last outcome: unauthenticated GitHub API calls
are limited to 60 an hour per address.
"""

import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, ValidationError

from powereditor.models import CamelModel

LATEST_RELEASE_URL = "https://api.github.com/repos/nikolmedo/PowerEditor/releases/latest"
CACHE_FOR = timedelta(hours=6)
FORCED_CHECK_INTERVAL = timedelta(seconds=60)
TIMEOUT_SECONDS = 10.0
CACHE_FILE_NAME = "update-check.json"
INSTALLER_ASSET = re.compile(r"PowerEditor-Setup-.+-x64\.exe")
CHECKSUMS_ASSET = "SHA256SUMS.txt"
SEMVER = re.compile(r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")

UpdateError = Literal["update_check_failed"]


class _GitHubAsset(BaseModel):
    name: str
    browser_download_url: str


class _GitHubRelease(BaseModel):
    tag_name: str
    html_url: str
    body: str | None = None
    assets: list[_GitHubAsset] = []


class ReleaseInfo(CamelModel):
    version: str
    release_url: str
    installer_url: str | None
    sha256_url: str | None
    notes: str | None


class _CachedCheck(CamelModel):
    attempted_at: datetime | None = None
    """The last request to GitHub, answered or not."""
    checked_at: datetime | None = None
    """The last answered request; None when none succeeded yet."""
    release: ReleaseInfo | None = None
    """None while the repository has no published release (GitHub answers 404)."""

    @property
    def last_attempt_failed(self) -> bool:
        return self.checked_at is None or (
            self.attempted_at is not None and self.attempted_at > self.checked_at
        )


class UpdateStatus(CamelModel):
    current: str
    latest: str | None = None
    update_available: bool = False
    release_url: str | None = None
    installer_url: str | None = None
    sha256_url: str | None = None
    notes: str | None = None
    checked_at: datetime | None = None
    enabled: bool = True
    """False when the `checkForUpdates` setting is off."""
    error: UpdateError | None = None


class UpdateCheckFailed(Exception):
    pass


def parse_version(text: str) -> tuple[int, int, int] | None:
    match = SEMVER.fullmatch(text.strip())
    if match is None:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def is_newer(latest: str, current: str) -> bool:
    latest_parts, current_parts = parse_version(latest), parse_version(current)
    return latest_parts is not None and current_parts is not None and latest_parts > current_parts


def _release_info(release: _GitHubRelease) -> ReleaseInfo:
    version = parse_version(release.tag_name)
    if version is None:
        raise UpdateCheckFailed(f"tag {release.tag_name!r} is not a version")
    urls = {asset.name: asset.browser_download_url for asset in release.assets}
    installer = next((url for name, url in urls.items() if INSTALLER_ASSET.fullmatch(name)), None)
    return ReleaseInfo(
        version=".".join(str(part) for part in version),
        release_url=release.html_url,
        installer_url=installer,
        sha256_url=urls.get(CHECKSUMS_ASSET),
        notes=release.body,
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _within(moment: datetime | None, now: datetime, span: timedelta) -> bool:
    return moment is not None and timedelta(0) <= now - moment < span


def _status_from(current: str, cached: _CachedCheck) -> UpdateStatus:
    release = cached.release
    if release is None:
        return UpdateStatus(current=current, checked_at=cached.checked_at)
    return UpdateStatus(
        current=current,
        latest=release.version,
        update_available=is_newer(release.version, current),
        release_url=release.release_url,
        installer_url=release.installer_url,
        sha256_url=release.sha256_url,
        notes=release.notes,
        checked_at=cached.checked_at,
    )


class UpdateChecker:
    def __init__(
        self,
        cache_file: Path,
        transport: httpx.BaseTransport | None = None,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.cache_file = cache_file
        self.transport = transport
        self.now = now

    def status(self, current: str, force: bool = False) -> UpdateStatus:
        now = self.now()
        cached = self._load()
        if force:
            ask = not _within(cached.attempted_at, now, FORCED_CHECK_INTERVAL)
        else:
            ask = not _within(cached.checked_at, now, CACHE_FOR)
        if ask:
            cached.attempted_at = now
            try:
                cached = _CachedCheck(
                    attempted_at=now, checked_at=now, release=self._fetch(current)
                )
            except UpdateCheckFailed:
                self._store(cached)
                return UpdateStatus(current=current, error="update_check_failed")
            self._store(cached)
        elif force and cached.last_attempt_failed:
            return UpdateStatus(current=current, error="update_check_failed")
        return _status_from(current, cached)

    def _fetch(self, current: str) -> ReleaseInfo | None:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": f"PowerEditor/{current}",
        }
        try:
            with httpx.Client(transport=self.transport, timeout=TIMEOUT_SECONDS) as client:
                response = client.get(LATEST_RELEASE_URL, headers=headers)
                if response.status_code == 404:
                    return None
                response.raise_for_status()
                release = _GitHubRelease.model_validate_json(response.content)
        except (httpx.HTTPError, ValidationError) as exc:
            raise UpdateCheckFailed(str(exc)) from exc
        return _release_info(release)

    def _load(self) -> _CachedCheck:
        try:
            return _CachedCheck.model_validate_json(self.cache_file.read_bytes())
        except (OSError, ValidationError):
            return _CachedCheck()

    def _store(self, cached: _CachedCheck) -> None:
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.cache_file.write_text(cached.model_dump_json(by_alias=True), encoding="utf-8")
        except OSError:
            pass  # a read-only data dir only costs a fresh check next time
