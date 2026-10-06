import hashlib
import json
import logging
import os
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from pydantic import Field, ValidationError

from powereditor.models import CamelModel, write_text_atomic
from powereditor.pipeline.ffmpeg import MediaTools, list_encoders, run_capture, run_ffmpeg
from powereditor.pipeline.runner import ProgressCallback, ProjectLayout, no_progress, run_stage
from powereditor.transcribe.base import audio_duration

logger = logging.getLogger(__name__)

INGEST_STAGE_VERSION = 2
MANIFEST_STAGE = "ingest"
STANDARD_FPS = (24, 25, 30, 50, 60)
VFR_TOLERANCE = 0.01
PROXY_SHORT_SIDE = 540
PROXY_GOP = 12
WAV_SAMPLE_RATE = 16000
MEZZANINE_CRF = 18
PROXY_CRF = 28

_MEZZANINE_SHARE = 0.6
_PROXY_SHARE = 0.3


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
    )


def probe_media(ffprobe: str, path: Path) -> ProbeResult:
    flags = ["-v", "error", "-print_format", "json", "-show_format", "-show_streams"]
    output = run_capture([ffprobe, *flags, str(path)])
    return parse_probe(json.loads(output))


def probe_audio_duration(ffprobe: str, path: Path) -> float:
    """Length in seconds of a file with an audio stream.

    Raises ValueError, with a message fit for the user (it never names `path`, which may be
    a temporary file), when the file has no audio stream or no length.
    """
    flags = ["-v", "error", "-print_format", "json", "-show_format", "-show_streams"]
    data: dict[str, Any] = json.loads(run_capture([ffprobe, *flags, str(path)]))
    streams: list[dict[str, Any]] = data.get("streams", [])
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    if audio is None:
        raise ValueError("The file has no audio stream.")
    duration = float(data.get("format", {}).get("duration") or audio.get("duration") or 0.0)
    if duration <= 0:
        raise ValueError("The audio has no length.")
    return duration


def select_video_encoder(encoders_listing: str, cuda_available: bool) -> str:
    listed = {line.split()[1] for line in encoders_listing.splitlines() if len(line.split()) > 1}
    return "h264_nvenc" if cuda_available and "h264_nvenc" in listed else "libx264"


def target_fps(probe: ProbeResult) -> int:
    rate = probe.avg_frame_rate or probe.r_frame_rate
    return min(STANDARD_FPS, key=lambda candidate: abs(candidate - rate))


def source_id_for(path: Path) -> str:
    normalized = os.path.normcase(str(path.resolve()))
    return "src-" + hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:10]


def _video_codec_args(encoder: str, crf: int, preset: str) -> list[str]:
    if encoder == "h264_nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", str(crf + 1)]
    return ["-c:v", "libx264", "-preset", preset, "-crf", str(crf)]


def _audio_args(bitrate: str) -> list[str]:
    return ["-c:a", "aac", "-b:a", bitrate, "-ar", "48000"]


def mezzanine_args(source: Path, output: Path, fps: int, encoder: str) -> list[str]:
    return [
        "-i", str(source),
        "-map", "0:v:0", "-map", "0:a:0?",
        *_video_codec_args(encoder, MEZZANINE_CRF, "medium"),
        "-r", str(fps), "-fps_mode", "cfr", "-pix_fmt", "yuv420p",
        *_audio_args("192k"),
        "-movflags", "+faststart",
        str(output),
    ]  # fmt: skip


def proxy_args(source: Path, output: Path, fps: int) -> list[str]:
    short = PROXY_SHORT_SIDE
    scale = f"scale='if(gt(iw,ih),-2,{short})':'if(gt(iw,ih),{short},-2)'"
    return [
        "-i", str(source),
        "-map", "0:v:0", "-map", "0:a:0?",
        "-vf", scale,
        *_video_codec_args("libx264", PROXY_CRF, "veryfast"),
        "-g", str(PROXY_GOP), "-keyint_min", str(PROXY_GOP), "-sc_threshold", "0",
        "-r", str(fps), "-fps_mode", "cfr", "-pix_fmt", "yuv420p",
        *_audio_args("96k"),
        "-movflags", "+faststart",
        str(output),
    ]  # fmt: skip


