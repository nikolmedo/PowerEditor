import json
import shutil
import subprocess
import sys
import wave
from pathlib import Path
from typing import Any

import pytest

from powereditor import process as process_module
from powereditor.paths import AppPaths
from powereditor.pipeline import ingest as ingest_module
from powereditor.pipeline.encoders import MF_HARDWARE, encoder_probe
from powereditor.pipeline.ffmpeg import (
    FfmpegError,
    MediaTools,
    encoder_works,
    list_encoders,
    parse_progress_seconds,
    run_ffmpeg,
)
from powereditor.pipeline.ingest import (
    IngestedSource,
    IngestPlan,
    ProbeResult,
    can_copy_video,
    choose_encoder,
    fallback_plans,
    ingest_args,
    ingest_files,
    ingest_parallelism,
    ingest_source,
    mezzanine_size,
    parse_rate,
    probe_media,
    source_id_for,
    target_fps,
)
from powereditor.pipeline.runner import ProjectLayout
from powereditor.process import ProcessScope, process_scope

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
needs_ffmpeg = pytest.mark.skipif(
    FFMPEG is None or FFPROBE is None, reason="ffmpeg/ffprobe not found"
)

LGPL_LISTING = (
    " V....D libopenh264  OpenH264 H.264\n V....D h264_mf  H264 via MediaFoundation\n"
    " V....D h264_nvenc  NVIDIA NVENC H.264 encoder\n"
)
OPENH264_ONLY_LISTING = " V....D libopenh264  OpenH264 H.264\n"
NVENC_LISTING = " V....D libx264  libx264 H.264\n V....D h264_nvenc  NVIDIA NVENC H.264 encoder\n"


def _probe(**overrides: Any) -> ProbeResult:
    values: dict[str, Any] = {
        "duration": 2.0,
        "width": 1920,
        "height": 1080,
        "rotation": 0,
        "r_frame_rate": 30.0,
        "avg_frame_rate": 30.0,
        "has_audio": True,
        "video_codec": "h264",
        "audio_codec": "aac",
    }
    values.update(overrides)
    return ProbeResult(**values)


@pytest.mark.parametrize(
    ("raw", "expected"), [("30000/1001", 29.97), ("25/1", 25.0), ("0/0", 0.0), ("24", 24.0)]
)
def test_parse_rate(raw: str, expected: float) -> None:
    assert parse_rate(raw) == pytest.approx(expected, abs=0.01)


def test_probe_flags_vfr_and_display_size() -> None:
    assert _probe(avg_frame_rate=14.4).is_vfr
    assert not _probe(r_frame_rate=29.97, avg_frame_rate=29.97).is_vfr
    rotated = _probe(rotation=-90)
    assert (rotated.display_width, rotated.display_height) == (1080, 1920)


@pytest.mark.parametrize(("avg", "expected"), [(23.976, 24), (29.97, 30), (59.94, 60), (25, 25)])
def test_target_fps_snaps_to_standard_rates(avg: float, expected: int) -> None:
    assert target_fps(_probe(avg_frame_rate=avg, r_frame_rate=avg)) == expected


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"width": 3840, "height": 2160, "rotation": -90}, (1080, 1920)),
        ({"width": 3840, "height": 2160}, (1920, 1080)),
        ({"width": 1920, "height": 1080}, (1920, 1080)),
        ({"width": 1440, "height": 1080}, (1440, 1080)),
        ({"width": 2880, "height": 2160}, (1440, 1080)),
        ({"width": 320, "height": 240}, (320, 240)),
        ({"width": 2560, "height": 1081}, (1920, 810)),
    ],
)
def test_mezzanine_fits_the_largest_render_and_never_upscales(
    overrides: dict[str, Any], expected: tuple[int, int]
) -> None:
    assert mezzanine_size(_probe(**overrides)) == expected


PHONE_H264 = {"width": 1080, "height": 1920, "pix_fmt": "yuv420p", "profile": "High"}


