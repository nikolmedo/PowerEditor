import contextvars
import hashlib
import json
import logging
import os
import sys
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from pydantic import Field, ValidationError

from powereditor.models import CamelModel, write_text_atomic
from powereditor.pipeline.encoders import (
    decoder_probe,
    encoder_probe,
    input_pix_fmt,
    is_hardware,
    select_hwaccel,
    select_video_encoder,
    software_encoder,
    video_codec_args,
)
from powereditor.pipeline.ffmpeg import (
    FfmpegError,
    MediaTools,
    list_encoders,
    list_hwaccels,
    run_capture,
    run_ffmpeg,
)
from powereditor.pipeline.runner import ProgressCallback, ProjectLayout, no_progress, run_stage
from powereditor.transcribe.base import audio_duration

logger = logging.getLogger(__name__)

INGEST_STAGE_VERSION = 3
MANIFEST_STAGE = "ingest"
STANDARD_FPS = (24, 25, 30, 50, 60)
VFR_TOLERANCE = 0.01
COPY_FPS_TOLERANCE = 0.001
"""Frames per second a copied stream may differ from the target: 23.976 is not 24."""
MEZZANINE_SHORT_SIDE = 1080
MEZZANINE_LONG_SIDE = 1920
"""The largest render (1080x1920 or 1920x1080 at scale 1): a bigger mezzanine only costs time."""
PROXY_SHORT_SIDE = 540
PROXY_GOP = 12
WAV_SAMPLE_RATE = 16000
MEZZANINE_CRF = 18
MEZZANINE_BITRATE = "20M"
PROXY_CRF = 28
PROXY_BITRATE = "2M"
HARDWARE_PARALLELISM = 2
"""Sources ingested at once with a hardware encoder; a software encode already uses every core."""
COPYABLE_PROFILES = frozenset({"Constrained Baseline", "Baseline", "Main", "High"})


class ProbeResult(CamelModel):
    duration: float = Field(ge=0.0)
    width: int
    height: int
    rotation: int
    r_frame_rate: float
    avg_frame_rate: float
    has_audio: bool
    video_codec: str
    audio_codec: str | None
    pix_fmt: str = "unknown"
    profile: str = "unknown"
    color_range: str = "unknown"

    @property
    def is_vfr(self) -> bool:
        if self.r_frame_rate <= 0 or self.avg_frame_rate <= 0:
            return False
        return abs(self.r_frame_rate - self.avg_frame_rate) > VFR_TOLERANCE * self.r_frame_rate

    @property
    def display_width(self) -> int:
        return self.height if abs(self.rotation) % 180 == 90 else self.width

    @property
    def display_height(self) -> int:
        return self.width if abs(self.rotation) % 180 == 90 else self.height


class IngestedSource(CamelModel):
    source_id: str
    original_path: str
    probe: ProbeResult
    fps: int
    video_encoder: str
    video_decoder: str = "software"
    """`d3d11va` when the GPU decoded the source, `copy` when the video stream was copied."""
    mezzanine_path: str
    proxy_path: str
    wav_path: str | None


class IngestManifest(CamelModel):
    sources: list[IngestedSource]


def parse_rate(raw: str) -> float:
    numerator, _, denominator = raw.partition("/")
    try:
        num = float(numerator)
        den = float(denominator) if denominator else 1.0
    except ValueError:
        return 0.0
    return num / den if den else 0.0


def _rotation(stream: dict[str, Any]) -> int:
    for side_data in stream.get("side_data_list", []):
        if "rotation" in side_data:
            return int(side_data["rotation"])
    rotate = stream.get("tags", {}).get("rotate")
    return int(rotate) if rotate else 0


def parse_probe(data: dict[str, Any]) -> ProbeResult:
    streams: list[dict[str, Any]] = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise ValueError("no video stream found")
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = data.get("format", {}).get("duration") or video.get("duration") or 0.0
    return ProbeResult(
        duration=float(duration),
        width=int(video["width"]),
        height=int(video["height"]),
        rotation=_rotation(video),
        r_frame_rate=parse_rate(video.get("r_frame_rate", "0/0")),
        avg_frame_rate=parse_rate(video.get("avg_frame_rate", "0/0")),
        has_audio=audio is not None,
        video_codec=str(video.get("codec_name", "unknown")),
        audio_codec=str(audio.get("codec_name")) if audio else None,
        pix_fmt=str(video.get("pix_fmt", "unknown")),
        profile=str(video.get("profile", "unknown")),
        color_range=str(video.get("color_range", "unknown")),
    )


