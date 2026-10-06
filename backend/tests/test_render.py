import json
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from powereditor.models import Project
from powereditor.pipeline.ffmpeg import run_capture, run_ffmpeg_stderr
from powereditor.pipeline.loudness import parse_integrated_lufs
from powereditor.render.base import RenderSettings
from powereditor.render.final_pass import (
    LoudnormMeasurement,
    finalize_export,
    loudnorm_filter,
    mux_args,
    parse_loudnorm_json,
    should_normalize,
)
from powereditor.render.media_server import serve_directory
from powereditor.render.node_runtime import NodeRuntimeError, resolve_render_node
from powereditor.render.remotion_render import (
    RemotionRenderer,
    RenderError,
    RenderEvent,
    parse_render_event,
    render_timeout_s,
)
from tests.media import FFMPEG, FFPROBE, ffmpeg_lavfi, needs_ffmpeg

FIXTURE = (
    Path(__file__).parents[2] / "packages" / "composition" / "test" / "fixtures" / "project.json"
)

LOUDNORM_STDERR = """
[Parsed_loudnorm_0 @ 000001]
{
	"input_i" : "-27.47",
	"input_tp" : "-4.47",
	"input_lra" : "0.00",
	"input_thresh" : "-37.47",
	"output_i" : "-14.09",
	"output_tp" : "-1.00",
	"output_lra" : "0.00",
	"output_thresh" : "-24.09",
	"normalization_type" : "dynamic",
	"target_offset" : "0.09"
}
"""


class ArchProbe:
    def __init__(self, arches: dict[str, str]) -> None:
        self.arches = arches
        self.probed: list[str] = []

    def __call__(self, node: str) -> str | None:
        self.probed.append(node)
        return self.arches.get(node)


