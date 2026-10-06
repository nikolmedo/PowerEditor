import pytest

from powereditor.decide.base import DecisionEngine
from powereditor.decide.heuristic import HeuristicEngine
from powereditor.models import Segment, Take, TakeCluster, TakeFeatures
from powereditor.settings_store import TakeWeights


def _segment(text: str, index: int = 0) -> Segment:
    return Segment(
        id=f"seg-a-{index}", source_id="a", start=float(index), end=index + 1.0, text=text, words=[]
    )


def _take(index: int) -> Take:
    return Take(
        id=f"take-{index}",
        segment_id=f"seg-{index}",
        source_id="a",
        start=index,
        end=index + 1.0,
        text="x",
    )


def _features(index: int, **values: object) -> TakeFeatures:
    base: dict[str, object] = {
        "take_id": f"take-{index}",
        "completeness": 1.0,
        "filler_count": 0,
        "repetition_count": 0,
        "cut_off": False,
        "speech_rate_wps": 2.7,
        "is_last_take": False,
    }
    base.update(values)
    return TakeFeatures.model_validate(base)


def test_heuristic_engine_satisfies_the_protocol() -> None:
    engine: DecisionEngine = HeuristicEngine()

    assert engine.name == "heuristic"


@pytest.mark.parametrize(
    "text",
    [
        "Corta, corta.",
        "Otra vez",
        "¿Está grabando?",
        "Ok, de nuevo.",
        "Cut!",
        "Let me try that again.",
        "Sorry, again",
    ],
)
def test_classify_segment_flags_out_of_take_remarks(text: str) -> None:
    flags = HeuristicEngine().classify_segment(_segment(text))

    assert flags.is_audience_content is False
    assert flags.confidence >= 0.7


@pytest.mark.parametrize(
    "text",
    [
        "Hoy vamos a cortar la cebolla en cubos chicos para el sofrito.",
        "Mañana lo intento de nuevo con otra receta distinta y les cuento cómo me fue.",
        "This is how we cut the onion.",
    ],
)
def test_classify_segment_keeps_script_lines_with_trigger_words(text: str) -> None:
    assert HeuristicEngine().classify_segment(_segment(text)).is_audience_content is True


def test_classify_segment_reports_completeness_and_call_to_action() -> None:
    engine = HeuristicEngine()

    cut = engine.classify_segment(_segment("Y el secreto está en la"))
    cta = engine.classify_segment(_segment("Si te sirvió, suscribite y dejá tu like."))

    assert (cut.is_complete, cut.has_cta) == (False, False)
    assert (cta.is_complete, cta.has_cta) == (True, True)


def test_decide_cluster_prefers_the_complete_fluent_take() -> None:
    cluster = TakeCluster(id="grp-1", take_ids=["take-0", "take-1", "take-2"])
    features = [
        _features(0, completeness=0.6, cut_off=True),
        _features(1, filler_count=3),
        _features(2, is_last_take=True),
    ]

    decision = HeuristicEngine().decide_cluster(cluster, [_take(i) for i in range(3)], features)

    assert decision.chosen_take_id == "take-2"
    assert decision.engine == "heuristic"
    assert decision.confidence > 0.5


def test_decide_cluster_confidence_follows_the_score_margin() -> None:
    cluster = TakeCluster(id="grp-1", take_ids=["take-0", "take-1"])
    takes = [_take(0), _take(1)]
    engine = HeuristicEngine()

    tie = engine.decide_cluster(cluster, takes, [_features(0), _features(1)])
    clear = engine.decide_cluster(
        cluster, takes, [_features(0), _features(1, cut_off=True, completeness=0.4)]
    )

    assert tie.confidence == 0.0
    assert clear.chosen_take_id == "take-0"
    assert clear.confidence == 1.0


def test_decide_cluster_weights_come_from_settings() -> None:
    cluster = TakeCluster(id="grp-1", take_ids=["take-0", "take-1"])
    features = [_features(0, filler_count=2), _features(1, is_last_take=True, completeness=0.9)]
    takes = [_take(0), _take(1)]

    default = HeuristicEngine().decide_cluster(cluster, takes, features)
    no_bonus = HeuristicEngine(TakeWeights(last_take=0.0)).decide_cluster(cluster, takes, features)
    lenient = HeuristicEngine(TakeWeights(last_take=0.0, fillers=0.0)).decide_cluster(
        cluster, takes, features
    )

    assert default.chosen_take_id == "take-1"
    assert no_bonus.chosen_take_id == "take-1"
    assert lenient.chosen_take_id == "take-0"


def test_decide_cluster_with_one_take_is_certain() -> None:
    cluster = TakeCluster(id="grp-1", take_ids=["take-0"])

    decision = HeuristicEngine().decide_cluster(cluster, [_take(0)], [_features(0)])

    assert (decision.chosen_take_id, decision.confidence) == ("take-0", 1.0)


def test_same_take_uses_the_heuristic_threshold() -> None:
    engine = HeuristicEngine()

    assert engine.same_take(_take(0), _take(1), 0.72).same is True
    assert engine.same_take(_take(0), _take(1), 0.65).same is False


def test_transition_between_is_a_cut_for_now() -> None:
    decision = HeuristicEngine().transition_between(_segment("a", 0), _segment("b", 1))

    assert (decision.type, decision.topic_change) == ("cut", False)