def probe_media(ffprobe: str, path: Path) -> ProbeResult:
    flags = ["-v", "error", "-print_format", "json", "-show_format", "-show_streams"]
    output = run_capture([ffprobe, *flags, str(path)])
    return parse_probe(json.loads(output))


class InvalidAudioError(ValueError):
    """A readable file that is not usable audio; the message is fit for the user."""

    code = "invalid_music"


def probe_audio_duration(ffprobe: str, path: Path) -> float:
    """Length in seconds of a file with an audio stream.

    Raises InvalidAudioError, with a message fit for the user (it never names `path`, which
    may be a temporary file), when the file has no audio stream or no length. Any other
    failure (unreadable probe output) surfaces as a plain ValueError or FfmpegError.
    """
    flags = ["-v", "error", "-print_format", "json", "-show_format", "-show_streams"]
    data: dict[str, Any] = json.loads(run_capture([ffprobe, *flags, str(path)]))
    streams: list[dict[str, Any]] = data.get("streams", [])
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    if audio is None:
        raise InvalidAudioError("The file has no audio stream.")
    duration = float(data.get("format", {}).get("duration") or audio.get("duration") or 0.0)
    if duration <= 0:
        raise InvalidAudioError("The audio has no length.")
    return duration


def target_fps(probe: ProbeResult) -> int:
    rate = probe.avg_frame_rate or probe.r_frame_rate
    return min(STANDARD_FPS, key=lambda candidate: abs(candidate - rate))


def source_id_for(path: Path) -> str:
    normalized = os.path.normcase(str(path.resolve()))
    return "src-" + hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:10]


def _even(value: float) -> int:
    return max(2, round(value / 2) * 2)


def mezzanine_size(probe: ProbeResult) -> tuple[int, int]:
    """Display size scaled down to fit the largest render, keeping the aspect ratio."""
    width, height = probe.display_width, probe.display_height
    factor = min(
        1.0, MEZZANINE_SHORT_SIDE / min(width, height), MEZZANINE_LONG_SIDE / max(width, height)
    )
    if factor == 1.0:
        return width, height
    return _even(width * factor), _even(height * factor)


def proxy_size(width: int, height: int) -> tuple[int, int]:
    factor = PROXY_SHORT_SIDE / min(width, height)
    return _even(width * factor), _even(height * factor)


def can_copy_video(probe: ProbeResult, fps: int) -> bool:
    """Whether the source's video stream already is a valid mezzanine: 8-bit 4:2:0 H.264 in
    TV range, constant `fps`, upright and no larger than the mezzanine."""
    return (
        probe.video_codec == "h264"
        and probe.pix_fmt == "yuv420p"
        and probe.profile in COPYABLE_PROFILES
        and probe.color_range != "pc"
        and not probe.is_vfr
        and abs(probe.avg_frame_rate - fps) <= COPY_FPS_TOLERANCE
        and probe.rotation == 0
        and mezzanine_size(probe) == (probe.width, probe.height)
    )


@dataclass(frozen=True)
class IngestPlan:
    fps: int
    width: int
    height: int
    """Mezzanine size, after rotation."""
    encoder: str
    hwaccel: str | None = None
    copy_video: bool = False
    has_audio: bool = True

    @property
    def decoder(self) -> str:
        return "copy" if self.copy_video else (self.hwaccel or "software")


def _audio_args(bitrate: str) -> list[str]:
    return ["-c:a", "aac", "-b:a", bitrate, "-ar", "48000"]


def _filter_graph(plan: IngestPlan) -> str:
    pix_fmt = input_pix_fmt(plan.encoder)
    proxy_width, proxy_height = proxy_size(plan.width, plan.height)
    proxy_scale = f"scale={proxy_width}:{proxy_height}"
    if plan.copy_video:
        return f"[0:v]fps={plan.fps},{proxy_scale}:out_range=tv,format={pix_fmt}[p]"
    mezzanine = f"fps={plan.fps},scale={plan.width}:{plan.height}:out_range=tv,format={pix_fmt}"
    return f"[0:v]{mezzanine},split=2[m][p0];[p0]{proxy_scale}[p]"


