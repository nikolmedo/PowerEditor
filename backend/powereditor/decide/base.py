"""The decision engine contract.

Each method is one independent AI feature with plain Pydantic inputs and outputs, so a
Phase 4 engine can answer some of them with a model and delegate the rest to the
heuristic engine.
"""

from collections.abc import Mapping
from typing import Any, Protocol

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


class DecisionEngine(Protocol):
    @property
    def name(self) -> DecisionEngineName: ...

    def fingerprint(self) -> Mapping[str, Any]:
        """Everything that changes this engine's answers; part of the stage cache key."""
        ...

    def same_take(self, first: Take, second: Take, similarity: float) -> SameTakeDecision:
        """Grey zone only: are `first` and `second` attempts at the same line?"""
        ...

    def decide_cluster(
        self, cluster: TakeCluster, takes: list[Take], features: list[TakeFeatures]
    ) -> ClusterDecision:
        """Pick the best take; `takes` and `features` follow `cluster.take_ids`."""
        ...

    def classify_segment(self, segment: Segment) -> SegmentFlags: ...

    def transition_between(
        self, prev: Segment, next: Segment, pause_s: float | None = None
    ) -> TransitionDecision:
        """Topic change between consecutive kept segments; `pause_s` is the silence recorded
        right before `next` (None when unknown, for example across source files)."""
        ...
