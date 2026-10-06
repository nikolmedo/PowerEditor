"""In-process background jobs with progress events and cooperative cancellation.

A job runs on a worker thread. Its progress callback publishes events to listeners
(throttled to visible changes) and raises `JobCancelledError` once a cancel was
requested; the cancel also kills the job's tracked subprocess trees so long ffmpeg
or Remotion runs stop at once.
"""

import logging
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from powereditor.models import CamelModel
from powereditor.pipeline.runner import ProgressCallback
from powereditor.process import ProcessScope, process_scope

logger = logging.getLogger(__name__)

JobKind = Literal["analyze", "render", "export_subtitles", "whisper_model", "runtime"]
JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
TERMINAL_STATUSES: frozenset[JobStatus] = frozenset({"succeeded", "failed", "cancelled"})
MIN_FRACTION_STEP = 0.01
SHUTDOWN_TIMEOUT_S = 10.0

type JobResult = dict[str, Any] | None
type JobWork = Callable[[ProgressCallback], JobResult]
type JobListener = Callable[["JobEvent"], None]


class JobCancelledError(Exception):
    code = "cancelled"


class JobConflictError(RuntimeError):
    code = "job_active"

    def __init__(self, active_job_id: str) -> None:
        super().__init__(f"job {active_job_id} is still running")
        self.active_job_id = active_job_id


class JobNotFoundError(LookupError):
    code = "job_not_found"


class JobError(CamelModel):
    code: str
    message: str


class JobInfo(CamelModel):
    id: str
    kind: JobKind
    project_id: str | None
    status: JobStatus
    stage: str | None = None
    fraction: float = 0.0
    message: str = ""
    error: JobError | None = None
    result: dict[str, Any] | None = None
    created_at: datetime


class JobEvent(CamelModel):
    job_id: str
    status: JobStatus
    stage: str | None
    fraction: float
    message: str
    error: JobError | None = None
    result: dict[str, Any] | None = None


def error_code(exc: BaseException) -> str:
    code = getattr(exc, "code", None)
    if isinstance(code, str):
        return code
    return "invalid_input" if isinstance(exc, ValueError) else "internal_error"


@dataclass
class _Job:
    info: JobInfo
    key: str
    work: JobWork
    scope: ProcessScope = field(default_factory=ProcessScope)
    listeners: list[JobListener] = field(default_factory=list)
    done: threading.Event = field(default_factory=threading.Event)

    def event(self) -> JobEvent:
        info = self.info
        return JobEvent(
            job_id=info.id,
            status=info.status,
            stage=info.stage,
            fraction=info.fraction,
            message=info.message,
            error=info.error,
            result=info.result,
        )


