"""Per-feature model routing: gating, double-order choice, fallbacks, usage and schemas."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from powereditor.config import Settings
from powereditor.decide.factory import create_engine
from powereditor.decide.heuristic import HeuristicEngine
from powereditor.decide.model_engine import FeatureRoute, ModelDecisionEngine
from powereditor.decide.prompts import (
    SAME_LINE,
    SEGMENT_PROMPTS,
    TAKE_PROMPTS,
    TOPIC_CHANGE,
    best_take_question,
)
from powereditor.models import Segment, Take, TakeCluster, TakeFeatures
from powereditor.paths import AppPaths
from powereditor.pipeline.analyze import record_model_usage
from powereditor.pipeline.runner import ProjectLayout
from powereditor.providers.base import (
    CheckResult,
    JudgmentRequest,
    JudgmentResult,
    ModelInfo,
    ProviderError,
    TokenUsage,
    Transport,
)
from powereditor.providers.config import FeatureId, ProviderConfig
from powereditor.providers.questions import Question, judgment_request, parse_answers
from powereditor.settings_store import InMemorySecretStore, SettingsService

Answerer = Callable[[str, dict[str, Any]], dict[str, Any]]


class ScriptedProvider:
    """A JSON-answering provider whose answers come from a function of (question, state)."""

    kind = "fake"
    transport: Transport = "api"

    def __init__(self, answer: Answerer, *, error: ProviderError | None = None) -> None:
        self.answer = answer
        self.error = error
        self.requests: list[JudgmentRequest] = []

    def check(self) -> CheckResult:
        return CheckResult(ok=True, detail="ok")

    def list_models(self) -> list[ModelInfo]:
        return [ModelInfo(id="m")]

    def judge(self, request: JudgmentRequest) -> JudgmentResult:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        output = {
            key: self.answer(key, request.state) for key in request.output_schema["properties"]
        }
        usage = TokenUsage(input_tokens=11, output_tokens=3)
        return JudgmentResult(output=output, raw_text=json.dumps(output), usage=usage, latency_s=0)


def _noul(yes: bool, certainty: str = "high") -> dict[str, Any]:
    return {"answer": "yes" if yes else "no", "certainty": certainty}


def _engine(
    provider: ScriptedProvider, *features: FeatureId, min_confidence: float = 0.8
) -> ModelDecisionEngine:
    route = FeatureRoute("fake-1", "fake", "api", "m", provider)
    return ModelDecisionEngine(HeuristicEngine(), dict.fromkeys(features, route), min_confidence)


def _segment(text: str, index: int = 0) -> Segment:
    return Segment(
        id=f"seg-{index}", source_id="a", start=index, end=index + 1, text=text, words=[]
    )


def _take(index: int, text: str) -> Take:
    return Take(
        id=f"take-{index}",
        segment_id=f"seg-{index}",
        source_id="a",
        start=index,
        end=index + 1,
        text=text,
    )


def _features(index: int, **values: Any) -> TakeFeatures:
    base: dict[str, Any] = {
        "take_id": f"take-{index}",
        "completeness": 1.0,
        "filler_count": 0,
        "repetition_count": 0,
        "cut_off": False,
        "speech_rate_wps": 2.7,
        "is_last_take": False,
    }
    return TakeFeatures.model_validate({**base, **values})


LONG_TEXT = "Hoy vamos a ver cómo preparar el café de especialidad en casa paso a paso."


# --- segment features -----------------------------------------------------------------


def test_unrouted_features_answer_like_the_heuristic() -> None:
    provider = ScriptedProvider(lambda key, state: _noul(True))
    engine = _engine(provider, "topic_change")
    segment = _segment(LONG_TEXT)

    assert engine.classify_segment(segment) == HeuristicEngine().classify_segment(segment)
    assert provider.requests == []


def test_segment_features_on_one_provider_share_one_call() -> None:
    provider = ScriptedProvider(lambda key, state: _noul(key == "has_call_to_action"))
    engine = _engine(provider, "off_take_detection", "cta_detection")

    flags = engine.classify_segment(_segment(LONG_TEXT))

    assert len(provider.requests) == 1
    assert provider.requests[0].state == {"segment_text": LONG_TEXT}
    assert flags.is_audience_content is False
    assert flags.has_cta is True
    assert flags.confidence == pytest.approx(0.9)


def test_low_confidence_keeps_the_heuristic_answer_and_flags_it() -> None:
    provider = ScriptedProvider(lambda key, state: _noul(False, "low"))
    engine = _engine(provider, "off_take_detection")

    flags = engine.classify_segment(_segment(LONG_TEXT))

    assert flags.is_audience_content is True
    assert flags.confidence == pytest.approx(0.3)
    assert engine.usage_report().features["off_take_detection"].fallbacks == 1


def test_failing_provider_falls_back_and_stops_calling() -> None:
    error = ProviderError("provider_unauthorized", "bad key")
    provider = ScriptedProvider(lambda key, state: _noul(True), error=error)
    engine = _engine(provider, "off_take_detection")

    first = engine.classify_segment(_segment(LONG_TEXT, 0))
    engine.classify_segment(_segment("Otra cosa distinta que decir hoy.", 1))

    usage = engine.usage_report().features["off_take_detection"]
    assert first.is_audience_content is True
    assert first.confidence == 0.0
    assert len(provider.requests) == 1
    assert (usage.calls, usage.failures, usage.fallbacks) == (0, 1, 2)


def test_same_question_and_state_are_answered_once() -> None:
    provider = ScriptedProvider(lambda key, state: _noul(True))
    engine = _engine(provider, "off_take_detection")

    engine.classify_segment(_segment(LONG_TEXT, 0))
    engine.classify_segment(_segment(LONG_TEXT, 1))

    assert len(provider.requests) == 1


def test_same_take_and_topic_change_use_two_text_states() -> None:
    provider = ScriptedProvider(lambda key, state: _noul(key == "topic_change"))
    engine = _engine(provider, "same_take_grey_zone", "topic_change")

    same = engine.same_take(_take(0, "uno"), _take(1, "dos"), 0.72)
    transition = engine.transition_between(_segment("uno"), _segment("dos", 1))

    assert same.same is False
    assert same.confidence == pytest.approx(0.9)
    assert transition.topic_change is True
    assert transition.type == "cut"
    assert provider.requests[0].state == {"first_text": "uno", "second_text": "dos"}
    assert provider.requests[1].state == {"previous_segment": "uno", "next_segment": "dos"}


# --- best take ------------------------------------------------------------------------


def _cluster() -> tuple[TakeCluster, list[Take], list[TakeFeatures]]:
    takes = [_take(0, "primer intento malo"), _take(1, "el intento bueno"), _take(2, "otro malo")]
    features = [_features(0), _features(1), _features(2, is_last_take=True)]
    return TakeCluster(id="grp-0", take_ids=[t.id for t in takes]), takes, features


def _pick(word: str) -> Answerer:
    def answer(key: str, state: dict[str, Any]) -> dict[str, Any]:
        label = next(label for label, text in state["takes"].items() if word in text)
        return {"choice": label, "certainty": "high"}

    return answer


def test_best_take_is_accepted_when_both_orders_agree() -> None:
    provider = ScriptedProvider(_pick("bueno"))
    cluster, takes, features = _cluster()

    decision = _engine(provider, "best_take_choice").decide_cluster(cluster, takes, features)

    first, second = (list(r.state["takes"].values()) for r in provider.requests)
    assert decision.chosen_take_id == "take-1"
    assert decision.engine == "model"
    assert decision.confidence == pytest.approx(0.9)
    assert second == list(reversed(first))


def test_position_bias_falls_back_to_the_scored_take() -> None:
    provider = ScriptedProvider(lambda key, state: {"choice": "A", "certainty": "high"})
    cluster, takes, features = _cluster()

    engine = _engine(provider, "best_take_choice")

    decision = engine.decide_cluster(cluster, takes, features)

    assert decision.chosen_take_id == "take-2"
    assert decision.engine == "heuristic"
    assert decision.confidence == 0.0
    assert len(provider.requests) == 2
    assert engine.usage_report().features["best_take_choice"].fallbacks == 1


def test_fluency_scores_enter_the_weighted_take_score() -> None:
    def answer(key: str, state: dict[str, Any]) -> dict[str, Any]:
        good = "bueno" in state["segment_text"]
        return {"level": "4" if good else "0", "certainty": "high"}

    provider = ScriptedProvider(answer)
    cluster, takes, _ = _cluster()
    features = [_features(0), _features(1), _features(2)]

    decision = _engine(provider, "fluency_score").decide_cluster(cluster, takes, features)

    assert decision.chosen_take_id == "take-1"
    assert len(provider.requests) == 3


def test_model_idea_completeness_replaces_the_cut_off_detector() -> None:
    provider = ScriptedProvider(lambda key, state: _noul("bueno" in state["segment_text"]))
    cluster, takes, _ = _cluster()
    features = [_features(0), _features(1), _features(2, is_last_take=True)]

    decision = _engine(provider, "idea_completeness").decide_cluster(cluster, takes, features)

    assert decision.chosen_take_id == "take-1"


# --- usage and fingerprint ------------------------------------------------------------


def test_usage_splits_tokens_of_a_shared_call() -> None:
    provider = ScriptedProvider(lambda key, state: _noul(True))
    engine = _engine(provider, "off_take_detection", "cta_detection")

    engine.classify_segment(_segment(LONG_TEXT))

    report = engine.usage_report()
    off, cta = report.features["off_take_detection"], report.features["cta_detection"]
    assert (off.calls, cta.calls) == (1, 1)
    assert off.input_tokens + cta.input_tokens == 11
    assert off.output_tokens + cta.output_tokens == 3
    assert report.calls == 2


def test_fingerprint_names_provider_model_and_prompt_version() -> None:
    engine = _engine(ScriptedProvider(lambda key, state: {}), "topic_change")

    fingerprint = engine.fingerprint()

    assert fingerprint["features"]["topic_change"] == {
        "provider": "fake-1",
        "kind": "fake",
        "transport": "api",
        "model": "m",
        "prompt": 1,
    }
    assert fingerprint["minConfidence"] == 0.8


# --- strict schemas -------------------------------------------------------------------

FORBIDDEN = {"minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems", "pattern"}


def _walk(node: Any) -> None:
    if isinstance(node, dict):
        assert not FORBIDDEN & node.keys()
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert node["required"] == list(node["properties"])
        for value in node.values():
            _walk(value)
    elif isinstance(node, list):
        for value in node:
            _walk(value)


def _all_questions() -> dict[str, Question]:
    prompts = [*SEGMENT_PROMPTS.values(), *TAKE_PROMPTS.values(), SAME_LINE, TOPIC_CHANGE]
    questions: dict[str, Question] = {p.question_id: p.question for p in prompts}
    questions["best_take"] = best_take_question(["A", "B", "C"])
    return questions


def test_every_feature_schema_is_strict_mode_compatible() -> None:
    request = judgment_request("m", {"segment_text": "x"}, _all_questions())

    _walk(request.output_schema)


def test_answers_outside_the_options_are_bad_output() -> None:
    questions = {"best_take": best_take_question(["A", "B"])}

    with pytest.raises(ProviderError) as unknown:
        parse_answers({"best_take": {"choice": "Z", "certainty": "high"}}, questions)
    with pytest.raises(ProviderError) as missing:
        parse_answers({}, questions)

    assert unknown.value.code == "provider_bad_output"
    assert missing.value.code == "provider_bad_output"


# --- factory --------------------------------------------------------------------------


def _service(tmp_path: Path) -> SettingsService:
    return SettingsService(
        paths=AppPaths(data_dir=tmp_path),
        secrets=InMemorySecretStore(),
        env=Settings(_env_file=None),
        cuda_available=lambda: False,
    )


def _assign(service: SettingsService, provider: ProviderConfig, feature: FeatureId) -> None:
    service.update(
        {
            "providers": [provider.model_dump(by_alias=True)],
            "featureModels": {feature: {"providerId": provider.id, "model": "gpt-x"}},
        }
    )


def test_factory_returns_the_heuristic_when_nothing_is_assigned(tmp_path: Path) -> None:
    engine = create_engine(_service(tmp_path))

    assert isinstance(engine, HeuristicEngine)


def test_factory_routes_assigned_features(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _assign(
        service, ProviderConfig(id="o1", kind="openai", transport="api", label="O"), "cta_detection"
    )
    service.update({"modelMinConfidence": 0.6})

    engine = create_engine(service)

    assert isinstance(engine, ModelDecisionEngine)
    assert engine.fingerprint()["features"]["cta_detection"]["model"] == "gpt-x"
    assert engine.fingerprint()["minConfidence"] == 0.6


def test_factory_skips_providers_that_cannot_be_built(tmp_path: Path) -> None:
    service = _service(tmp_path)
    untrusted = ProviderConfig(
        id="o1", kind="openai", transport="api", label="O", base_url="https://evil.example"
    )
    _assign(service, untrusted, "cta_detection")

    assert isinstance(create_engine(service), HeuristicEngine)


def test_usage_is_written_only_when_a_model_was_called(tmp_path: Path) -> None:
    layout = ProjectLayout(tmp_path / "project")
    layout.ensure()
    provider = ScriptedProvider(lambda key, state: _noul(True))
    engine = _engine(provider, "cta_detection")

    assert record_model_usage(layout, HeuristicEngine()) is None
    assert record_model_usage(layout, engine) is None
    engine.classify_segment(_segment(LONG_TEXT))
    report = record_model_usage(layout, engine)

    stored = json.loads((layout.cache_dir / "model_usage.json").read_text(encoding="utf-8"))
    assert report is not None
    assert stored["features"]["cta_detection"]["calls"] == 1
    assert stored["features"]["cta_detection"]["inputTokens"] == 11
