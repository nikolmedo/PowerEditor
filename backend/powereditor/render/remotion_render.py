"""Render a project with the Remotion composition in `packages/composition`.

The backend runs `scripts/render.mjs` (bundler + renderer APIs) rather than
`pnpm exec remotion render`: the script must start under a specific Node binary
(x64 on Windows, see `node_runtime`), which a pnpm shim would not honour, and it
reports bundling and rendering times separately as JSON lines.

A render that stops making progress (a hung browser, a stuck compositor) is
killed after a generous timeout that grows with the timeline length.
"""

import json
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from powereditor.models import Project
from powereditor.pipeline.ffmpeg import FractionCallback
from powereditor.process import kill_tree
from powereditor.render.base import RenderSettings, RenderTiming
from powereditor.render.media_server import serve_directory
from powereditor.timeline import timeline_layout

STDERR_TAIL_CHARS = 4000
COMPOSITION_DIR = Path(__file__).resolve().parents[3] / "packages" / "composition"
# Measured on an emulated x64 Node: ~30 s startup + ~0.17 s per 1080p frame.
# The budget is an order of magnitude above that so only a truly stuck render dies.
TIMEOUT_BASE_S = 600.0
TIMEOUT_PER_FRAME_S = 2.0


class RenderError(RuntimeError):
    code = "render_failed"


class RenderTimeoutError(RenderError):
    code = "render_timeout"


def render_timeout_s(frames: int) -> float:
    return TIMEOUT_BASE_S + TIMEOUT_PER_FRAME_S * frames


@dataclass(frozen=True)
class RenderEvent:
    event: str
    fraction: float | None = None
    ms: int | None = None
    frames: int | None = None
    message: str | None = None


def parse_render_event(line: str) -> RenderEvent | None:
    """One JSON-lines event from `render.mjs`; any other output yields None."""
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("event"), str):
        return None
    fraction = data.get("fraction")
    ms = data.get("ms")
    frames = data.get("frames")
    message = data.get("message")
    return RenderEvent(
        event=data["event"],
        fraction=float(fraction) if isinstance(fraction, int | float) else None,
        ms=ms if isinstance(ms, int) else None,
        frames=frames if isinstance(frames, int) else None,
        message=message if isinstance(message, str) else None,
    )


def _drain(stream: IO[str], sink: list[str]) -> None:
    sink.extend(stream)


def _check_media(project: Project, media_dir: Path) -> None:
    for source in project.sources:
        served = media_dir / Path(source.mezzanine_path).name
        if not served.is_file():
            raise RenderError(f"mezzanine for source {source.id} is not in {media_dir}")


class RemotionRenderer:
    def __init__(
        self,
        node: str,
        composition_dir: Path = COMPOSITION_DIR,
        *,
        script: Path | None = None,
        timeout_s: float | None = None,
    ) -> None:
        self.node = node
        self.composition_dir = composition_dir
        self.script = script or composition_dir / "scripts" / "render.mjs"
        self.timeout_s = timeout_s

    def render(
        self,
        project: Project,
        media_dir: Path,
        output: Path,
        settings: RenderSettings,
        on_progress: FractionCallback | None = None,
    ) -> RenderTiming:
        _check_media(project, media_dir)
        output.parent.mkdir(parents=True, exist_ok=True)
        props_file = output.with_name(f"{output.stem}.props.json")
        started = time.perf_counter()
        bundled_at: float | None = None
        errors: list[str] = []
        failure: str | None = None
        timeout_s = self.timeout_s or render_timeout_s(timeline_layout(project).duration_in_frames)
        timed_out = threading.Event()
        try:
            with serve_directory(media_dir) as base_url:
                props = {
                    "project": project.model_dump(by_alias=True, mode="json"),
                    "audioCrossfadeMs": settings.audio_crossfade_ms,
                    "punchInScale": settings.punch_in_scale,
                    "mediaBaseUrl": base_url,
                }
                props_file.write_text(json.dumps(props), encoding="utf-8")
                command = [
                    self.node,
                    str(self.script),
                    "--props", str(props_file),
                    "--output", str(output),
                ]  # fmt: skip
                with subprocess.Popen(
                    command,
                    cwd=self.composition_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                ) as process:
                    assert process.stdout is not None and process.stderr is not None
                    drainer = threading.Thread(
                        target=_drain, args=(process.stderr, errors), daemon=True
                    )
                    drainer.start()

                    def expire() -> None:
                        timed_out.set()
                        kill_tree(process)

                    # Killing the process closes stdout, which ends the read loop below.
                    watchdog = threading.Timer(timeout_s, expire)
                    watchdog.start()
                    try:
                        for line in process.stdout:
                            event = parse_render_event(line)
                            if event is None:
                                continue
                            if event.event == "bundled":
                                bundled_at = time.perf_counter()
                            elif event.event == "error":
                                failure = event.message
                            elif (
                                event.event == "progress"
                                and on_progress
                                and event.fraction is not None
                            ):
                                on_progress(min(event.fraction, 1.0))
                        returncode = process.wait()
                    finally:
                        watchdog.cancel()
                    drainer.join()
        finally:
            props_file.unlink(missing_ok=True)
        if timed_out.is_set():
            raise RenderTimeoutError(f"Remotion render timed out after {timeout_s:.0f}s")
        if returncode != 0:
            cause = failure or "".join(errors)[-STDERR_TAIL_CHARS:].strip()
            raise RenderError(f"Remotion render exited with code {returncode}: {cause}")
        finished = time.perf_counter()
        setup_end = bundled_at or started
        return RenderTiming(setup_s=setup_end - started, render_s=finished - setup_end)
