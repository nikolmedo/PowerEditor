from pathlib import Path

import pytest

from powereditor.pipeline import encoders
from powereditor.pipeline.encoders import (
    MF_HARDWARE,
    input_pix_fmt,
    is_hardware,
    select_hwaccel,
    select_video_encoder,
    video_codec_args,
)

LGPL_LISTING = (
    " V....D libopenh264  OpenH264 H.264\n V....D h264_mf  H264 via MediaFoundation\n"
    " V....D h264_nvenc  NVIDIA NVENC H.264 encoder\n V..... h264_qsv  Intel QSV\n"
    " V....D h264_amf  AMD AMF H.264 Encoder\n"
)
HWACCELS = "Hardware acceleration methods:\ncuda\ndxva2\nqsv\nd3d11va\n"


def _only(*working: str) -> encoders.EncoderCheck:
    def works(encoder: str) -> bool:
        return encoder in working

    return works


@pytest.mark.parametrize(
    ("working", "cuda", "expected"),
    [
        (("h264_nvenc", "h264_qsv", MF_HARDWARE, "h264_mf"), True, "h264_nvenc"),
        (("h264_nvenc", "h264_qsv", MF_HARDWARE, "h264_mf"), False, "h264_qsv"),
        (("h264_amf", MF_HARDWARE, "h264_mf"), False, "h264_amf"),
        ((MF_HARDWARE, "h264_mf"), False, MF_HARDWARE),
        (("h264_mf",), False, "h264_mf"),
        ((), False, "libopenh264"),
    ],
)
def test_hardware_encoders_that_work_come_before_software(
    working: tuple[str, ...], cuda: bool, expected: str
) -> None:
    assert select_video_encoder(LGPL_LISTING, cuda, _only(*working)) == expected


def test_an_unlisted_hardware_encoder_is_never_probed() -> None:
    probed: list[str] = []

    def works(encoder: str) -> bool:
        probed.append(encoder)
        return False

    assert select_video_encoder(" V....D libx264  libx264 H.264\n", True, works) == "libx264"
    assert probed == []


def test_hardware_media_foundation_takes_nv12_and_the_hardware_flag() -> None:
    args = video_codec_args(MF_HARDWARE, bitrate="20M", crf=18, preset="medium")

    assert args[:4] == ["-c:v", "h264_mf", "-hw_encoding", "1"]
    assert args[args.index("-profile:v") + 1] == "100"
    assert args[args.index("-b:v") + 1] == "20M"
    assert input_pix_fmt(MF_HARDWARE) == "nv12"
    assert input_pix_fmt("h264_mf") == "yuv420p"
    assert input_pix_fmt("libx264") == "yuv420p"
    assert is_hardware(MF_HARDWARE) and is_hardware("h264_qsv")
    assert not is_hardware("h264_mf") and not is_hardware("libopenh264")


@pytest.mark.parametrize(
    ("encoder", "expected"),
    [
        (
            "h264_mf",
            ["-c:v", "h264_mf", "-rate_control", "u_vbr", "-b:v", "20M", "-profile:v", "100"],
        ),
        ("libopenh264", ["-c:v", "libopenh264", "-b:v", "20M", "-profile:v", "high"]),
        ("libx264", ["-c:v", "libx264", "-preset", "medium", "-crf", "18"]),
    ],
)
def test_software_encoders_keep_their_rate_control(encoder: str, expected: list[str]) -> None:
    assert video_codec_args(encoder, bitrate="20M", crf=18, preset="medium") == expected


@pytest.mark.parametrize("encoder", ["h264_qsv", "h264_amf"])
def test_vendor_encoders_use_the_high_profile_at_the_target_bitrate(encoder: str) -> None:
    args = video_codec_args(encoder, bitrate="2M", crf=28, preset="veryfast")

    assert args[:2] == ["-c:v", encoder]
    assert args[args.index("-profile:v") + 1] == "high"
    assert args[args.index("-b:v") + 1] == "2M"


def test_encoder_probe_feeds_each_encoder_its_own_pixel_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, tuple[str, ...], str]] = []

    def fake_works(ffmpeg: str, encoder: str, options: tuple[str, ...], pix_fmt: str) -> bool:
        calls.append((encoder, options, pix_fmt))
        return True

    monkeypatch.setattr(encoders, "encoder_works", fake_works)
    works = encoders.encoder_probe("ffmpeg")

    assert works(MF_HARDWARE) and works("libopenh264")
    assert calls[0][0] == "h264_mf"
    assert calls[0][1][:2] == ("-hw_encoding", "1")
    assert calls[0][2] == "nv12"
    assert calls[1][0] == "libopenh264"
    assert calls[1][2] == "yuv420p"


def test_hwaccel_is_used_on_windows_only_when_a_probe_decodes_the_source() -> None:
    assert select_hwaccel(HWACCELS, "win32", "hevc", lambda method: True) == "d3d11va"
    assert select_hwaccel(HWACCELS, "win32", "hevc", lambda method: False) is None
    assert select_hwaccel(HWACCELS, "linux", "hevc", lambda method: True) is None
    no_d3d11 = "Hardware acceleration methods:\ncuda\n"
    assert select_hwaccel(no_d3d11, "win32", "hevc", lambda method: True) is None


def test_cheap_codecs_decode_on_the_cpu_without_probing_the_gpu() -> None:
    probed: list[str] = []

    def decodes(method: str) -> bool:
        probed.append(method)
        return True

    assert select_hwaccel(HWACCELS, "win32", "h264", decodes) is None
    assert select_hwaccel(HWACCELS, "win32", "av1", decodes) == "d3d11va"
    assert probed == ["d3d11va"]


def test_decoder_probe_runs_once_per_codec(monkeypatch: pytest.MonkeyPatch) -> None:
    probed: list[Path] = []

    def fake_decodes(ffmpeg: str, hwaccel: str, source: Path) -> bool:
        probed.append(source)
        return True

    monkeypatch.setattr(encoders, "hwaccel_decodes", fake_decodes)
    monkeypatch.setattr(encoders, "_decoder_results", {})

    first = encoders.decoder_probe("ffmpeg", Path("a.mp4"), ("hevc", "Main", "yuvj420p"))
    second = encoders.decoder_probe("ffmpeg", Path("b.mp4"), ("hevc", "Main", "yuvj420p"))
    other = encoders.decoder_probe("ffmpeg", Path("c.mp4"), ("h264", "High", "yuv420p"))

    assert first("d3d11va") and second("d3d11va") and other("d3d11va")
    assert probed == [Path("a.mp4"), Path("c.mp4")]