@pytest.mark.parametrize(
    ("overrides", "fps", "expected"),
    [
        ({}, 30, True),
        ({"profile": "Main"}, 30, True),
        ({"video_codec": "hevc"}, 30, False),
        ({"pix_fmt": "yuvj420p"}, 30, False),
        ({"pix_fmt": "yuv420p10le", "profile": "High 10"}, 30, False),
        ({"color_range": "pc"}, 30, False),
        ({"avg_frame_rate": 29.97, "r_frame_rate": 29.97}, 30, False),
        ({"avg_frame_rate": 27.5}, 30, False),
        ({"avg_frame_rate": 23.976, "r_frame_rate": 23.976}, 24, False),
        ({}, 25, False),
        ({"rotation": 90}, 30, False),
        ({"width": 2160, "height": 3840}, 30, False),
    ],
)
def test_video_is_copied_only_when_it_already_is_a_valid_mezzanine(
    overrides: dict[str, Any], fps: int, expected: bool
) -> None:
    assert can_copy_video(_probe(**{**PHONE_H264, **overrides}), fps) is expected


def _plan(**overrides: Any) -> IngestPlan:
    values: dict[str, Any] = {"fps": 30, "width": 1080, "height": 1920, "encoder": "libx264"}
    values.update(overrides)
    return IngestPlan(**values)


def _outputs(args: list[str]) -> list[str]:
    return [arg for arg in args if arg.endswith((".mp4", ".wav")) and arg != "in.mov"]


def _output_args(args: list[str], output: str) -> list[str]:
    """The options between the previous output (or the filter graph) and `output`."""
    end = args.index(output)
    previous = [i for i, arg in enumerate(args[:end]) if arg in _outputs(args)]
    start = previous[-1] + 1 if previous else args.index("-filter_complex") + 2
    return args[start:end]


def test_one_ffmpeg_run_writes_mezzanine_proxy_and_wav_from_one_decode() -> None:
    args = ingest_args(Path("in.mov"), _plan(), Path("m.mp4"), Path("p.mp4"), Path("a.wav"))

    assert args.count("-i") == 1
    assert _outputs(args) == ["m.mp4", "p.mp4", "a.wav"]
    graph = args[args.index("-filter_complex") + 1]
    assert graph.startswith("[0:v]fps=30,scale=1080:1920:out_range=tv,format=yuv420p,split=2")
    assert graph.endswith("scale=540:960[p]")
    mezzanine = _output_args(args, "m.mp4")
    assert mezzanine[:2] == ["-map", "[m]"] and "libx264" in mezzanine
    proxy = _output_args(args, "p.mp4")
    assert proxy[:2] == ["-map", "[p]"]
    assert proxy[proxy.index("-g") + 1] == "12"
    wav = _output_args(args, "a.wav")
    assert wav[wav.index("-ar") + 1] == "16000" and "pcm_s16le" in wav
    assert "-r" not in args and "-hwaccel" not in args


def test_hardware_plans_decode_on_the_gpu_and_feed_nv12() -> None:
    plan = _plan(encoder=MF_HARDWARE, hwaccel="d3d11va")
    args = ingest_args(Path("in.mov"), plan, Path("m.mp4"), Path("p.mp4"), Path("a.wav"))

    assert args[: args.index("-i")] == ["-hwaccel", "d3d11va"]
    assert "format=nv12" in args[args.index("-filter_complex") + 1]
    assert _output_args(args, "p.mp4")[2:6] == ["-map", "0:a:0", "-c:v", "h264_mf"]


def test_a_copied_mezzanine_keeps_the_video_stream_and_still_gets_a_proxy() -> None:
    plan = _plan(copy_video=True)
    args = ingest_args(Path("in.mov"), plan, Path("m.mp4"), Path("p.mp4"), Path("a.wav"))

    mezzanine = _output_args(args, "m.mp4")
    assert mezzanine[:4] == ["-map", "0:v:0", "-c:v", "copy"]
    assert args[args.index("-filter_complex") + 1] == (
        "[0:v]fps=30,scale=540:960:out_range=tv,format=yuv420p[p]"
    )


