import json
import shutil
import subprocess
import sys
import wave
from pathlib import Path
from typing import Any

import pytest

from powereditor.paths import AppPaths
from powereditor.pipeline import ingest as ingest_module
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
    ProbeResult,
    ingest_files,
    ingest_source,
    mezzanine_args,
    parse_rate,
    probe_media,
    proxy_args,
    select_video_encoder,
    software_encoder,
    source_id_for,
    target_fps,
)
from powereditor.pipeline.runner import ProjectLayout

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
    ("listing", "cuda", "expected"),
    [
        (NVENC_LISTING, False, "libx264"),
        (NVENC_LISTING, True, "h264_nvenc"),
        (" V....D libx264  libx264 H.264\n", True, "libx264"),
        (LGPL_LISTING, False, "h264_mf"),
        (LGPL_LISTING, True, "h264_nvenc"),
        (OPENH264_ONLY_LISTING, False, "libopenh264"),
        (" V....D libx264  libx264 H.264\n" + LGPL_LISTING, False, "libx264"),
    ],
)
def test_select_video_encoder(listing: str, cuda: bool, expected: str) -> None:
    assert select_video_encoder(listing, cuda) == expected


def test_media_foundation_that_cannot_encode_falls_back_to_openh264() -> None:
    probed: list[str] = []

    def works(encoder: str) -> bool:
        probed.append(encoder)
        return encoder != "h264_mf"

    assert software_encoder(LGPL_LISTING, works) == "libopenh264"
    assert probed == ["h264_mf"]


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
    return {"accented": accented, "vfr": vfr, "rotated": rotated}


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
        [clips["accented"], clips["vfr"], clips["rotated"]],
        _tools(),
        cuda_available=False,
        progress=record,
    )

    assert len(manifest.sources) == 3
    accented, vfr, rotated = manifest.sources
    assert accented.fps == 24
    assert accented.video_encoder == "libx264"
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
    assert len(again.sources) == 3