def wav_args(source: Path, output: Path) -> list[str]:
    return [
        "-i", str(source),
        "-map", "0:a:0", "-vn",
        "-ac", "1", "-ar", str(WAV_SAMPLE_RATE), "-c:a", "pcm_s16le",
        str(output),
    ]  # fmt: skip


def _scaled(progress: ProgressCallback, stage: str, start: float, share: float, label: str) -> Any:
    def report(fraction: float) -> None:
        progress(stage, start + share * fraction, label)

    return report


def _partial(path: Path) -> Path:
    return path.with_name(f"{path.stem}.part{path.suffix}")


def _encode_atomic(
    ffmpeg: str,
    build_args: Callable[[Path], list[str]],
    output: Path,
    duration: float,
    on_progress: Callable[[float], None],
) -> None:
    partial = _partial(output)
    try:
        run_ffmpeg(ffmpeg, build_args(partial), duration, on_progress)
        partial.replace(output)
    finally:
        partial.unlink(missing_ok=True)


def _ingest_outputs(entry: "IngestedSource") -> list[Path]:
    paths = [Path(entry.mezzanine_path), Path(entry.proxy_path)]
    return paths + ([Path(entry.wav_path)] if entry.wav_path else [])


def _wav_readable(entry: "IngestedSource") -> bool:
    return entry.wav_path is None or bool(audio_duration(Path(entry.wav_path)))


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
    media = layout.media_dir
    mezzanine = media / f"{source_id}.mezzanine.mp4"
    proxy = media / f"{source_id}.proxy.mp4"
    wav = media / f"{source_id}.wav"

    encoder = select_video_encoder(list_encoders(tools.ffmpeg), cuda_available)

    def compute() -> IngestedSource:
        layout.ensure()
        probe = probe_media(tools.ffprobe, source)
        chosen_fps = fps or target_fps(probe)
        _encode_atomic(
            tools.ffmpeg,
            lambda out: mezzanine_args(source, out, chosen_fps, encoder),
            mezzanine,
            probe.duration,
            _scaled(progress, stage, 0.0, _MEZZANINE_SHARE, "mezzanine"),
        )
        _encode_atomic(
            tools.ffmpeg,
            lambda out: proxy_args(source, out, chosen_fps),
            proxy,
            probe.duration,
            _scaled(progress, stage, _MEZZANINE_SHARE, _PROXY_SHARE, "proxy"),
        )
        wav_path: str | None = None
        if probe.has_audio:
            start = _MEZZANINE_SHARE + _PROXY_SHARE
            _encode_atomic(
                tools.ffmpeg,
                lambda out: wav_args(source, out),
                wav,
                probe.duration,
                _scaled(progress, stage, start, 1.0 - start, "audio"),
            )
            wav_path = str(wav)
        return IngestedSource(
            source_id=source_id,
            original_path=str(source.resolve()),
            probe=probe,
            fps=chosen_fps,
            video_encoder=encoder,
            mezzanine_path=str(mezzanine),
            proxy_path=str(proxy),
            wav_path=wav_path,
        )

    params = {
        "fps": fps,
        "videoEncoder": encoder,
        "mezzanineVideoArgs": _video_codec_args(encoder, MEZZANINE_CRF, "medium"),
        "proxyVideoArgs": _video_codec_args("libx264", PROXY_CRF, "veryfast"),
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
    layout.ensure()
    by_id = {entry.source_id: entry for entry in load_manifest(layout).sources}
    for source in sources:
        entry = ingest_source(
            layout, source, tools, cuda_available=cuda_available, fps=fps, progress=progress
        )
        by_id[entry.source_id] = entry
    manifest = IngestManifest(sources=list(by_id.values()))
    write_text_atomic(
        layout.cache_file(MANIFEST_STAGE), manifest.model_dump_json(by_alias=True, indent=2) + "\n"
    )
    return manifest