def test_a_source_without_audio_writes_no_wav() -> None:
    args = ingest_args(
        Path("in.mov"), _plan(has_audio=False), Path("m.mp4"), Path("p.mp4"), Path("a.wav")
    )

    assert _outputs(args) == ["m.mp4", "p.mp4"]
    assert "0:a:0" not in args


def test_failed_hardware_runs_retry_in_software() -> None:
    hardware = _plan(encoder=MF_HARDWARE, hwaccel="d3d11va")

    assert fallback_plans(hardware, "h264_mf") == [
        hardware,
        _plan(encoder=MF_HARDWARE),
        _plan(encoder="h264_mf"),
    ]
    assert fallback_plans(_plan(), "libx264") == [_plan()]


def test_two_sources_ingest_at_once_only_with_a_hardware_encoder() -> None:
    assert ingest_parallelism(MF_HARDWARE, sources=5) == 2
    assert ingest_parallelism(MF_HARDWARE, sources=1) == 1
    assert ingest_parallelism("libx264", sources=5) == 1


def test_parse_progress_seconds() -> None:
    assert parse_progress_seconds("out_time_us=1500000\n") == 1.5
    assert parse_progress_seconds("out_time_ms=1500000") is None
    assert parse_progress_seconds("out_time_us=N/A") is None