def _file(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


# --- loudnorm -------------------------------------------------------------------------


def test_parse_loudnorm_json_reads_the_measured_values() -> None:
    measurement = parse_loudnorm_json(LOUDNORM_STDERR)

    assert measurement == LoudnormMeasurement(
        input_i=-27.47, input_tp=-4.47, input_lra=0.0, input_thresh=-37.47, target_offset=0.09
    )


def test_parse_loudnorm_json_uses_the_last_block_and_rejects_missing_output() -> None:
    earlier = LOUDNORM_STDERR.replace("-27.47", "-99.00")
    assert parse_loudnorm_json(earlier + LOUDNORM_STDERR).input_i == -27.47
    with pytest.raises(ValueError, match="loudnorm"):
        parse_loudnorm_json("no json here")


def test_loudnorm_filter_feeds_the_measurement_back_in_linear_mode() -> None:
    measurement = parse_loudnorm_json(LOUDNORM_STDERR)

    assert loudnorm_filter(measurement, target_lufs=-14.0) == (
        "loudnorm=I=-14.0:TP=-1.0:LRA=11.0:measured_I=-27.47:measured_TP=-4.47"
        ":measured_LRA=0.0:measured_thresh=-37.47:offset=0.09:linear=true:print_format=summary"
    )


def test_mux_args_copy_remotion_video_and_encode_the_rebuilt_voice() -> None:
    args = mux_args(Path("v.mp4"), Path("voice.wav"), Path("out.mp4"), "loudnorm=I=-14")

    assert args[:4] == ["-i", "v.mp4", "-i", "voice.wav"]
    first_map = args.index("-map")
    assert args[first_map : first_map + 4] == ["-map", "0:v:0", "-map", "1:a:0"]
    assert args[args.index("-c:v") + 1] == "copy"
    assert args[args.index("-af") + 1] == "loudnorm=I=-14"
    assert args[args.index("-b:a") + 1] == "192k"
    assert args[args.index("-ar") + 1] == "48000"
    assert args[args.index("-movflags") + 1] == "+faststart"
    assert args[-1] == "out.mp4"
    assert "-af" not in mux_args(Path("v.mp4"), Path("voice.wav"), Path("out.mp4"), None)


@pytest.mark.parametrize(
    ("input_i", "expected"),
    [(-27.47, True), (-69.0, True), (-75.0, False), (float("-inf"), False)],
)
def test_silent_or_near_silent_voice_is_not_normalized(input_i: float, expected: bool) -> None:
    measurement = LoudnormMeasurement(input_i, -4.0, 0.0, -37.0, 0.1)

    assert should_normalize(measurement) is expected


def _video_only(path: Path, seconds: float) -> Path:
    return ffmpeg_lavfi(
        path,
        "-f", "lavfi", "-i", f"testsrc2=size=160x120:rate=30:duration={seconds}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
    )  # fmt: skip


def _wav(path: Path, source: str) -> Path:
    return ffmpeg_lavfi(path, "-f", "lavfi", "-i", source, "-c:a", "pcm_f32le", "-ac", "2")


def _stream_durations(path: Path) -> dict[str, float]:
    assert FFPROBE is not None
    rows = run_capture(
        [FFPROBE, "-v", "error", "-show_entries", "stream=codec_name,duration",
         "-of", "csv=p=0", str(path)]
    ).split()  # fmt: skip
    return {name: float(value) for name, value in (row.split(",") for row in rows)}


@pytest.mark.ffmpeg
@needs_ffmpeg
def test_finalize_export_normalizes_the_voice_and_keeps_av_in_sync(tmp_path: Path) -> None:
    assert FFMPEG is not None
    video = _video_only(tmp_path / "video.mp4", 6)
    voice = _wav(
        tmp_path / "voice.wav", "sine=frequency=330:duration=6:sample_rate=48000,volume=0.05"
    )
    output = tmp_path / "final.mp4"

    result = finalize_export(FFMPEG, video, voice, output, target_lufs=-14.0)

    assert result.normalized is True
    measured = parse_integrated_lufs(
        run_ffmpeg_stderr(FFMPEG, ["-i", str(output), "-af", "ebur128", "-f", "null", "-"])
    )
    assert abs(measured - -14.0) <= 1.0
    durations = _stream_durations(output)
    assert list(durations) == ["h264", "aac"]
    assert abs(durations["h264"] - durations["aac"]) <= 1 / 30


@pytest.mark.ffmpeg
@needs_ffmpeg
def test_finalize_export_passes_silent_voice_through_without_loudnorm(tmp_path: Path) -> None:
    assert FFMPEG is not None
    video = _video_only(tmp_path / "video.mp4", 3)
    voice = _wav(tmp_path / "voice.wav", "anullsrc=r=48000:cl=stereo:d=3")
    output = tmp_path / "final.mp4"

    result = finalize_export(FFMPEG, video, voice, output, target_lufs=-14.0)

    assert result.normalized is False
    assert list(_stream_durations(output)) == ["h264", "aac"]


# --- render events --------------------------------------------------------------------


def test_parse_render_event_reads_progress_and_timing_lines() -> None:
    assert parse_render_event('{"event":"progress","fraction":0.25}') == RenderEvent(
        "progress", fraction=0.25
    )
    assert parse_render_event('{"event":"bundled","ms":1200}') == RenderEvent("bundled", ms=1200)
    assert parse_render_event('{"event":"done","ms":5000,"frames":90}') == RenderEvent(
        "done", ms=5000, frames=90
    )


def test_parse_render_event_ignores_non_event_output() -> None:
    assert parse_render_event("Downloading Chrome Headless Shell") is None
    assert parse_render_event('{"other": 1}') is None
    assert parse_render_event("[1, 2]") is None


# --- node runtime ---------------------------------------------------------------------


def test_render_node_prefers_the_configured_binary(tmp_path: Path) -> None:
    configured = str(_file(tmp_path / "custom" / "node.exe"))
    probe = ArchProbe({configured: "x64"})

    node = resolve_render_node(configured, tmp_path / "bin", probe, which=lambda _: None)

    assert node == configured


def test_render_node_skips_arm64_and_falls_back_to_bundled_x64(tmp_path: Path) -> None:
    bundled = str(_file(tmp_path / "bin" / "node-x64" / "node.exe"))
    probe = ArchProbe({"/usr/node": "arm64", bundled: "x64"})

    node = resolve_render_node(None, tmp_path / "bin", probe, which=lambda _: "/usr/node")

    assert node == bundled


def test_render_node_rejects_a_system_arm64_node_on_windows(tmp_path: Path) -> None:
    probe = ArchProbe({"/usr/node": "arm64"})

    with pytest.raises(NodeRuntimeError) as excinfo:
        resolve_render_node(
            None, tmp_path / "bin", probe, which=lambda _: "/usr/node", platform="win32"
        )

    assert excinfo.value.code == "missing_node_x64"
    assert probe.probed == ["/usr/node"]


def test_render_node_accepts_any_arch_outside_windows(tmp_path: Path) -> None:
    probe = ArchProbe({"/usr/bin/node": "arm64"})

    node = resolve_render_node(
        None, tmp_path / "bin", probe, which=lambda _: "/usr/bin/node", platform="darwin"
    )

    assert node == "/usr/bin/node"


# --- media server ---------------------------------------------------------------------


def test_media_server_serves_files_from_the_directory(tmp_path: Path) -> None:
    (tmp_path / "s1 clip.mp4").write_bytes(b"video-bytes")

    with serve_directory(tmp_path) as base_url:
        assert base_url.startswith("http://127.0.0.1:")
        with urllib.request.urlopen(f"{base_url}/s1%20clip.mp4", timeout=5) as response:
            body: bytes = response.read()

    assert body == b"video-bytes"


# --- remotion renderer (fake Node process) --------------------------------------------

FAKE_RENDER_SCRIPT = r"""
import json, os, sys, time

def emit(event):
    print(json.dumps(event), flush=True)

args = sys.argv[1:]
props = json.loads(open(args[args.index("--props") + 1], encoding="utf-8").read())
mode = os.environ["FAKE_RENDER_MODE"]
emit({"event": "bundled", "ms": 10})
if mode == "ok":
    print("Chrome noise", flush=True)
    for fraction in (0.25, 0.5, 1.5):
        emit({"event": "progress", "fraction": fraction})
    with open(args[args.index("--output") + 1], "w", encoding="utf-8") as out:
        json.dump(props, out)
    emit({"event": "done", "ms": 20, "frames": 3})
elif mode == "error-event":
    emit({"event": "error", "message": "composition ProjectVideo crashed"})
    sys.exit(1)
elif mode == "exit":
    sys.stderr.write("node: fatal crash\n")
    sys.exit(3)
else:
    time.sleep(60)
"""


def _fake_renderer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str, timeout_s: float = 30.0
) -> tuple[RemotionRenderer, Project, Path]:
    monkeypatch.setenv("FAKE_RENDER_MODE", mode)
    script = tmp_path / "fake_render.py"
    script.write_text(FAKE_RENDER_SCRIPT, encoding="utf-8")
    media = tmp_path / "media"
    _file(media / "s1.mezzanine.mp4")
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    renderer = RemotionRenderer(sys.executable, script=script, timeout_s=timeout_s)
    return renderer, Project.model_validate(fixture["project"]), media


