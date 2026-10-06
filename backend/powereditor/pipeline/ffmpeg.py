import subprocess
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import cache
from typing import IO

from powereditor.settings_store import SettingsService

FractionCallback = Callable[[float], None]
STDERR_TAIL_CHARS = 2000


class MissingToolError(RuntimeError):
    def __init__(self, tool: str) -> None:
        super().__init__(f"{tool} not found; configure its path in settings")
        self.tool = tool
        self.code = f"missing_{tool}"


class FfmpegError(RuntimeError):
    code = "ffmpeg_failed"


@dataclass(frozen=True)
class MediaTools:
    ffmpeg: str
    ffprobe: str

    @classmethod
    def from_settings(cls, service: SettingsService) -> "MediaTools":
        ffmpeg = service.locate_executable("ffmpeg")
        if ffmpeg is None:
            raise MissingToolError("ffmpeg")
        ffprobe = service.locate_executable("ffprobe")
        if ffprobe is None:
            raise MissingToolError("ffprobe")
        return cls(ffmpeg=ffmpeg, ffprobe=ffprobe)


def parse_progress_seconds(line: str) -> float | None:
    """Return the processed media time from one `-progress` line, if present."""
    key, _, value = line.strip().partition("=")
    if key != "out_time_us":
        return None
    try:
        micros = int(value)
    except ValueError:
        return None
    return max(micros, 0) / 1_000_000


def _drain(stream: IO[str], sink: list[str]) -> None:
    sink.extend(stream)


def run_ffmpeg(
    ffmpeg: str,
    args: Sequence[str],
    duration: float | None = None,
    on_progress: FractionCallback | None = None,
) -> None:
    command = [ffmpeg, "-hide_banner", "-nostdin", "-nostats", "-loglevel", "error", "-y"]
    command += ["-progress", "pipe:1", *args]
    errors: list[str] = []
    with subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    ) as process:
        assert process.stdout is not None and process.stderr is not None
        drainer = threading.Thread(target=_drain, args=(process.stderr, errors), daemon=True)
        drainer.start()
        for line in process.stdout:
            seconds = parse_progress_seconds(line)
            if seconds is not None and on_progress is not None and duration:
                on_progress(min(seconds / duration, 1.0))
        returncode = process.wait()
        drainer.join()
    if returncode != 0:
        tail = "".join(errors)[-STDERR_TAIL_CHARS:].strip()
        raise FfmpegError(f"ffmpeg exited with code {returncode}: {tail}")
    if on_progress is not None:
        on_progress(1.0)


def run_capture(args: Sequence[str]) -> str:
    result = subprocess.run(
        list(args), capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )
    if result.returncode != 0:
        raise FfmpegError(f"{args[0]} exited with code {result.returncode}: {result.stderr[-500:]}")
    return result.stdout


def run_capture_bytes(args: Sequence[str]) -> bytes:
    """Run a command and return its raw stdout (e.g. ffmpeg rawvideo on pipe:1)."""
    result = subprocess.run(list(args), capture_output=True, check=False)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace")[-500:]
        raise FfmpegError(f"{args[0]} exited with code {result.returncode}: {stderr}")
    return result.stdout


def run_ffmpeg_stderr(ffmpeg: str, args: Sequence[str]) -> str:
    """Run ffmpeg for analysis filters that report on stderr (e.g. silencedetect)."""
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-nostdin", "-nostats", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise FfmpegError(f"ffmpeg exited with code {result.returncode}: {result.stderr[-500:]}")
    return result.stderr


@cache
def list_encoders(ffmpeg: str) -> str:
    return run_capture([ffmpeg, "-hide_banner", "-encoders"])
