"""Score take clustering and take choice against a labelled benchmark."""

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from powereditor.config import REPO_ROOT
from powereditor.decide.base import DecisionEngine
from powereditor.decide.heuristic import HeuristicEngine
from powereditor.models import CamelModel, Segment, Word
from powereditor.pipeline.clustering import SimilarityModel, TextSimilarity
from powereditor.pipeline.takes import TakeSelection, select_takes

DEFAULT_BENCHMARK = REPO_ROOT / "backend" / "tests" / "fixtures" / "takes_benchmark.json"
SECONDS_PER_WORD = 0.35
GAP_SECONDS = 1.0


class BenchmarkSegment(CamelModel):
    text: str
    group: str | None = None
    best: bool = False
    off_take: bool = False


class BenchmarkScene(CamelModel):
    id: str
    language: str | None = None
    script: str | None = None
    segments: list[BenchmarkSegment]


class TakesBenchmark(CamelModel):
    synthetic: bool
    description: str
    scenes: list[BenchmarkScene]


@dataclass(frozen=True)
class TakesReport:
    synthetic: bool
    clusters: int
    clustering_accuracy: float
    best_take_accuracy: float
    off_take_accuracy: float
    threshold: float
    automatic_share: float
    automatic_accuracy: float


@dataclass
class _Tally:
    clusters: int = 0
    clustered: int = 0
    best: int = 0
    segments: int = 0
    off_take: int = 0
    automatic: int = 0
    automatic_correct: int = 0


def load_benchmark(path: Path = DEFAULT_BENCHMARK) -> TakesBenchmark:
    return TakesBenchmark.model_validate_json(path.read_bytes())


def scene_segments(scene: BenchmarkScene) -> list[Segment]:
    """Segments with evenly spaced words, as if read at a steady pace."""
    segments: list[Segment] = []
    cursor = 0.0
    for index, item in enumerate(scene.segments):
        texts = item.text.split()
        words = [
            Word(
                text=text,
                start=cursor + i * SECONDS_PER_WORD,
                end=cursor + (i + 1) * SECONDS_PER_WORD,
            )
            for i, text in enumerate(texts)
        ]
        segments.append(
            Segment(
                id=f"seg-{scene.id}-{index:04d}",
                source_id=scene.id,
                start=cursor,
                end=words[-1].end,
                text=item.text,
                words=words,
            )
        )
        cursor = words[-1].end + GAP_SECONDS
    return segments


def _score_scene(
    scene: BenchmarkScene,
    segments: list[Segment],
    selection: TakeSelection,
    threshold: float,
    tally: _Tally,
) -> None:
    gold: dict[str, set[str]] = defaultdict(set)
    best: dict[str, str] = {}
    for item, segment in zip(scene.segments, segments, strict=True):
        if item.group is not None:
            gold[item.group].add(segment.id)
            if item.best:
                best[item.group] = segment.id
    segment_of = {take.id: take.segment_id for take in selection.takes}
    predicted = {
        segment_of[take_id]: (cluster.id, {segment_of[t] for t in cluster.take_ids})
        for cluster in selection.clusters
        for take_id in cluster.take_ids
    }
    decisions = {decision.cluster_id: decision for decision in selection.decisions}
    for group, members in gold.items():
        if len(members) < 2:
            continue
        tally.clusters += 1
        cluster_id, predicted_members = predicted.get(best[group], ("", set()))
        tally.clustered += predicted_members == members
        decision = decisions.get(cluster_id)
        correct = decision is not None and segment_of[decision.chosen_take_id] == best[group]
        tally.best += correct
        if decision is not None and decision.confidence >= threshold:
            tally.automatic += 1
            tally.automatic_correct += correct
    for item, flag in zip(scene.segments, selection.flags, strict=True):
        tally.segments += 1
        tally.off_take += item.off_take == (not flag.is_audience_content)


def _ratio(part: int, whole: int) -> float:
    return part / whole if whole else 0.0


def evaluate_takes(
    benchmark: TakesBenchmark,
    *,
    engine: DecisionEngine | None = None,
    similarity: SimilarityModel | None = None,
    threshold: float = 0.6,
) -> TakesReport:
    """Clustering accuracy (exact groups), best-take accuracy and automatic-decision share.

    A decision is automatic when its confidence reaches `threshold`.
    """
    tally = _Tally()
    for scene in benchmark.scenes:
        segments = scene_segments(scene)
        selection = select_takes(
            segments,
            engine or HeuristicEngine(language=scene.language),
            similarity or TextSimilarity(scene.language),
            language=scene.language,
            script=scene.script,
        )
        _score_scene(scene, segments, selection, threshold, tally)
    return TakesReport(
        synthetic=benchmark.synthetic,
        clusters=tally.clusters,
        clustering_accuracy=_ratio(tally.clustered, tally.clusters),
        best_take_accuracy=_ratio(tally.best, tally.clusters),
        off_take_accuracy=_ratio(tally.off_take, tally.segments),
        threshold=threshold,
        automatic_share=_ratio(tally.automatic, tally.clusters),
        automatic_accuracy=_ratio(tally.automatic_correct, tally.automatic),
    )