def ingest_args(
    source: Path, plan: IngestPlan, mezzanine: Path, proxy: Path, wav: Path
) -> list[str]:
    """One ffmpeg run: a single decode feeds the mezzanine, the proxy and the WAV.

    The `fps` filter makes both videos constant frame rate; `out_range=tv` maps full-range
    phone video (yuvj420p) to the TV range every player expects.
    """
    audio_map = ["-map", "0:a:0"] if plan.has_audio else []
    if plan.copy_video:
        mezzanine_video = ["-map", "0:v:0", "-c:v", "copy"]
    else:
        codec = video_codec_args(
            plan.encoder, bitrate=MEZZANINE_BITRATE, crf=MEZZANINE_CRF, preset="medium"
        )
        mezzanine_video = ["-map", "[m]", *codec]
    proxy_codec = video_codec_args(
        plan.encoder, bitrate=PROXY_BITRATE, crf=PROXY_CRF, preset="veryfast"
    )
    gop = ["-g", str(PROXY_GOP), "-keyint_min", str(PROXY_GOP), "-sc_threshold", "0"]
    args = ["-hwaccel", plan.hwaccel] if plan.hwaccel else []
    args += [
        "-i", str(source),
        "-filter_complex", _filter_graph(plan),
        *mezzanine_video, *audio_map, *(_audio_args("192k") if plan.has_audio else []),
        "-movflags", "+faststart", str(mezzanine),
        "-map", "[p]", *audio_map, *proxy_codec, *gop,
        *(_audio_args("96k") if plan.has_audio else []),
        "-movflags", "+faststart", str(proxy),
    ]  # fmt: skip
    if plan.has_audio:
        args += [
            "-map", "0:a:0", "-vn",
            "-ac", "1", "-ar", str(WAV_SAMPLE_RATE), "-c:a", "pcm_s16le",
            str(wav),
        ]  # fmt: skip
    return args


def fallback_plans(plan: IngestPlan, software: str) -> list[IngestPlan]:
    """`plan`, then software decoding, then a software encoder: a GPU can fail mid-file."""
    candidates = [plan, replace(plan, hwaccel=None), replace(plan, hwaccel=None, encoder=software)]
    return list(dict.fromkeys(candidates))


def ingest_parallelism(encoder: str, *, sources: int) -> int:
    limit = HARDWARE_PARALLELISM if is_hardware(encoder) else 1
    return max(1, min(limit, sources))


def _partial(path: Path) -> Path:
    return path.with_name(f"{path.stem}.part{path.suffix}")


def _run_atomic(
    ffmpeg: str,
    args: list[str],
    outputs: list[Path],
    duration: float,
    on_progress: Callable[[float], None],
) -> None:
    """Run ffmpeg writing every output under its `.part` name; rename them all only when
    ffmpeg succeeds."""
    partials = [_partial(path) for path in outputs]
    try:
        run_ffmpeg(ffmpeg, args, duration, on_progress)
        for partial, output in zip(partials, outputs, strict=True):
            partial.replace(output)
    finally:
        for partial in partials:
            partial.unlink(missing_ok=True)


def _ingest_outputs(entry: "IngestedSource") -> list[Path]:
    paths = [Path(entry.mezzanine_path), Path(entry.proxy_path)]
    return paths + ([Path(entry.wav_path)] if entry.wav_path else [])


def _wav_readable(entry: "IngestedSource") -> bool:
    return entry.wav_path is None or bool(audio_duration(Path(entry.wav_path)))


def choose_encoder(ffmpeg: str, cuda_available: bool) -> str:
    return select_video_encoder(list_encoders(ffmpeg), cuda_available, encoder_probe(ffmpeg))


def plan_ingest(
    ffmpeg: str,
    source: Path,
    probe: ProbeResult,
    encoder: str,
    fps: int | None = None,
    platform: str = sys.platform,
) -> IngestPlan:
    chosen_fps = fps or target_fps(probe)
    width, height = mezzanine_size(probe)
    codec = (probe.video_codec, probe.profile, probe.pix_fmt)
    decodes = decoder_probe(ffmpeg, source, codec)
    return IngestPlan(
        fps=chosen_fps,
        width=width,
        height=height,
        encoder=encoder,
        hwaccel=select_hwaccel(list_hwaccels(ffmpeg), platform, probe.video_codec, decodes),
        copy_video=can_copy_video(probe, chosen_fps),
        has_audio=probe.has_audio,
    )


def _encode_with_fallback(
    ffmpeg: str,
    source: Path,
    plan: IngestPlan,
    software: str,
    outputs: tuple[Path, Path, Path],
    duration: float,
    report: Callable[[float, str], None],
) -> IngestPlan:
    """Run `plan`, falling back to software decoding and encoding; return the plan that ran."""
    mezzanine, proxy, wav = outputs
    written = [mezzanine, proxy, *([wav] if plan.has_audio else [])]
    attempts = fallback_plans(plan, software)
    for attempt in attempts:
        args = ingest_args(source, attempt, _partial(mezzanine), _partial(proxy), _partial(wav))
        try:
            _run_atomic(ffmpeg, args, written, duration, lambda f: report(f, "encoding"))
            return attempt
        except FfmpegError as exc:
            if attempt is attempts[-1]:
                raise
            logger.warning(
                "Ingest of %s with %s decoding and %s failed, retrying in software: %s",
                source.name,
                attempt.decoder,
                attempt.encoder,
                exc,
            )
            report(0.0, "retrying in software")
    raise AssertionError("fallback_plans is never empty")


