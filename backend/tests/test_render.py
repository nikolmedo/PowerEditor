import urllib.request
from pathlib import Path

import pytest

from powereditor.pipeline.ffmpeg import run_capture, run_ffmpeg_stderr
from powereditor.pipeline.loudness import parse_integrated_lufs
from powereditor.render.final_pass import (
    LoudnormMeasurement,
    apply_loudnorm_args,
    normalize_loudness,
    parse_loudnorm_json,
)
from powereditor.render.media_server import serve_directory
from powereditor.render.node_runtime import NodeRuntimeError, resolve_render_node
from powereditor.render.remotion_render import RenderEvent, parse_render_event
from tests.media import FFMPEG, FFPROBE, ffmpeg_lavfi, needs_ffmpeg

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


def test_apply_args_feed_the_measurement_back_in_linear_mode() -> None:
    measurement = parse_loudnorm_json(LOUDNORM_STDERR)

    args = apply_loudnorm_args(Path("in.mp4"), Path("out.mp4"), measurement, target_lufs=-14.0)

    audio_filter = args[args.index("-af") + 1]
    assert audio_filter == (
        "loudnorm=I=-14.0:TP=-1.0:LRA=11.0:measured_I=-27.47:measured_TP=-4.47"
        ":measured_LRA=0.0:measured_thresh=-37.47:offset=0.09:linear=true:print_format=summary"
    )
    assert args[args.index("-c:v") + 1] == "copy"
    assert args[args.index("-b:a") + 1] == "192k"
    assert args[args.index("-ar") + 1] == "48000"
    assert args[args.index("-movflags") + 1] == "+faststart"
    assert args[-1] == "out.mp4"


@pytest.mark.ffmpeg
@needs_ffmpeg
def test_normalize_loudness_reaches_the_target_and_copies_video(tmp_path: Path) -> None:
    assert FFMPEG is not None and FFPROBE is not None
    quiet = ffmpeg_lavfi(
        tmp_path / "quiet.mp4",
        "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=30:duration=6",
        "-f", "lavfi", "-i", "sine=frequency=330:duration=6,volume=0.05",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
    )  # fmt: skip
    output = tmp_path / "final.mp4"

    normalize_loudness(FFMPEG, quiet, output, target_lufs=-14.0)

    measured = parse_integrated_lufs(
        run_ffmpeg_stderr(FFMPEG, ["-i", str(output), "-af", "ebur128", "-f", "null", "-"])
    )
    assert abs(measured - -14.0) <= 1.0
    codecs = run_capture(
        [
            FFPROBE,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name",
            "-of",
            "csv=p=0",
            str(output),
        ]
    ).split()
    assert codecs == ["h264", "aac"]


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