def _make_clip(path: Path, extra: list[str], video: str, audio: bool = True) -> Path:
    assert FFMPEG is not None
    args = [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", video]
    if audio:
        args += ["-f", "lavfi", "-i", "sine=frequency=440:duration=2"]
    args += [*extra, "-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if audio:
        args += ["-c:a", "aac", "-shortest"]
    subprocess.run([*args, str(path)], check=True)
    return path


@pytest.fixture(scope="module")
def clips(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    if FFMPEG is None:
        pytest.skip("ffmpeg not found")
    root = tmp_path_factory.mktemp("media dir con espacios")
    accented = _make_clip(
        root / "tomá 1.mp4", [], "testsrc2=size=320x240:rate=24000/1001:duration=2"
    )
    vfr = _make_clip(
        root / "vfr.mp4",
        ["-vf", "select='not(mod(n,3))+lt(n,10)'", "-fps_mode", "vfr"],
        "testsrc2=size=320x240:rate=30:duration=2",
    )
    upright = _make_clip(
        root / "upright.mp4", [], "testsrc2=size=320x240:rate=30:duration=2", audio=False
    )
    rotated = root / "rotated.mp4"
    rotate = ["-display_rotation", "90", "-i", str(upright), "-c", "copy"]
    subprocess.run(
        [FFMPEG, "-v", "error", "-y", *rotate, str(rotated)],
        check=True,
    )
    cfr = _make_clip(root / "cfr.mp4", [], "testsrc2=size=320x240:rate=30:duration=2")
    return {"accented": accented, "vfr": vfr, "rotated": rotated, "cfr": cfr}


def _tools() -> MediaTools:
    assert FFMPEG is not None and FFPROBE is not None
    return MediaTools(ffmpeg=FFMPEG, ffprobe=FFPROBE)


def _stream(path: Path) -> dict[str, Any]:
    assert FFPROBE is not None
    flags = ["-v", "error", "-select_streams", "v:0", "-show_streams", "-show_format"]
    out = subprocess.run(
        [FFPROBE, *flags, "-print_format", "json", str(path)],
        capture_output=True,
        check=True,
        text=True,
    ).stdout
    data = json.loads(out)
    stream: dict[str, Any] = data["streams"][0]
    stream["format_duration"] = float(data["format"]["duration"])
    return stream


@pytest.mark.ffmpeg
@needs_ffmpeg
def test_probe_media_reads_real_files(clips: dict[str, Path]) -> None:
    accented = probe_media(_tools().ffprobe, clips["accented"])
    assert accented.duration == pytest.approx(2.0, abs=0.1)
    assert (accented.width, accented.height) == (320, 240)
    assert accented.avg_frame_rate == pytest.approx(23.976, abs=0.01)
    assert accented.has_audio
    assert accented.video_codec == "h264"

    assert probe_media(_tools().ffprobe, clips["vfr"]).is_vfr

    rotated = probe_media(_tools().ffprobe, clips["rotated"])
    assert abs(rotated.rotation) == 90
    assert not rotated.has_audio
    assert (rotated.display_width, rotated.display_height) == (240, 320)


@pytest.mark.ffmpeg
@needs_ffmpeg
def test_ingest_produces_cfr_mezzanine_proxy_and_wav(
    clips: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layout = ProjectLayout.for_project(AppPaths(data_dir=tmp_path), "demo")
    events: list[tuple[str, float, str]] = []

    def record(stage: str, fraction: float, message: str) -> None:
        events.append((stage, fraction, message))

    manifest = ingest_files(
        layout,
        [clips["accented"], clips["vfr"], clips["rotated"], clips["cfr"]],
        _tools(),
        cuda_available=False,
        progress=record,
    )

    assert len(manifest.sources) == 4
    accented, vfr, rotated, cfr = manifest.sources
    assert accented.fps == 24
    assert accented.video_encoder == choose_encoder(_tools().ffmpeg, False)
    assert accented.video_decoder != "copy"
    mezz = _stream(Path(accented.mezzanine_path))
    assert mezz["r_frame_rate"] == mezz["avg_frame_rate"] == "24/1"
    assert mezz["format_duration"] == pytest.approx(2.0, abs=0.15)
    assert (mezz["width"], mezz["height"]) == (320, 240)
    proxy = _stream(Path(accented.proxy_path))
    assert (proxy["width"], proxy["height"]) == (720, 540)
    assert accented.wav_path is not None
    with wave.open(accented.wav_path, "rb") as wav:
        assert (wav.getnchannels(), wav.getframerate(), wav.getsampwidth()) == (1, 16000, 2)
        assert wav.getnframes() / 16000 == pytest.approx(2.0, abs=0.1)

    assert vfr.probe.is_vfr
    vfr_mezz = _stream(Path(vfr.mezzanine_path))
    assert vfr_mezz["r_frame_rate"] == vfr_mezz["avg_frame_rate"]

    rotated_proxy = _stream(Path(rotated.proxy_path))
    assert (rotated_proxy["width"], rotated_proxy["height"]) == (540, 720)
    assert rotated.wav_path is None

    assert cfr.video_decoder == "copy"
    copied = _stream(Path(cfr.mezzanine_path))
    assert (copied["codec_name"], copied["width"]) == ("h264", 320)
    assert copied["avg_frame_rate"] == "30/1"
    assert copied["format_duration"] == pytest.approx(2.0, abs=0.15)
    assert _stream(Path(cfr.proxy_path))["height"] == 540

    stage = f"ingest-{accented.source_id}"
    fractions = [f for s, f, _ in events if s == stage]
    assert fractions == sorted(fractions)
    assert fractions[-1] == 1.0
    assert any(0.0 < f < 1.0 for f in fractions)

    saved = json.loads(layout.cache_file("ingest").read_text(encoding="utf-8"))
    assert [s["sourceId"] for s in saved["sources"]] == [s.source_id for s in manifest.sources]

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("ffmpeg must not run on a cache hit")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    again = ingest_files(layout, [clips["accented"]], _tools(), cuda_available=False)
    assert again.sources[0] == accented
    assert len(again.sources) == 4


class FakeFfmpeg:
    """Stands in for ffmpeg: writes every `.part` output named in the arguments."""

    def __init__(self, fail_when: str | None = None) -> None:
        self.outputs: list[Path] = []
        self.calls: list[list[str]] = []
        self.scopes: list[ProcessScope | None] = []
        self.fail_when = fail_when

    def __call__(self, ffmpeg: str, args: list[str], *rest: object) -> None:
        self.calls.append(list(args))
        self.scopes.append(process_module._current_scope.get())
        for output in (Path(arg) for arg in args if ".part." in arg):
            self.outputs.append(output)
            if output.suffix == ".wav":
                with wave.open(str(output), "wb") as handle:
                    handle.setnchannels(1)
                    handle.setsampwidth(2)
                    handle.setframerate(16000)
                    handle.writeframes(b"\x00\x00" * 1600)
            else:
                output.write_bytes(b"video")
        if self.fail_when is not None and self.fail_when in args:
            raise FfmpegError("simulated crash")


@pytest.fixture
def fake_media(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    state: dict[str, Any] = {
        "listing": " V....D libx264  libx264 H.264\n",
        "ffmpeg": FakeFfmpeg(),
        "works": lambda encoder: True,
        "hwaccel": None,
    }
    monkeypatch.setattr(ingest_module, "probe_media", lambda ffprobe, path: _probe())
    monkeypatch.setattr(ingest_module, "list_encoders", lambda ffmpeg: state["listing"])
    monkeypatch.setattr(ingest_module, "encoder_probe", lambda ffmpeg: state["works"])
    monkeypatch.setattr(ingest_module, "list_hwaccels", lambda ffmpeg: "")
    monkeypatch.setattr(ingest_module, "select_hwaccel", lambda *args: state["hwaccel"])
    monkeypatch.setattr(ingest_module, "run_ffmpeg", lambda *args: state["ffmpeg"](*args))
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"source")
    state["source"] = source
    state["layout"] = ProjectLayout.for_project(AppPaths(data_dir=tmp_path), "demo")
    return state


def _ingest(state: dict[str, Any], cuda: bool = False) -> IngestedSource:
    tools = MediaTools(ffmpeg="ffmpeg", ffprobe="ffprobe")
    return ingest_source(state["layout"], state["source"], tools, cuda_available=cuda)


def test_ingest_is_one_ffmpeg_run(fake_media: dict[str, Any]) -> None:
    entry = _ingest(fake_media)

    assert len(fake_media["ffmpeg"].calls) == 1
    assert [path.name for path in fake_media["ffmpeg"].outputs] == [
        f"{entry.source_id}.mezzanine.part.mp4",
        f"{entry.source_id}.proxy.part.mp4",
        f"{entry.source_id}.part.wav",
    ]
    assert entry.video_decoder == "software"


def test_ingest_cache_key_includes_video_encoder(fake_media: dict[str, Any]) -> None:
    first = _ingest(fake_media)
    assert _ingest(fake_media) == first
    assert len(fake_media["ffmpeg"].calls) == 1

    fake_media["listing"] = NVENC_LISTING
    again = _ingest(fake_media, cuda=True)

    assert again.video_encoder == "h264_nvenc"
    assert len(fake_media["ffmpeg"].calls) == 2


def test_ingest_missing_or_corrupt_wav_is_a_cache_miss(fake_media: dict[str, Any]) -> None:
    entry = _ingest(fake_media)
    assert entry.wav_path is not None

    Path(entry.wav_path).unlink()
    _ingest(fake_media)
    assert len(fake_media["ffmpeg"].calls) == 2

    Path(entry.wav_path).write_bytes(b"not a wav file")
    _ingest(fake_media)
    assert len(fake_media["ffmpeg"].calls) == 3


def test_ingest_writes_outputs_atomically(fake_media: dict[str, Any]) -> None:
    fake_media["ffmpeg"] = FakeFfmpeg(fail_when="-i")

    with pytest.raises(FfmpegError):
        _ingest(fake_media)

    assert len(fake_media["ffmpeg"].outputs) == 3
    assert all(".part" in path.name for path in fake_media["ffmpeg"].outputs)
    media_dir: Path = fake_media["layout"].media_dir
    assert list(media_dir.iterdir()) == []
    assert (
        not fake_media["layout"]
        .cache_file(f"ingest-{source_id_for(fake_media['source'])}")
        .exists()
    )


def test_a_failed_gpu_decode_is_retried_in_software(fake_media: dict[str, Any]) -> None:
    fake_media["listing"] = LGPL_LISTING
    fake_media["hwaccel"] = "d3d11va"
    fake_media["ffmpeg"] = FakeFfmpeg(fail_when="-hwaccel")
    events: list[str] = []

    entry = ingest_source(
        fake_media["layout"],
        fake_media["source"],
        MediaTools(ffmpeg="ffmpeg", ffprobe="ffprobe"),
        cuda_available=False,
        progress=lambda stage, fraction, message: events.append(message),
    )

    assert (entry.video_decoder, entry.video_encoder) == ("software", MF_HARDWARE)
    assert ["-hwaccel" in call for call in fake_media["ffmpeg"].calls] == [True, False]
    assert events[0] == "preparing"
    assert "retrying in software" in events
    assert Path(entry.mezzanine_path).is_file()


def test_ingest_with_an_lgpl_ffmpeg_uses_media_foundation_for_both_files(
    fake_media: dict[str, Any],
) -> None:
    fake_media["listing"] = LGPL_LISTING
    fake_media["works"] = lambda encoder: encoder == "h264_mf"

    entry = _ingest(fake_media)

    assert entry.video_encoder == "h264_mf"
    (args,) = fake_media["ffmpeg"].calls
    assert [args[i + 1] for i, arg in enumerate(args) if arg == "-c:v"] == ["h264_mf", "h264_mf"]


def test_sources_ingest_two_at_a_time_inside_the_job_process_scope(
    fake_media: dict[str, Any], tmp_path: Path
) -> None:
    fake_media["listing"] = LGPL_LISTING
    sources = [tmp_path / f"clip{i}.mp4" for i in range(3)]
    for source in sources:
        source.write_bytes(source.name.encode())
    scope = ProcessScope()

    with process_scope(scope):
        manifest = ingest_files(
            fake_media["layout"],
            [*sources, sources[0]],
            MediaTools(ffmpeg="ffmpeg", ffprobe="ffprobe"),
            cuda_available=False,
        )

    assert [entry.source_id for entry in manifest.sources] == [source_id_for(s) for s in sources]
    assert len(fake_media["ffmpeg"].calls) == 3
    assert fake_media["ffmpeg"].scopes == [scope, scope, scope]


def _media_foundation_listed() -> bool:
    return FFMPEG is not None and "h264_mf" in list_encoders(FFMPEG)


@pytest.mark.ffmpeg
@needs_ffmpeg
def test_encoder_probe_rejects_an_encoder_ffmpeg_does_not_have() -> None:
    assert FFMPEG is not None
    assert encoder_works(FFMPEG, "powereditor_no_such_encoder") is False


@pytest.mark.ffmpeg
@needs_ffmpeg
@pytest.mark.skipif(sys.platform != "win32", reason="Media Foundation is Windows only")
@pytest.mark.parametrize("encoder", ["h264_mf", MF_HARDWARE])
def test_media_foundation_writes_high_profile_mezzanine_and_proxy(
    clips: dict[str, Path], tmp_path: Path, encoder: str
) -> None:
    if not _media_foundation_listed():
        pytest.skip("this ffmpeg has no h264_mf")
    assert FFMPEG is not None
    if not encoder_probe(FFMPEG)(encoder):
        pytest.skip(f"{encoder} cannot encode on this machine")
    mezzanine, proxy, wav = tmp_path / "m.mp4", tmp_path / "p.mp4", tmp_path / "a.wav"
    plan = IngestPlan(fps=24, width=320, height=240, encoder=encoder)

    run_ffmpeg(FFMPEG, ingest_args(clips["accented"], plan, mezzanine, proxy, wav))

    for path, size in ((mezzanine, (320, 240)), (proxy, (720, 540))):
        stream = _stream(path)
        assert (stream["codec_name"], stream["profile"]) == ("h264", "High")
        assert (stream["width"], stream["height"]) == size
        assert stream["format_duration"] == pytest.approx(2.0, abs=0.1)