class JobManager:
    """Runs jobs on a small thread pool, at most one active job per key (project)."""

    def __init__(self, max_workers: int = 2) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="job")
        self._lock = threading.Lock()
        self._jobs: dict[str, _Job] = {}
        self._active: dict[str, str] = {}

    def submit(self, kind: JobKind, key: str, project_id: str | None, work: JobWork) -> JobInfo:
        with self._lock:
            active = self._active.get(key)
            if active is not None:
                raise JobConflictError(active)
            info = JobInfo(
                id=uuid.uuid4().hex,
                kind=kind,
                project_id=project_id,
                status="queued",
                created_at=datetime.now(UTC),
            )
            job = _Job(info=info, key=key, work=work)
            self._jobs[info.id] = job
            self._active[key] = info.id
            snapshot = info.model_copy()
        self._executor.submit(self._run, job)
        return snapshot

    def _job(self, job_id: str) -> _Job:
        job = self._jobs.get(job_id)
        if job is None:
            raise JobNotFoundError(f"job {job_id!r} does not exist")
        return job

    def get(self, job_id: str) -> JobInfo:
        with self._lock:
            return self._job(job_id).info.model_copy()

    def active_job(self, key: str) -> JobInfo | None:
        with self._lock:
            job_id = self._active.get(key)
            return self._jobs[job_id].info.model_copy() if job_id else None

    def cancel(self, job_id: str) -> JobInfo:
        """Request a cancel; a queued job is cancelled at once, a running one at its next
        progress report or when its killed subprocess returns."""
        with self._lock:
            job = self._job(job_id)
            if job.info.status in TERMINAL_STATUSES:
                return job.info.model_copy()
            if job.info.status == "queued":
                self._finish(job, "cancelled", message="cancelled")
                return job.info.model_copy()
        job.scope.cancel()
        return self.get(job_id)

    def subscribe(self, job_id: str, listener: JobListener) -> tuple[JobEvent, Callable[[], None]]:
        """Register `listener` and return the current state, atomically, plus an unsubscribe."""
        with self._lock:
            job = self._job(job_id)
            if job.info.status not in TERMINAL_STATUSES:
                job.listeners.append(listener)
            snapshot = job.event()

        def unsubscribe() -> None:
            with self._lock:
                if listener in job.listeners:
                    job.listeners.remove(listener)

        return snapshot, unsubscribe

    def latest_job(self, key: str) -> JobInfo | None:
        """The most recently submitted job for `key`, active or finished."""
        with self._lock:
            for job in reversed(self._jobs.values()):  # insertion order is submission order
                if job.key == key:
                    return job.info.model_copy()
            return None

    def shutdown(self, timeout: float = SHUTDOWN_TIMEOUT_S) -> None:
        """Cancel running jobs and wait up to `timeout` seconds for them to stop. A job that
        never reports progress cannot be interrupted; it is logged and left behind."""
        with self._lock:
            running = [job for job in self._jobs.values() if job.info.status == "running"]
        for job in running:
            job.scope.cancel()
        self._executor.shutdown(wait=False, cancel_futures=True)
        deadline = time.monotonic() + timeout
        for job in running:
            if not job.done.wait(max(0.0, deadline - time.monotonic())):
                logger.warning("job %s did not stop within %.1f s", job.info.id, timeout)

    def _publish(self, job: _Job) -> None:
        """Send the job's state to its listeners; call with `self._lock` held."""
        event = job.event()
        for listener in list(job.listeners):
            try:
                listener(event)
            except Exception:  # a closed WebSocket loop must not break the job
                logger.debug("dropping a failed job listener", exc_info=True)
                job.listeners.remove(listener)
        if job.info.status in TERMINAL_STATUSES:
            job.listeners.clear()

    def _finish(self, job: _Job, status: JobStatus, **changes: Any) -> None:
        job.info = job.info.model_copy(update={"status": status, **changes})
        if self._active.get(job.key) == job.info.id:
            del self._active[job.key]
        self._publish(job)
        job.done.set()

    def _progress(self, job: _Job) -> ProgressCallback:
        def report(stage: str, fraction: float, message: str) -> None:
            if job.scope.cancelled:
                raise JobCancelledError("the job was cancelled")
            with self._lock:
                info = job.info
                visible = (
                    stage != info.stage
                    or message != info.message
                    or abs(fraction - info.fraction) >= MIN_FRACTION_STEP
                    or fraction in (0.0, 1.0)
                )
                if not visible:
                    return
                job.info = info.model_copy(
                    update={"stage": stage, "fraction": fraction, "message": message}
                )
                self._publish(job)

        return report

    def _run(self, job: _Job) -> None:
        with self._lock:
            if job.info.status != "queued":
                return
            job.info = job.info.model_copy(update={"status": "running"})
            self._publish(job)
        try:
            with process_scope(job.scope):
                result = job.work(self._progress(job))
        except Exception as exc:
            with self._lock:
                if job.scope.cancelled:
                    self._finish(job, "cancelled", message="cancelled")
                else:
                    if error_code(exc) == "internal_error":
                        logger.exception("job %s failed", job.info.id)
                    self._finish(
                        job, "failed", error=JobError(code=error_code(exc), message=str(exc))
                    )
            return
        with self._lock:
            if job.scope.cancelled:
                self._finish(job, "cancelled", message="cancelled")
            else:
                self._finish(job, "succeeded", fraction=1.0, message="done", result=result)