def ingest_source(
    layout: ProjectLayout,
    source: Path,
    tools: MediaTools,
    *,
    cuda_available: bool,
    fps: int | None = None,
    progress: ProgressCallback = no_progress,
) -> IngestedSource:
    source_id = source_id_for(source)
    stage = f"ingest-{source_id}"
    progress(stage, 0.0, "preparing")
    media = layout.media_dir
    outputs = (
        media / f"{source_id}.mezzanine.mp4",
        media / f"{source_id}.proxy.mp4",
        media / f"{source_id}.wav",
    )
    encoder = choose_encoder(tools.ffmpeg, cuda_available)
    software = software_encoder(list_encoders(tools.ffmpeg), encoder_probe(tools.ffmpeg))

    def report(fraction: float, message: str) -> None:
        progress(stage, fraction, message)

    def compute() -> IngestedSource:
        layout.ensure()
        probe = probe_media(tools.ffprobe, source)
        plan = plan_ingest(tools.ffmpeg, source, probe, encoder, fps)
        used = _encode_with_fallback(
            tools.ffmpeg, source, plan, software, outputs, probe.duration, report
        )
        return IngestedSource(
            source_id=source_id,
            original_path=str(source.resolve()),
            probe=probe,
            fps=used.fps,
            video_encoder=used.encoder,
            video_decoder=used.decoder,
            mezzanine_path=str(outputs[0]),
            proxy_path=str(outputs[1]),
            wav_path=str(outputs[2]) if used.has_audio else None,
        )

    params = {
        "fps": fps,
        "videoEncoder": encoder,
        "mezzanineMaxSize": [MEZZANINE_SHORT_SIDE, MEZZANINE_LONG_SIDE],
        "mezzanineVideoArgs": video_codec_args(
            encoder, bitrate=MEZZANINE_BITRATE, crf=MEZZANINE_CRF, preset="medium"
        ),
        "proxyVideoArgs": video_codec_args(
            encoder, bitrate=PROXY_BITRATE, crf=PROXY_CRF, preset="veryfast"
        ),
    }
    return run_stage(
        layout,
        stage,
        INGEST_STAGE_VERSION,
        [source],
        params,
        IngestedSource,
        compute,
        outputs=_ingest_outputs,
        validate=_wav_readable,
        progress=progress,
    )


def load_manifest(layout: ProjectLayout) -> IngestManifest:
    path = layout.cache_file(MANIFEST_STAGE)
    if not path.is_file():
        return IngestManifest(sources=[])
    try:
        return IngestManifest.model_validate_json(path.read_bytes())
    except (OSError, ValidationError) as exc:
        logger.warning("Ignoring unreadable ingest manifest %s: %s", path, exc)
        return IngestManifest(sources=[])


def ingest_files(
    layout: ProjectLayout,
    sources: Sequence[Path],
    tools: MediaTools,
    *,
    cuda_available: bool,
    fps: int | None = None,
    progress: ProgressCallback = no_progress,
) -> IngestManifest:
    """Ingest `sources`, two at a time with a hardware encoder (GPUs encode several streams)."""
    layout.ensure()
    by_id = {entry.source_id: entry for entry in load_manifest(layout).sources}
    unique = list({source_id_for(source): source for source in sources}.values())

    def ingest_one(source: Path) -> IngestedSource:
        return ingest_source(
            layout, source, tools, cuda_available=cuda_available, fps=fps, progress=progress
        )

    for source in unique:  # the encoder probes below take a moment on a first run
        progress(f"ingest-{source_id_for(source)}", 0.0, "preparing")
    workers = ingest_parallelism(choose_encoder(tools.ffmpeg, cuda_available), sources=len(unique))
    if workers == 1:
        entries = [ingest_one(source) for source in unique]
    else:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ingest") as pool:
            # Each worker runs in a copy of this context so a job cancel still reaches the
            # ffmpeg processes it starts (the process scope is a context variable).
            futures = [
                pool.submit(contextvars.copy_context().run, ingest_one, source) for source in unique
            ]
            try:
                entries = [future.result() for future in futures]
            except BaseException:
                pool.shutdown(cancel_futures=True)
                raise
    for entry in entries:
        by_id[entry.source_id] = entry
    manifest = IngestManifest(sources=list(by_id.values()))
    write_text_atomic(
        layout.cache_file(MANIFEST_STAGE), manifest.model_dump_json(by_alias=True, indent=2) + "\n"
    )
    return manifest
