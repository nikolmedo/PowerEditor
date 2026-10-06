"""Full analysis: ingest, transcribe, VAD, segmentation, loudness/color, takes, draft."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from powereditor.decide.base import DecisionEngine
from powereditor.decide.factory import create_engine
from powereditor.decide.model_engine import ModelUsageReport
from powereditor.models import Project, ProjectPreset, Transcript, write_text_atomic
from powereditor.pipeline.clustering import create_similarity
from powereditor.pipeline.color_stats import measure_color
from powereditor.pipeline.draft_builder import DraftSource, build_draft, write_draft
from powereditor.pipeline.ffmpeg import MediaTools
from powereditor.pipeline.ingest import (
    IngestedSource,
    ingest_files,
    load_manifest,
    source_id_for,
)
from powereditor.pipeline.loudness import measure_loudness
from powereditor.pipeline.runner import ProgressCallback, ProjectLayout, no_progress
from powereditor.pipeline.segmentation import segment_source
from powereditor.pipeline.takes import TakeSelection, select_project_takes
from powereditor.pipeline.transcription import transcribe_project
from powereditor.pipeline.vad import Range, SileroDetector, SpeechDetector, detect_voice
from powereditor.pipeline.visual import create_visual_extractor
from powereditor.settings_store import SettingsService, UserSettings
from powereditor.transcribe.base import Transcriber
from powereditor.transcribe.factory import create_transcriber


@dataclass(frozen=True)
class AnalyzeResult:
    project: Project
    project_path: Path
    original_seconds: float
    kept_seconds: float
    takes: TakeSelection
    model_usage: ModelUsageReport | None = None
    """Model calls made by this run; None when the takes came from the cache or no
    feature uses a model."""


MODEL_USAGE_FILE = "model_usage.json"


def record_model_usage(layout: ProjectLayout, engine: DecisionEngine) -> ModelUsageReport | None:
    """Write `cache/model_usage.json` when this run called a model; a cache hit keeps the
    previous report."""
    usage_report = getattr(engine, "usage_report", None)
    if usage_report is None:
        return None
    report: ModelUsageReport = usage_report()
    if not report.calls:
        return None
    write_text_atomic(
        layout.cache_dir / MODEL_USAGE_FILE,
        report.model_dump_json(by_alias=True, indent=2) + "\n",
    )
    return report


def _select_sources(
    layout: ProjectLayout,
    files: Sequence[Path],
    tools: MediaTools,
    service: SettingsService,
    progress: ProgressCallback,
) -> list[IngestedSource]:
    if not files:
        return load_manifest(layout).sources
    manifest = ingest_files(
        layout, files, tools, cuda_available=service.cuda_available(), progress=progress
    )
    by_id = {entry.source_id: entry for entry in manifest.sources}
    return [by_id[source_id] for source_id in dict.fromkeys(map(source_id_for, files))]


def _analyze_source(
    layout: ProjectLayout,
    entry: IngestedSource,
    transcript: Transcript | None,
    tools: MediaTools,
    padding_ms: int,
    detector: SpeechDetector,
    progress: ProgressCallback,
) -> DraftSource:
    wav = Path(entry.wav_path) if entry.wav_path else None
    words = transcript.words if transcript else []
    if wav is None:
        speech: list[Range] = [(0.0, entry.probe.duration)]
        duration = entry.probe.duration
    else:
        vad = detect_voice(
            layout,
            entry.source_id,
            wav,
            padding_ms=padding_ms,
            detector=detector,
            progress=progress,
        )
        speech = [(r.start, r.end) for r in vad.speech]
        duration = vad.duration
    segments = segment_source(layout, entry.source_id, words, speech, duration, progress=progress)
    return DraftSource(
        ingested=entry,
        segments=segments,
        words=list(words),
        loudness_lufs=measure_loudness(layout, entry.source_id, wav, tools.ffmpeg, progress),
        color_stats=measure_color(
            layout,
            entry.source_id,
            Path(entry.proxy_path),
            entry.probe.duration,
            tools.ffmpeg,
            progress,
        ),
    )


def _select_takes(
    layout: ProjectLayout,
    drafts: Sequence[DraftSource],
    settings: UserSettings,
    engine: DecisionEngine,
    script: str | None,
    progress: ProgressCallback,
) -> TakeSelection:
    segments = [
        segment
        for draft in drafts
        for segment in sorted(draft.segments, key=lambda segment: segment.start)
    ]
    sources = [draft.ingested for draft in drafts]
    return select_project_takes(
        layout,
        segments,
        engine,
        create_similarity(settings.take_similarity, settings.language),
        language=settings.language,
        script=script,
        wav_paths={s.source_id: Path(s.wav_path) for s in sources if s.wav_path},
        visual=create_visual_extractor({s.source_id: Path(s.proxy_path) for s in sources}),
        progress=progress,
    )


def _cta_segments(takes: TakeSelection) -> set[str]:
    return {flag.segment_id for flag in takes.flags if flag.has_cta}


def analyze_project(
    layout: ProjectLayout,
    service: SettingsService,
    *,
    files: Sequence[Path] = (),
    transcriber: Transcriber | None = None,
    detector: SpeechDetector | None = None,
    preset: ProjectPreset | None = None,
    engine: DecisionEngine | None = None,
    script: str | None = None,
    language: str | None = None,
    progress: ProgressCallback = no_progress,
) -> AnalyzeResult:
    """Ingest `files` (or reuse every ingested source) and write a draft `project.json`.

    `language` overrides the language setting for this project. Every stage is cached,
    so re-running only recomputes what changed.
    """
    settings = service.get_effective()
    if language is not None:
        settings = settings.model_copy(update={"language": language})
    tools = MediaTools.from_settings(service)
    layout.ensure()
    entries = _select_sources(layout, files, tools, service, progress)
    if not entries:
        raise ValueError(f"project {layout.project_id!r} has no sources to analyze")
    transcripts: dict[str, Transcript] = {}
    if any(entry.wav_path for entry in entries):
        transcripts = transcribe_project(
            layout,
            transcriber or create_transcriber(service),
            settings.language,
            progress,
            sources=entries,
        )
    drafts = [
        _analyze_source(
            layout,
            entry,
            transcripts.get(entry.source_id),
            tools,
            settings.silence_padding_ms,
            detector or SileroDetector(),
            progress,
        )
        for entry in entries
    ]
    engine = engine or create_engine(service)
    takes = _select_takes(layout, drafts, settings, engine, script, progress)
    model_usage = record_model_usage(layout, engine)
    progress("draft", 0.0, "building")
    project = build_draft(
        drafts,
        padding_s=settings.silence_padding_ms / 1000,
        preset=preset,
        entries=takes.entries,
        cta_segment_ids=_cta_segments(takes) if settings.auto_cta else (),
        language=settings.language,
    )
    path = write_draft(layout, project)
    progress("draft", 1.0, "done")
    kept = sum((c.out_sec - c.in_sec) / c.speed for c in project.clips if not c.removed)
    return AnalyzeResult(
        project=project,
        project_path=path,
        original_seconds=sum(entry.probe.duration for entry in entries),
        kept_seconds=kept,
        takes=takes,
        model_usage=model_usage,
    )
