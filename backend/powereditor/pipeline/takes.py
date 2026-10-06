"""Take selection: classify segments, cluster retakes, score them and order the draft."""

from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path

from pydantic import Field

from powereditor.decide.base import DecisionEngine
from powereditor.models import (
    CamelModel,
    ClusterDecision,
    Segment,
    SegmentFlags,
    Take,
    TakeCluster,
    TakeFeatures,
    TransitionType,
)
from powereditor.pipeline.clustering import ClusterParams, SimilarityModel, cluster_takes
from powereditor.pipeline.features import AudioClip, cluster_features, script_lines
from powereditor.pipeline.runner import ProgressCallback, ProjectLayout, no_progress, run_stage
from powereditor.pipeline.vad import read_wav
from powereditor.pipeline.visual import NullVisualExtractor, VisualFeatureExtractor

TAKES_STAGE = "takes"
TAKES_STAGE_VERSION = 2


class TakeEntry(CamelModel):
    """One segment's place in the draft timeline."""

    segment_id: str
    take_group_id: str | None = None
    removed: bool
    decision_confidence: float | None = None
    alternative_segment_ids: list[str] = Field(default_factory=list)
    transition: TransitionType = "cut"


class TakeSelection(CamelModel):
    """Everything the takes stage decided; cached as `cache/takes.json`."""

    takes: list[Take]
    clusters: list[TakeCluster]
    features: list[TakeFeatures]
    decisions: list[ClusterDecision]
    flags: list[SegmentFlags]
    entries: list[TakeEntry]


def _suffix(segment_id: str) -> str:
    return segment_id.removeprefix("seg-")


def take_for(segment: Segment) -> Take:
    return Take(
        id=f"take-{_suffix(segment.id)}",
        segment_id=segment.id,
        source_id=segment.source_id,
        start=segment.start,
        end=segment.end,
        text=segment.text,
    )


def _group_entries(
    group: list[Take], decision: ClusterDecision | None, cluster_id: str
) -> list[TakeEntry]:
    if decision is None:
        return [TakeEntry(segment_id=group[0].segment_id, removed=False)]
    chosen = next(take for take in group if take.id == decision.chosen_take_id)
    return [
        TakeEntry(
            segment_id=take.segment_id,
            take_group_id=cluster_id,
            removed=take is not chosen,
            decision_confidence=decision.confidence if take is chosen else None,
            alternative_segment_ids=(
                [other.segment_id for other in group if other is not chosen]
                if take is chosen
                else []
            ),
        )
        for take in group
    ]


def _pauses_before(segments: Sequence[Segment]) -> dict[str, float]:
    """Silence recorded right before each segment, after whatever its source said last."""
    pauses: dict[str, float] = {}
    previous_end: dict[str, float] = {}
    for segment in sorted(segments, key=lambda s: (s.source_id, s.start)):
        if segment.source_id in previous_end:
            pauses[segment.id] = max(segment.start - previous_end[segment.source_id], 0.0)
        previous_end[segment.source_id] = segment.end
    return pauses


def _with_transitions(
    entries: list[TakeEntry], segments: Sequence[Segment], engine: DecisionEngine
) -> list[TakeEntry]:
    """A topic change gets the engine's transition; the cuts inside a block alternate
    between a plain cut and a punch-in, so the zoom toggles at every cut."""
    by_id = {segment.id: segment for segment in segments}
    pauses = _pauses_before(segments)
    previous: Segment | None = None
    zoomed = False
    result: list[TakeEntry] = []
    for entry in entries:
        segment = by_id[entry.segment_id]
        if not entry.removed and previous is not None:
            pause = pauses.get(segment.id) if segment.source_id == previous.source_id else None
            decision = engine.transition_between(previous, segment, pause)
            if decision.topic_change:
                transition, zoomed = decision.type, False
            else:
                zoomed = not zoomed
                transition = "punch_in" if zoomed else "cut"
            entry = entry.model_copy(update={"transition": transition})
        if not entry.removed:
            previous = segment
        result.append(entry)
    return result


def select_takes(
    segments: Sequence[Segment],
    engine: DecisionEngine,
    similarity: SimilarityModel,
    *,
    language: str | None,
    params: ClusterParams | None = None,
    script: str | None = None,
    audio: Mapping[str, AudioClip] | None = None,
    visual: VisualFeatureExtractor | None = None,
) -> TakeSelection:
    """Decide takes for `segments` given in recording order (sources in project order).

    Out-of-take remarks become removed entries. Each retake group sits where its first
    take was recorded, with every take but the chosen one removed, so the group stays
    restorable and the script order is kept.
    """
    flags = [engine.classify_segment(segment) for segment in segments]
    remarks = {flag.segment_id for flag in flags if not flag.is_audience_content}
    takes = [take_for(segment) for segment in segments if segment.id not in remarks]
    groups = cluster_takes(takes, similarity, engine, params)
    words = {take_for(segment).id: segment.words for segment in segments}
    lines = script_lines(script) if script else []
    first_take = {group[0].segment_id: group for group in groups}

    clusters: list[TakeCluster] = []
    all_features: list[TakeFeatures] = []
    decisions: list[ClusterDecision] = []
    entries: list[TakeEntry] = []
    for segment in segments:
        if segment.id in remarks:
            entries.append(TakeEntry(segment_id=segment.id, removed=True))
            continue
        group = first_take.get(segment.id)
        if group is None:
            continue
        cluster = TakeCluster(id=f"grp-{_suffix(segment.id)}", take_ids=[take.id for take in group])
        features = cluster_features(
            group, language=language, script=lines, words=words, audio=audio, visual=visual
        )
        decision = None
        if len(group) > 1:
            decision = engine.decide_cluster(cluster, group, features)
            decisions.append(decision)
        clusters.append(cluster)
        all_features.extend(features)
        entries.extend(_group_entries(group, decision, cluster.id))
    return TakeSelection(
        takes=takes,
        clusters=clusters,
        features=all_features,
        decisions=decisions,
        flags=flags,
        entries=_with_transitions(entries, segments, engine),
    )


def select_project_takes(
    layout: ProjectLayout,
    segments: Sequence[Segment],
    engine: DecisionEngine,
    similarity: SimilarityModel,
    *,
    language: str | None,
    params: ClusterParams | None = None,
    script: str | None = None,
    wav_paths: Mapping[str, Path] | None = None,
    visual: VisualFeatureExtractor | None = None,
    progress: ProgressCallback = no_progress,
) -> TakeSelection:
    """Cached `takes` stage over every source's segments."""
    wav_paths = dict(wav_paths or {})
    visual = visual or NullVisualExtractor()
    params = params or ClusterParams()

    def compute() -> TakeSelection:
        audio = {}
        for source_id, path in wav_paths.items():
            samples, rate = read_wav(path)
            audio[source_id] = AudioClip(samples=samples, rate=rate)
        return select_takes(
            segments,
            engine,
            similarity,
            language=language,
            params=params,
            script=script,
            audio=audio,
            visual=visual,
        )

    stage_params = {
        "segments": [segment.model_dump(mode="json") for segment in segments],
        "engine": {"name": engine.name, **engine.fingerprint()},
        "similarity": similarity.name,
        "visual": visual.name,
        "cluster": asdict(params),
        "language": language,
        "script": script,
    }
    return run_stage(
        layout,
        TAKES_STAGE,
        TAKES_STAGE_VERSION,
        list(wav_paths.values()),
        stage_params,
        TakeSelection,
        compute,
        progress=progress,
    )
