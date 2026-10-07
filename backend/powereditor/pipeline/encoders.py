"""Which H.264 encoder and which hardware decoder ingest uses on this machine.

Hardware encoders come first, each confirmed by a one-frame encode, because a listed
encoder can still fail (no GPU, no driver, Windows N editions). Media Foundation has two
entries: `h264_mf_hw` asks for the GPU's encoder (it only takes NV12 frames) and plain
`h264_mf` is Microsoft's software encoder.
"""

import threading
from collections.abc import Callable
from pathlib import Path

from powereditor.pipeline.ffmpeg import encoder_works, hwaccel_decodes

EncoderCheck = Callable[[str], bool]
DecoderCheck = Callable[[str], bool]

MF_HARDWARE = "h264_mf_hw"
HARDWARE_ENCODERS = ("h264_nvenc", "h264_qsv", "h264_amf", MF_HARDWARE)
HWACCEL = "d3d11va"
"""Direct3D 11 video decoding: every Windows GPU driver with video decode offers it."""
GPU_DECODED_CODECS = frozenset({"hevc", "av1", "vp9"})


def _always_works(encoder: str) -> bool:
    return True


def _listed_encoders(encoders_listing: str) -> set[str]:
    return {line.split()[1] for line in encoders_listing.splitlines() if len(line.split()) > 1}


def _ffmpeg_encoder(encoder: str) -> str:
    return "h264_mf" if encoder == MF_HARDWARE else encoder


def is_hardware(encoder: str) -> bool:
    return encoder in HARDWARE_ENCODERS


def input_pix_fmt(encoder: str) -> str:
    """The frame format the encoder is fed: the Media Foundation GPU encoder needs NV12."""
    return "nv12" if is_hardware(encoder) else "yuv420p"


def video_codec_args(encoder: str, *, bitrate: str, crf: int, preset: str) -> list[str]:
    """`-c:v` and its options. Every encoder but libx264 and NVENC encodes at `bitrate`."""
    if encoder == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", str(crf + 1)]
    if encoder in ("h264_qsv", "h264_amf"):
        return ["-c:v", encoder, "-profile:v", "high", "-b:v", bitrate]
    if encoder in ("h264_mf", MF_HARDWARE):
        hardware = ["-hw_encoding", "1"] if encoder == MF_HARDWARE else []
        # Media Foundation takes the profile as a number: 100 is High.
        rate = ["-rate_control", "u_vbr", "-b:v", bitrate, "-profile:v", "100"]
        return ["-c:v", "h264_mf", *hardware, *rate]
    if encoder == "libopenh264":
        return ["-c:v", "libopenh264", "-b:v", bitrate, "-profile:v", "high"]
    return ["-c:v", "libx264", "-preset", preset, "-crf", str(crf)]


def software_encoder(encoders_listing: str, works: EncoderCheck = _always_works) -> str:
    """libx264 when the build has it (developer machines). The LGPL build the app downloads
    has none: Windows' own Media Foundation encoder comes next, OpenH264 last."""
    listed = _listed_encoders(encoders_listing)
    if "libx264" in listed:
        return "libx264"
    if "h264_mf" in listed and works("h264_mf"):
        return "h264_mf"
    return "libopenh264" if "libopenh264" in listed else "libx264"


def select_video_encoder(
    encoders_listing: str, cuda_available: bool, works: EncoderCheck = _always_works
) -> str:
    """The first hardware encoder that is listed and encodes a frame, else software.

    NVENC is only tried with CUDA present, as before hardware probing existed.
    """
    listed = _listed_encoders(encoders_listing)
    for encoder in HARDWARE_ENCODERS:
        if encoder == "h264_nvenc" and not cuda_available:
            continue
        if _ffmpeg_encoder(encoder) in listed and works(encoder):
            return encoder
    return software_encoder(encoders_listing, works)


def encoder_probe(ffmpeg: str) -> EncoderCheck:
    """Check an encoder with the options and frame format ingest will give it."""

    def works(encoder: str) -> bool:
        options = video_codec_args(encoder, bitrate="2M", crf=28, preset="veryfast")[2:]
        return encoder_works(
            ffmpeg, _ffmpeg_encoder(encoder), tuple(options), input_pix_fmt(encoder)
        )

    return works


def select_hwaccel(
    hwaccels_listing: str, platform: str, codec: str, decodes: DecoderCheck
) -> str | None:
    """D3D11VA on Windows for codecs that are expensive in software, when this ffmpeg has it
    and it decodes the source on the GPU. H.264 decodes faster on the CPU: downloading GPU
    frames costs more than it saves."""
    methods = {line.strip() for line in hwaccels_listing.splitlines()}
    if platform != "win32" or codec not in GPU_DECODED_CODECS or HWACCEL not in methods:
        return None
    return HWACCEL if decodes(HWACCEL) else None


_decoder_results: dict[tuple[str, str, tuple[str, ...]], bool] = {}
_decoder_lock = threading.Lock()


def decoder_probe(ffmpeg: str, source: Path, codec: tuple[str, ...]) -> DecoderCheck:
    """Probe hardware decoding with `source` once per `codec` (name, profile, pixel format)."""

    def decodes(hwaccel: str) -> bool:
        key = (ffmpeg, hwaccel, codec)
        with _decoder_lock:
            if key not in _decoder_results:
                _decoder_results[key] = hwaccel_decodes(ffmpeg, hwaccel, source)
            return _decoder_results[key]

    return decodes
