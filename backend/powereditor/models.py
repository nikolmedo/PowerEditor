import os
import tempfile
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator
from pydantic.alias_generators import to_camel

ProjectPreset = Literal["reel_9x16", "landscape_16x9"]
TransitionType = Literal["cut", "punch_in", "fade", "slide"]
AudioTrackKind = Literal["voice", "music", "sfx"]
SubtitlePreset = Literal[
    "karaoke_highlight",
    "clean",
    "bold_pop",
    "minimal",
    "pill_karaoke",
    "kinetic_slam",
    "emoji_pop",
    "editorial_emphasis",
]
SubtitlePosition = Literal["bottom", "center", "top"]
OverlayTemplateId = Literal[
    "title", "lower_third", "cta", "logo", "progress_bar", "image", "count_up", "progress_ring"
]
ColorPreset = Literal["natural", "warm", "cool", "bw"]
TranscriberProvider = Literal["local", "openai"]
DecisionEngineName = Literal["heuristic", "jev", "model"]


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


LOAD_CONTEXT = {"clamp_to_bounds": True}
"""Validation context of stored projects: values outside newer bounds are clamped, not refused."""


def _clamped(value: Any, info: ValidationInfo, low: float, high: float) -> Any:
    """Clamp a stored number into [low, high] when loading a project; new writes stay strict."""
    if not (info.context or {}).get("clamp_to_bounds"):
        return value
    if isinstance(value, int | float) and not isinstance(value, bool):
        return min(high, max(low, value))
    return value


def _clamp_grade_fields(value: Any, info: ValidationInfo) -> Any:
    low, high = (-1.0, 1.0) if info.field_name == "temperature" else (0.0, 2.0)
    return _clamped(value, info, low, high)


class ColorStats(CamelModel):
    mean_luma: float
    mean_r: float
    mean_g: float
    mean_b: float


class ColorCorrection(CamelModel):
    """Per-channel gains that match a source's color to the project, applied before the grade."""

    red_gain: float = Field(ge=0.5, le=2.0)
    green_gain: float = Field(ge=0.5, le=2.0)
    blue_gain: float = Field(ge=0.5, le=2.0)


class Source(CamelModel):
    id: str
    original_path: str
    mezzanine_path: str
    proxy_path: str
    display_color: str
    loudness_lufs: float
    color_stats: ColorStats
    color_correction: ColorCorrection | None = None
    """Automatic match to the other sources (None = unchanged), computed when the draft is built."""


class TransitionIn(CamelModel):
    type: TransitionType
    duration_frames: int = Field(ge=0)


class ColorGrade(CamelModel):
    """Brightness, contrast and saturation are factors (1 = unchanged); temperature runs from
    -1 (cool) to 1 (warm). The preset names the values it last set."""

    preset: ColorPreset
    brightness: float = Field(ge=0.0, le=2.0)
    contrast: float = Field(ge=0.0, le=2.0)
    saturation: float = Field(ge=0.0, le=2.0)
    temperature: float = Field(ge=-1.0, le=1.0)

    _clamp_on_load = field_validator(
        "brightness", "contrast", "saturation", "temperature", mode="before"
    )(_clamp_grade_fields)


class ColorGradeOverride(CamelModel):
    preset: ColorPreset | None = None
    brightness: float | None = Field(default=None, ge=0.0, le=2.0)
    contrast: float | None = Field(default=None, ge=0.0, le=2.0)
    saturation: float | None = Field(default=None, ge=0.0, le=2.0)
    temperature: float | None = Field(default=None, ge=-1.0, le=1.0)

    _clamp_on_load = field_validator(
        "brightness", "contrast", "saturation", "temperature", mode="before"
    )(_clamp_grade_fields)


class Clip(CamelModel):
    id: str
    source_id: str
    in_sec: float = Field(ge=0.0)
    out_sec: float = Field(ge=0.0)
    speed: float = Field(ge=0.5, le=2.0)
    volume: float = Field(ge=0.0, le=2.0)
    transition_in: TransitionIn
    take_group_id: str | None = None
    alternative_take_ids: list[str]
    decision_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    color_override: ColorGradeOverride | None = None
    removed: bool


