"""Deterministic decision engine: the default and the fallback for every AI feature."""

import re
from collections.abc import Mapping
from typing import Any

from powereditor.models import (
    ClusterDecision,
    DecisionEngineName,
    SameTakeDecision,
    Segment,
    SegmentFlags,
    Take,
    TakeCluster,
    TakeFeatures,
    TransitionDecision,
)
from powereditor.pipeline.take_text import looks_cut_off, tokens
from powereditor.settings_store import TakeWeights

SAME_TAKE_THRESHOLD = 0.7
# Distance from the threshold at which a grey-zone answer counts as certain.
SAME_TAKE_CERTAIN_DISTANCE = 0.1
# Score margin between the best and the runner-up take that maps to confidence 1.0.
CONFIDENCE_MARGIN = 1.5
TARGET_SPEECH_RATE_WPS = 2.7
MAX_COUNTED_DEFECTS = 5
REMARK_MAX_WORDS = 6

# Matched against accent-free, lowercase, punctuation-free text.
_REMARK = re.compile(
    r"\b(corta|corten|cortamos|otra vez|de nuevo|desde el principio|estas? grabando"
    r"|me equivoque|perdon|cut|again|one more time|from the top"
    r"|(is it|are we|are you) recording|sorry|take two)\b"
)
_CTA = re.compile(
    r"\b(suscribi\w*|suscribe\w*|dale like|deja\w* tu like|link en la bio|seguime|sigueme"
    r"|activa la campanita|subscribe|follow (me|us)|link in (the )?bio|hit the bell)\b"
)


def _rate_score(rate_wps: float) -> float:
    """1.0 at a natural speaking rate, falling linearly to 0 at double or zero speed."""
    return 1.0 - min(abs(rate_wps - TARGET_SPEECH_RATE_WPS) / TARGET_SPEECH_RATE_WPS, 1.0)


def take_score(features: TakeFeatures, weights: TakeWeights) -> float:
    """Weighted take score; optional features that are unknown add nothing."""
    score = weights.completeness * features.completeness
    score -= weights.fillers * min(features.filler_count, MAX_COUNTED_DEFECTS)
    score -= weights.repetitions * min(features.repetition_count, MAX_COUNTED_DEFECTS)
    score -= weights.cut_off * features.cut_off
    score += weights.speech_rate * _rate_score(features.speech_rate_wps)
    score -= weights.clipping * features.clipping
    score += weights.last_take * features.is_last_take
    optional = (
        (weights.word_prob, features.mean_word_prob),
        (weights.face_centered, features.face_centered),
        (weights.sharpness, features.sharpness),
        (weights.fluency, features.fluency),
    )
    score += sum(weight * value for weight, value in optional if value is not None)
    return score


class HeuristicEngine:
    def __init__(self, weights: TakeWeights | None = None, language: str | None = None) -> None:
        self.weights = weights or TakeWeights()
        self.language = language

    @property
    def name(self) -> DecisionEngineName:
        return "heuristic"

    def fingerprint(self) -> Mapping[str, Any]:
        return {
            "weights": self.weights.model_dump(mode="json", by_alias=True),
            "language": self.language,
        }

    def same_take(self, first: Take, second: Take, similarity: float) -> SameTakeDecision:
        distance = abs(similarity - SAME_TAKE_THRESHOLD)
        return SameTakeDecision(
            same=similarity >= SAME_TAKE_THRESHOLD,
            confidence=min(distance / SAME_TAKE_CERTAIN_DISTANCE, 1.0),
        )

    def decide_cluster(
        self, cluster: TakeCluster, takes: list[Take], features: list[TakeFeatures]
    ) -> ClusterDecision:
        scored = sorted(
            ((take_score(f, self.weights), f.take_id) for f in features),
            key=lambda pair: pair[0],
            reverse=True,
        )
        best_score, best_id = scored[0]
        if len(scored) == 1:
            return ClusterDecision(
                cluster_id=cluster.id, chosen_take_id=best_id, confidence=1.0, engine=self.name
            )
        runner_up = scored[1][0]
        return ClusterDecision(
            cluster_id=cluster.id,
            chosen_take_id=best_id,
            confidence=min((best_score - runner_up) / CONFIDENCE_MARGIN, 1.0),
            engine=self.name,
            reason=f"score {best_score:.2f} vs runner-up {runner_up:.2f}",
        )

    def classify_segment(self, segment: Segment) -> SegmentFlags:
        words = tokens(segment.text)
        plain = " ".join(words)
        mentions_remark = _REMARK.search(plain) is not None
        is_remark = mentions_remark and len(words) <= REMARK_MAX_WORDS
        # A trigger word inside a long sentence is weak evidence either way.
        confidence = 0.9 if is_remark else 0.6 if mentions_remark else 0.8
        return SegmentFlags(
            segment_id=segment.id,
            is_audience_content=not is_remark,
            is_complete=not looks_cut_off(segment.text, self.language),
            has_cta=_CTA.search(plain) is not None,
            confidence=confidence,
        )

    def transition_between(self, prev: Segment, next: Segment) -> TransitionDecision:
        # Topic-change detection lands with Phase 5; until then every cut is a plain cut.
        return TransitionDecision(type="cut", topic_change=False, confidence=0.5)
