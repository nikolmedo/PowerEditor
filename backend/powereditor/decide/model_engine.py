"""Model-backed decisions, routed per feature with the heuristic engine as fallback.

Each AI feature (see `providers.config.FeatureId`) may be assigned its own provider and
model. Unassigned features, failed calls and answers below `min_confidence` use the
heuristic answer; the last two also lower the decision's confidence so the UI flags it
for review. The best take is asked twice with the takes in reversed order and only
accepted when both answers pick the same take. All weighing stays in code: model scores
enter `take_score` next to the deterministic features.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import Field

from powereditor.decide.heuristic import HeuristicEngine, topic_transition
from powereditor.decide.prompts import (
    BEST_TAKE_ID,
    MAX_CHOICE_TAKES,
    PROMPT_VERSIONS,
    SAME_LINE,
    SEGMENT_PROMPTS,
    SEGMENT_TEXT,
    TAKE_PROMPTS,
    TOPIC_CHANGE,
    FeaturePrompt,
    best_take_question,
    take_labels,
)
from powereditor.models import (
    CamelModel,
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
from powereditor.providers.base import ModelProvider, ProviderError, TokenUsage, Transport
from powereditor.providers.config import FeatureId
from powereditor.providers.questions import (
    Answer,
    ChoiceAnswer,
    NoulAnswer,
    Question,
    ScoreAnswer,
    ask_questions,
    state_key,
)

logger = logging.getLogger(__name__)

_SEGMENT_FIELDS: dict[FeatureId, str] = {
    "off_take_detection": "is_audience_content",
    "idea_completeness": "is_complete",
    "cta_detection": "has_cta",
}


@dataclass(frozen=True)
class FeatureRoute:
    """The provider and model that answer one feature."""

    provider_id: str
    kind: str
    transport: Transport
    model: str
    provider: ModelProvider

    def fingerprint(self, feature: FeatureId) -> dict[str, Any]:
        return {
            "provider": self.provider_id,
            "kind": self.kind,
            "transport": self.transport,
            "model": self.model,
            "prompt": PROMPT_VERSIONS[feature],
        }


class FeatureUsage(CamelModel):
    provider_id: str
    model: str
    calls: int = 0
    failures: int = 0
    fallbacks: int = 0
    """Answers not applied (failed call or below the minimum confidence)."""
    input_tokens: int = 0
    output_tokens: int = 0


class ModelUsageReport(CamelModel):
    """Per-feature model use of one takes computation; written to `cache/model_usage.json`.
    Tokens of a call that answered several features are split evenly between them."""

    features: dict[FeatureId, FeatureUsage] = Field(default_factory=dict)

    @property
    def calls(self) -> int:
        return sum(usage.calls for usage in self.features.values())


def _confidence(answer: Answer | None) -> float:
    return 0.0 if answer is None else answer.confidence


class ModelDecisionEngine:
    def __init__(
        self,
        fallback: HeuristicEngine,
        routes: Mapping[FeatureId, FeatureRoute],
        min_confidence: float,
    ) -> None:
        self._fallback = fallback
        self._routes = dict(routes)
        self._min_confidence = min_confidence
        # None records a bad output, so the same question and state is not asked again.
        self._memo: dict[tuple[str, str, str, str], Answer | None] = {}
        self._disabled: set[str] = set()
        self._usage = {
            feature: FeatureUsage(provider_id=route.provider_id, model=route.model)
            for feature, route in self._routes.items()
        }

    @property
    def name(self) -> DecisionEngineName:
        return "model"

    def fingerprint(self) -> Mapping[str, Any]:
        return {
            "fallback": dict(self._fallback.fingerprint()),
            "minConfidence": self._min_confidence,
            "features": {
                feature: route.fingerprint(feature)
                for feature, route in sorted(self._routes.items())
            },
        }

    def usage_report(self) -> ModelUsageReport:
        return ModelUsageReport(
            features={feature: usage.model_copy() for feature, usage in self._usage.items()}
        )

    # --- features -------------------------------------------------------------------

    def classify_segment(self, segment: Segment) -> SegmentFlags:
        base = self._fallback.classify_segment(segment)
        routed = [feature for feature in SEGMENT_PROMPTS if feature in self._routes]
        if not routed:
            return base
        answers = self._ask({SEGMENT_TEXT: segment.text}, {f: SEGMENT_PROMPTS[f] for f in routed})
        values: dict[str, Any] = {}
        confidences = [] if "off_take_detection" in self._routes else [base.confidence]
        for feature in routed:
            answer = answers[feature]
            if isinstance(answer, NoulAnswer) and self._accepts(feature, answer):
                values[_SEGMENT_FIELDS[feature]] = answer.value
                confidences.append(answer.confidence)
            else:
                confidences.append(min(base.confidence, _confidence(answer)))
        return base.model_copy(update={**values, "confidence": min(confidences)})

    def same_take(self, first: Take, second: Take, similarity: float) -> SameTakeDecision:
        base = self._fallback.same_take(first, second, similarity)
        feature: FeatureId = "same_take_grey_zone"
        if feature not in self._routes:
            return base
        state = {"first_text": first.text, "second_text": second.text}
        answer = self._ask(state, {feature: SAME_LINE})[feature]
        if isinstance(answer, NoulAnswer) and self._accepts(feature, answer):
            return SameTakeDecision(same=answer.value, confidence=answer.confidence)
        return base.model_copy(update={"confidence": min(base.confidence, _confidence(answer))})

    def transition_between(
        self, prev: Segment, next: Segment, pause_s: float | None = None
    ) -> TransitionDecision:
        base = self._fallback.transition_between(prev, next, pause_s)
        feature: FeatureId = "topic_change"
        if feature not in self._routes:
            return base
        state = {"previous_segment": prev.text, "next_segment": next.text}
        answer = self._ask(state, {feature: TOPIC_CHANGE})[feature]
        if isinstance(answer, NoulAnswer) and self._accepts(feature, answer):
            return TransitionDecision(
                type=topic_transition(prev, next) if answer.value else "cut",
                topic_change=answer.value,
                confidence=answer.confidence,
            )
        return base.model_copy(update={"confidence": min(base.confidence, _confidence(answer))})

    def decide_cluster(
        self, cluster: TakeCluster, takes: list[Take], features: list[TakeFeatures]
    ) -> ClusterDecision:
        enriched = [
            self._with_model_scores(take, f) for take, f in zip(takes, features, strict=True)
        ]
        scored = self._fallback.decide_cluster(cluster, takes, enriched)
        feature: FeatureId = "best_take_choice"
        if feature not in self._routes or len(takes) > MAX_CHOICE_TAKES:
            return scored
        forward = self._choose(takes)
        backward = self._choose(list(reversed(takes)))
        if forward and backward and forward[0] == backward[0]:
            confidence = min(forward[1], backward[1])
            if confidence >= self._min_confidence:
                route = self._routes[feature]
                return ClusterDecision(
                    cluster_id=cluster.id,
                    chosen_take_id=forward[0],
                    confidence=confidence,
                    engine=self.name,
                    reason=f"{route.provider_id}/{route.model} chose it in both orders",
                )
            self._usage[feature].fallbacks += 1
            return scored.model_copy(update={"confidence": min(scored.confidence, confidence)})
        if forward and backward:
            self._usage[feature].fallbacks += 1
        reason = f"{scored.reason}; no model choice in both orders" if scored.reason else None
        return scored.model_copy(update={"confidence": 0.0, "reason": reason})

    # --- helpers --------------------------------------------------------------------

    def _with_model_scores(self, take: Take, features: TakeFeatures) -> TakeFeatures:
        routed = {f: TAKE_PROMPTS[f] for f in TAKE_PROMPTS if f in self._routes}
        if not routed:
            return features
        answers = self._ask({SEGMENT_TEXT: take.text}, routed)
        update: dict[str, Any] = {}
        fluency = answers.get("fluency_score")
        if isinstance(fluency, ScoreAnswer) and self._accepts("fluency_score", fluency):
            update["fluency"] = fluency.value
        complete = answers.get("idea_completeness")
        if isinstance(complete, NoulAnswer) and self._accepts("idea_completeness", complete):
            update["cut_off"] = not complete.value
        return features.model_copy(update=update)

    def _choose(self, takes: list[Take]) -> tuple[str, float] | None:
        """One Choice call; returns the chosen take id and the answer's confidence."""
        labels = take_labels(len(takes))
        by_label = dict(zip(labels, takes, strict=True))
        state = {"takes": {label: take.text for label, take in by_label.items()}}
        prompt = FeaturePrompt(BEST_TAKE_ID, best_take_question(labels))
        answer = self._ask(state, {"best_take_choice": prompt})["best_take_choice"]
        if not isinstance(answer, ChoiceAnswer):
            return None
        return by_label[answer.choice].id, answer.confidence

    def _accepts(self, feature: FeatureId, answer: Answer) -> bool:
        if answer.confidence >= self._min_confidence:
            return True
        self._usage[feature].fallbacks += 1
        return False

    def _ask(
        self, state: dict[str, Any], prompts: Mapping[FeatureId, FeaturePrompt]
    ) -> dict[FeatureId, Answer | None]:
        """Answer each feature's question about `state`, one call per provider and model,
        reusing earlier answers to the same question and state."""
        key = state_key(state)
        results: dict[FeatureId, Answer | None] = {}
        groups: dict[tuple[str, str], list[FeatureId]] = {}
        for feature, prompt in prompts.items():
            route = self._routes[feature]
            memo_key = (route.provider_id, route.model, prompt.question_id, key)
            if memo_key in self._memo:
                results[feature] = self._memo[memo_key]
                if results[feature] is None:
                    self._usage[feature].fallbacks += 1
            else:
                groups.setdefault((route.provider_id, route.model), []).append(feature)
        for (provider_id, model), features in groups.items():
            questions = {prompts[f].question_id: prompts[f].question for f in features}
            answers = self._call(self._routes[features[0]], features, state, questions)
            for feature in features:
                answer = None if answers is None else answers.get(prompts[feature].question_id)
                results[feature] = answer
                if answers is not None:
                    self._memo[(provider_id, model, prompts[feature].question_id, key)] = answer
                if answer is None:
                    self._usage[feature].fallbacks += 1
        return results

    def _call(
        self,
        route: FeatureRoute,
        features: list[FeatureId],
        state: dict[str, Any],
        questions: dict[str, Question],
    ) -> dict[str, Answer] | None:
        """The provider's answers; `{}` for a bad output (worth remembering), `None` when the
        provider is disabled or failed in a way that says nothing about this question."""
        if route.provider_id in self._disabled:
            return None
        try:
            result = ask_questions(route.provider, route.model, state, questions)
        except ProviderError as exc:
            for feature in features:
                self._usage[feature].failures += 1
            logger.warning(
                "%s (%s) failed for %s: %s; using the heuristic",
                route.provider_id,
                exc.code,
                ", ".join(features),
                exc.message,
            )
            if exc.code == "provider_bad_output":
                return {}
            # Auth, missing client, timeouts and outages repeat on every call.
            self._disabled.add(route.provider_id)
            return None
        self._record(features, result.usage)
        return result.answers

    def _record(self, features: list[FeatureId], usage: TokenUsage | None) -> None:
        share = len(features)
        for index, feature in enumerate(features):
            entry = self._usage[feature]
            entry.calls += 1
            if usage is None:
                continue
            for field in ("input_tokens", "output_tokens"):
                total = getattr(usage, field) or 0
                portion = total // share + (1 if index < total % share else 0)
                setattr(entry, field, getattr(entry, field) + portion)