class AudioTrack(CamelModel):
    id: str
    kind: AudioTrackKind
    source_path: str | None = None
    volume: float = Field(ge=0.0, le=2.0)
    ducking_enabled: bool
    ducking_db: float = Field(default=12.0, ge=0.0, le=30.0)
    """How far a ducked track drops under speech."""


class TimelineWord(CamelModel):
    text: str
    start_frame: int = Field(ge=0)
    end_frame: int = Field(ge=0)
    clip_id: str
    word_index: int | None = Field(default=None, ge=0)
    """Index of the word in `Subtitles.sourceWords[<clip's source>]`, for text edits."""


class SourceWord(CamelModel):
    """A transcribed word in source seconds; its text may have been edited."""

    text: str
    start: float = Field(ge=0.0)
    end: float = Field(ge=0.0)


class SubtitleStyle(CamelModel):
    preset: SubtitlePreset
    font_size: int = Field(gt=0)
    position: SubtitlePosition
    highlight_color: str
    max_words_per_line: int = Field(gt=0)


class Subtitles(CamelModel):
    style: SubtitleStyle
    words: list[TimelineWord]
    """Timeline words derived from `source_words` and the clips; rebuilt after every edit."""
    source_words: dict[str, list[SourceWord]] = Field(default_factory=dict)
    """Words per source id in source time, so edits never need a new transcription."""


class Overlay(CamelModel):
    id: str
    template_id: OverlayTemplateId
    start_frame: int = Field(ge=0)
    end_frame: int = Field(ge=0)
    props: dict[str, Any]
    auto_generated: bool


class Project(CamelModel):
    version: Literal[1]
    preset: ProjectPreset
    fps: int = Field(gt=0)
    sources: list[Source]
    clips: list[Clip]
    audio_tracks: list[AudioTrack]
    subtitles: Subtitles
    overlays: list[Overlay]
    color_grade: ColorGrade
    normalize_sources: bool = False
    """Bring every source to the same loudness before mixing (see `render.audio_mix`)."""


class Word(CamelModel):
    text: str
    start: float = Field(ge=0.0)
    end: float = Field(ge=0.0)
    prob: float | None = Field(default=None, ge=0.0, le=1.0)


class Transcript(CamelModel):
    language: str | None
    words: list[Word]
    provider: TranscriberProvider
    model: str


class Segment(CamelModel):
    id: str
    source_id: str
    start: float = Field(ge=0.0)
    end: float = Field(ge=0.0)
    text: str
    words: list[Word]


class Take(CamelModel):
    id: str
    segment_id: str
    source_id: str
    start: float = Field(ge=0.0)
    end: float = Field(ge=0.0)
    text: str


class TakeCluster(CamelModel):
    id: str
    take_ids: list[str]


class TakeFeatures(CamelModel):
    take_id: str
    completeness: float = Field(ge=0.0, le=1.0)
    filler_count: int = Field(ge=0)
    repetition_count: int = Field(ge=0)
    cut_off: bool
    speech_rate_wps: float = Field(ge=0.0)
    mean_word_prob: float | None = None
    loudness_lufs: float | None = None
    clipping: bool = False
    face_centered: float | None = None
    sharpness: float | None = None
    is_last_take: bool
    fluency: float | None = None
    """Model fluency score 0..1, set only when a model answers `fluency_score`."""


class ClusterDecision(CamelModel):
    cluster_id: str
    chosen_take_id: str
    confidence: float = Field(ge=0.0, le=1.0)
    engine: DecisionEngineName
    reason: str | None = None


class SegmentFlags(CamelModel):
    segment_id: str
    is_audience_content: bool
    is_complete: bool
    has_cta: bool
    confidence: float = Field(ge=0.0, le=1.0)


class SameTakeDecision(CamelModel):
    same: bool
    confidence: float = Field(ge=0.0, le=1.0)


class TransitionDecision(CamelModel):
    type: TransitionType
    topic_change: bool
    confidence: float = Field(ge=0.0, le=1.0)


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        tmp_path.replace(path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def parse_project(content: bytes | str) -> Project:
    """A stored `project.json`; files written before a bound existed load clamped into it."""
    return Project.model_validate_json(content, context=LOAD_CONTEXT)


def load_project(path: Path) -> Project:
    return parse_project(path.read_bytes())


def save_project(project: Project, path: Path) -> None:
    write_text_atomic(path, project.model_dump_json(by_alias=True, indent=2) + "\n")