class FakeFfmpeg:
    """Stands in for ffmpeg: writes the last argument as the output file."""

    def __init__(self, fail_on: str | None = None) -> None:
        self.outputs: list[Path] = []
        self.calls: list[list[str]] = []
        self.fail_on = fail_on

    def __call__(self, ffmpeg: str, args: list[str], *rest: object) -> None:
        self.calls.append(list(args))
        output = Path(args[-1])
        self.outputs.append(output)
        if output.suffix == ".wav":
            with wave.open(str(output), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(16000)
                handle.writeframes(b"\x00\x00" * 1600)
        else:
            output.write_bytes(b"video")
        if self.fail_on is not None and self.fail_on in output.name:
            raise FfmpegError("simulated crash")


@pytest.fixture
def fake_media(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    state: dict[str, Any] = {"listing": " V....D libx264  libx264 H.264\n", "ffmpeg": FakeFfmpeg()}
    monkeypatch.setattr(ingest_module, "probe_media", lambda ffprobe, path: _probe())
    monkeypatch.setattr(ingest_module, "list_encoders", lambda ffmpeg: state["listing"])
    monkeypatch.setattr(ingest_module, "encoder_works", lambda ffmpeg, encoder: True)
    monkeypatch.setattr(ingest_module, "run_ffmpeg", lambda *args: state["ffmpeg"](*args))
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"source")
    state["source"] = source
    state["layout"] = ProjectLayout.for_project(AppPaths(data_dir=tmp_path), "demo")
    return state


def _ingest(state: dict[str, Any], cuda: bool = False) -> IngestedSource:
    tools = MediaTools(ffmpeg="ffmpeg", ffprobe="ffprobe")
    return ingest_source(state["layout"], state["source"], tools, cuda_available=cuda)


def test_ingest_cache_key_includes_video_encoder(fake_media: dict[str, Any]) -> None:
    first = _ingest(fake_media)
    runs = len(fake_media["ffmpeg"].outputs)
    assert _ingest(fake_media) == first
    assert len(fake_media["ffmpeg"].outputs) == runs

    fake_media["listing"] = NVENC_LISTING
    again = _ingest(fake_media, cuda=True)

    assert again.video_encoder == "h264_nvenc"
    assert len(fake_media["ffmpeg"].outputs) == 2 * runs


def test_ingest_missing_or_corrupt_wav_is_a_cache_miss(fake_media: dict[str, Any]) -> None:
    entry = _ingest(fake_media)
    runs = len(fake_media["ffmpeg"].outputs)
    assert entry.wav_path is not None

    Path(entry.wav_path).unlink()
    _ingest(fake_media)
    assert len(fake_media["ffmpeg"].outputs) == 2 * runs

    Path(entry.wav_path).write_bytes(b"not a wav file")
    _ingest(fake_media)
    assert len(fake_media["ffmpeg"].outputs) == 3 * runs


def test_ingest_writes_outputs_atomically(fake_media: dict[str, Any]) -> None:
    fake_media["ffmpeg"] = FakeFfmpeg(fail_on="proxy")

    with pytest.raises(FfmpegError):
        _ingest(fake_media)

    written = fake_media["ffmpeg"].outputs
    assert all(".part" in path.name for path in written)
    media_dir: Path = fake_media["layout"].media_dir
    assert not any(path.name.endswith(".proxy.mp4") for path in media_dir.iterdir())
    assert not any(".part" in path.name for path in media_dir.iterdir())
    assert (
        not fake_media["layout"]
        .cache_file(f"ingest-{source_id_for(fake_media['source'])}")
        .exists()
    )


def test_an_lgpl_ffmpeg_encodes_with_openh264_at_a_fixed_bitrate(tmp_path: Path) -> None:
    source, out = tmp_path / "in.mov", tmp_path / "out.mp4"

    mezzanine = mezzanine_args(source, out, 30, "libopenh264")
    proxy = proxy_args(source, out, 30, encoder="libopenh264")
    default_proxy = proxy_args(source, out, 30)

    assert mezzanine[mezzanine.index("-c:v") + 1 :][:3] == ["libopenh264", "-b:v", "20M"]
    assert proxy[proxy.index("-c:v") + 1 :][:3] == ["libopenh264", "-b:v", "2M"]
    assert "-crf" not in mezzanine and "-crf" not in proxy
    assert default_proxy[default_proxy.index("-c:v") + 1] == "libx264"


def test_media_foundation_encodes_at_a_fixed_bitrate_with_the_high_profile(tmp_path: Path) -> None:
    source, out = tmp_path / "in.mov", tmp_path / "out.mp4"

    mezzanine = mezzanine_args(source, out, 30, "h264_mf")
    proxy = proxy_args(source, out, 30, encoder="h264_mf")

    codec = ["h264_mf", "-rate_control", "u_vbr", "-b:v", "20M", "-profile:v", "100"]
    assert mezzanine[mezzanine.index("-c:v") + 1 :][:7] == codec
    assert proxy[proxy.index("-c:v") + 1 :][:5] == [
        "h264_mf",
        "-rate_control",
        "u_vbr",
        "-b:v",
        "2M",
    ]
    assert "-crf" not in mezzanine and "-crf" not in proxy


def test_ingest_with_an_lgpl_ffmpeg_uses_media_foundation_for_both_files(
    fake_media: dict[str, Any],
) -> None:
    fake_media["listing"] = LGPL_LISTING

    entry = _ingest(fake_media)

    assert entry.video_encoder == "h264_mf"
    codecs = [args[args.index("-c:v") + 1] for args in fake_media["ffmpeg"].calls if "-c:v" in args]
    assert codecs == ["h264_mf", "h264_mf"]


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
def test_media_foundation_writes_high_profile_mezzanine_and_proxy(
    clips: dict[str, Path], tmp_path: Path
) -> None:
    if not _media_foundation_listed():
        pytest.skip("this ffmpeg has no h264_mf")
    assert FFMPEG is not None
    assert encoder_works(FFMPEG, "h264_mf") is True
    mezzanine, proxy = tmp_path / "m.mp4", tmp_path / "p.mp4"

    run_ffmpeg(FFMPEG, mezzanine_args(clips["accented"], mezzanine, 24, "h264_mf"))
    run_ffmpeg(FFMPEG, proxy_args(clips["accented"], proxy, 24, "h264_mf"))

    for path, height in ((mezzanine, 240), (proxy, 540)):
        stream = _stream(path)
        assert (stream["codec_name"], stream["profile"], stream["height"]) == (
            "h264",
            "High",
            height,
        )
        assert stream["format_duration"] == pytest.approx(2.0, abs=0.1)