def test_remotion_renderer_forwards_clamped_progress_and_passes_props(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    renderer, project, media = _fake_renderer(tmp_path, monkeypatch, "ok")
    output = tmp_path / "out" / "video.mp4"
    fractions: list[float] = []

    timing = renderer.render(project, media, output, RenderSettings(15), fractions.append)

    assert fractions == [0.25, 0.5, 1.0]
    props = json.loads(output.read_text(encoding="utf-8"))
    assert props["audioCrossfadeMs"] == 15
    assert props["mediaBaseUrl"].startswith("http://127.0.0.1:")
    assert props["project"]["clips"][0]["id"] == "c1"
    assert sorted(p.name for p in output.parent.iterdir()) == ["video.mp4"]
    assert timing.setup_s >= 0 and timing.render_s >= 0


@pytest.mark.parametrize(
    ("mode", "message"),
    [("error-event", "composition ProjectVideo crashed"), ("exit", "code 3: node: fatal crash")],
)
def test_remotion_renderer_reports_failures_with_their_cause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str, message: str
) -> None:
    renderer, project, media = _fake_renderer(tmp_path, monkeypatch, mode)

    with pytest.raises(RenderError, match=message) as excinfo:
        renderer.render(project, media, tmp_path / "video.mp4", RenderSettings(15))

    assert excinfo.value.code == "render_failed"


def test_remotion_renderer_kills_a_hung_render_after_the_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    renderer, project, media = _fake_renderer(tmp_path, monkeypatch, "hang", timeout_s=1.0)
    started = time.perf_counter()

    with pytest.raises(RenderError, match="timed out") as excinfo:
        renderer.render(project, media, tmp_path / "video.mp4", RenderSettings(15))

    assert excinfo.value.code == "render_timeout"
    assert time.perf_counter() - started < 30


def test_default_render_timeout_grows_with_the_timeline() -> None:
    assert render_timeout_s(0) == 600.0
    assert render_timeout_s(1800) == 600.0 + 1800 * 2.0
