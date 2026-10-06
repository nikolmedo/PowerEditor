import subprocess
import sys
import threading
import time
from collections.abc import Iterator

import pytest

from powereditor.jobs import JobConflictError, JobEvent, JobManager, JobNotFoundError, JobWork
from powereditor.pipeline.ffmpeg import FfmpegError
from powereditor.pipeline.runner import ProgressCallback
from powereditor.process import tracked

TIMEOUT = 10


@pytest.fixture
def manager() -> Iterator[JobManager]:
    jobs = JobManager()
    yield jobs
    jobs.shutdown()


def _wait(manager: JobManager, job_id: str) -> str:
    done = threading.Event()
    status: list[str] = []

    def listener(event: JobEvent) -> None:
        if event.status in ("succeeded", "failed", "cancelled"):
            status.append(event.status)
            done.set()

    snapshot, unsubscribe = manager.subscribe(job_id, listener)
    if snapshot.status in ("succeeded", "failed", "cancelled"):
        return snapshot.status
    assert done.wait(TIMEOUT)
    unsubscribe()
    return status[0]


def _blocking(release: threading.Event) -> JobWork:
    def work(_: ProgressCallback) -> None:
        release.wait(TIMEOUT)

    return work


def test_job_reports_progress_and_result(manager: JobManager) -> None:
    events: list[JobEvent] = []
    release = threading.Event()

    def work(progress: ProgressCallback) -> dict[str, int]:
        release.wait(TIMEOUT)
        progress("ingest", 0.0, "running")
        progress("ingest", 0.004, "running")  # below the throttle step: not published
        progress("ingest", 0.5, "running")
        return {"clips": 3}

    info = manager.submit("analyze", "p1", "p1", work)
    manager.subscribe(info.id, events.append)
    release.set()

    assert _wait(manager, info.id) == "succeeded"
    job = manager.get(info.id)
    assert job.result == {"clips": 3}
    assert job.fraction == 1.0
    fractions = [(e.stage, e.fraction) for e in events if e.status == "running"]
    assert ("ingest", 0.004) not in fractions
    assert ("ingest", 0.5) in fractions


def test_one_active_job_per_key(manager: JobManager) -> None:
    release = threading.Event()
    first = manager.submit("analyze", "p1", "p1", _blocking(release))

    with pytest.raises(JobConflictError) as conflict:
        manager.submit("render", "p1", "p1", lambda _: None)
    other = manager.submit("render", "p2", "p2", lambda _: None)

    assert conflict.value.active_job_id == first.id
    assert _wait(manager, other.id) == "succeeded"
    release.set()
    assert _wait(manager, first.id) == "succeeded"
    assert manager.active_job("p1") is None


def test_failure_keeps_the_error_code(manager: JobManager) -> None:
    def work(_: ProgressCallback) -> None:
        raise FfmpegError("ffmpeg exited with code 1")

    info = manager.submit("render", "p1", "p1", work)

    assert _wait(manager, info.id) == "failed"
    error = manager.get(info.id).error
    assert error is not None
    assert (error.code, error.message) == ("ffmpeg_failed", "ffmpeg exited with code 1")


def test_value_errors_map_to_invalid_input(manager: JobManager) -> None:
    def work(_: ProgressCallback) -> None:
        raise ValueError("no sources")

    info = manager.submit("analyze", "p1", "p1", work)

    assert _wait(manager, info.id) == "failed"
    error = manager.get(info.id).error
    assert error is not None and error.code == "invalid_input"


def test_cancel_stops_at_the_next_progress_report(manager: JobManager) -> None:
    started, cancelled = threading.Event(), threading.Event()
    reached_end: list[bool] = []

    def work(progress: ProgressCallback) -> None:
        started.set()
        cancelled.wait(TIMEOUT)
        progress("transcribe", 0.5, "running")
        reached_end.append(True)

    info = manager.submit("analyze", "p1", "p1", work)
    assert started.wait(TIMEOUT)
    manager.cancel(info.id)
    cancelled.set()

    assert _wait(manager, info.id) == "cancelled"
    assert reached_end == []


def test_cancel_kills_the_running_subprocess(manager: JobManager) -> None:
    started = threading.Event()
    exit_codes: list[int] = []

    def work(_: ProgressCallback) -> None:
        with (
            subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"], text=True
            ) as process,
            tracked(process),
        ):
            started.set()
            exit_codes.append(process.wait(timeout=30))
        raise FfmpegError("ffmpeg exited because it was killed")

    info = manager.submit("render", "p1", "p1", work)
    assert started.wait(TIMEOUT)
    manager.cancel(info.id)

    assert _wait(manager, info.id) == "cancelled"
    assert exit_codes and exit_codes[0] != 0
    assert manager.get(info.id).error is None


def test_cancel_a_queued_job() -> None:
    manager = JobManager(max_workers=1)
    release = threading.Event()
    blocker = manager.submit("analyze", "p1", "p1", _blocking(release))
    ran: list[bool] = []
    queued = manager.submit("analyze", "p2", "p2", lambda _: ran.append(True))

    assert manager.cancel(queued.id).status == "cancelled"
    release.set()
    assert _wait(manager, blocker.id) == "succeeded"
    manager.shutdown()
    assert ran == []


def test_unknown_job(manager: JobManager) -> None:
    with pytest.raises(JobNotFoundError):
        manager.get("missing")


def test_shutdown_does_not_wait_forever_for_a_job_that_ignores_cancel() -> None:
    manager = JobManager()
    release = threading.Event()
    started = threading.Event()

    def stubborn(_: ProgressCallback) -> None:
        started.set()
        release.wait(TIMEOUT)  # never reports progress, so a cancel cannot stop it

    manager.submit("render", "p1", "p1", stubborn)
    assert started.wait(TIMEOUT)
    began = time.monotonic()
    manager.shutdown(timeout=0.2)
    elapsed = time.monotonic() - began
    release.set()

    assert elapsed < 2
