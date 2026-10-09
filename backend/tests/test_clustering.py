import pytest

from powereditor.decide.heuristic import HeuristicEngine
from powereditor.models import Take
from powereditor.pipeline.clustering import ClusterParams, TextSimilarity, cluster_takes


def _take(index: int, text: str, source_id: str = "a", start: float | None = None) -> Take:
    begin = start if start is not None else index * 5.0
    return Take(
        id=f"take-{source_id}-{index}",
        segment_id=f"seg-{source_id}-{index}",
        source_id=source_id,
        start=begin,
        end=begin + 3.0,
        text=text,
    )


def _ids(clusters: list[list[Take]]) -> list[list[str]]:
    return [[take.id for take in cluster] for cluster in clusters]


def test_text_similarity_ignores_fillers_case_and_punctuation() -> None:
    similarity = TextSimilarity(language="es")

    assert (
        similarity(
            "Hola a todos, hoy vamos a hablar de café.",
            "eh hola a TODOS hoy vamos a hablar de cafe",
        )
        == 1.0
    )
    assert (
        similarity("Hoy vamos a hablar de", "Hoy vamos a hablar de café y de sus orígenes") >= 0.8
    )
    assert similarity("Hoy vamos a hablar de café", "El precio subió mucho este año") < 0.5


def test_text_similarity_compares_short_phrases_by_whole_words() -> None:
    similarity = TextSimilarity(language="es")

    assert similarity("palabra0 fin0.", "palabra1 fin1.") == 0.0
    assert similarity("Gracias.", "gracias") == 1.0


def test_text_similarity_matches_a_fragment_said_inside_a_line() -> None:
    similarity = TextSimilarity(language="es")
    line = "Me hubiera gustado saber esto antes de empezar a correr"

    assert similarity("antes", line) == 1.0
    assert similarity(line, "eh, a correr") == 1.0
    assert similarity("correr antes", line) < 0.5
    assert similarity("de", line) < 0.5


def test_cluster_takes_groups_retakes_and_keeps_script_order() -> None:
    takes = [
        _take(0, "Hola a todos, hoy vamos a hablar de"),
        _take(1, "Hola a todos, hoy vamos a hablar de café."),
        _take(2, "El café llegó a Europa en el siglo diecisiete."),
        _take(3, "Eh, el café llegó a Europa en el siglo diecisiete."),
        _take(4, "Suscribite para más videos."),
    ]

    clusters = cluster_takes(takes, TextSimilarity(language="es"), HeuristicEngine())

    assert _ids(clusters) == [
        ["take-a-0", "take-a-1"],
        ["take-a-2", "take-a-3"],
        ["take-a-4"],
    ]


def test_cluster_takes_does_not_merge_repeats_outside_the_window() -> None:
    line = "Hoy vamos a hablar de café y de sus orígenes."
    takes = [
        _take(0, line),
        *(_take(i, f"Frase distinta número {i} sobre otra cosa.") for i in range(1, 4)),
        _take(4, line),
    ]

    near = cluster_takes(
        takes, TextSimilarity(language="es"), HeuristicEngine(), ClusterParams(window_takes=4)
    )
    far = cluster_takes(
        takes, TextSimilarity(language="es"), HeuristicEngine(), ClusterParams(window_takes=2)
    )

    assert ["take-a-0", "take-a-4"] in _ids(near)
    assert ["take-a-0"] in _ids(far) and ["take-a-4"] in _ids(far)


def test_cluster_takes_applies_the_time_window_within_a_source_only() -> None:
    line = "Hoy vamos a hablar de café y de sus orígenes."
    params = ClusterParams(window_seconds=30.0)
    same_source = [_take(0, line, start=0.0), _take(1, line, start=100.0)]
    across = [_take(0, line, start=100.0), _take(0, line, source_id="b", start=0.0)]

    assert (
        len(cluster_takes(same_source, TextSimilarity(language="es"), HeuristicEngine(), params))
        == 2
    )
    assert len(cluster_takes(across, TextSimilarity(language="es"), HeuristicEngine(), params)) == 1


class _FixedSimilarity:
    name = "fixed"

    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self, first: str, second: str) -> float:
        return self.value


@pytest.mark.parametrize(("value", "groups"), [(0.75, 1), (0.6, 2), (0.4, 2)])
def test_grey_zone_is_resolved_by_the_engine(value: float, groups: int) -> None:
    takes = [_take(0, "uno dos tres cuatro"), _take(1, "cinco seis siete ocho")]

    clusters = cluster_takes(takes, _FixedSimilarity(value), HeuristicEngine())

    assert len(clusters) == groups


# SYNTHETIC: modeled on a real retake-heavy recording (fragments around a line, a partial
# attempt before the full one, fragments between two attempts), with invented text.
RETAKE_SESSION = [
    "Me hubiera gustado saber esto antes de empezar a correr",
    "Eh, me hubiera gustado saber esto antes de empezar a correr",
    "Me hubiera gustado",
    "antes",
    "a correr",
    "Ojalá alguien me hubiera contado esto antes de empezar a correr",
    "Me hubiera",
    "Antes de cada carrera conviene estirar bien las piernas",
    "Entrenando para una maratón",
    "una maratón tenés que reorganizar toda tu semana pensar tus horarios pensar tus comidas",
    "Entrenando para una maratón con un trabajo full time tenés que reorganizar tu semana "
    "cambiar los horarios las comidas y dormir más de lo normal",
    "Como corredor principiante es muy difícil saber qué ritmo es bueno y qué ritmo es demasiado",
    "mirá",
    "che",
    "listo",
    "dale",
    "vamos",
    "ufa",
    "pará",
    "Como corredor principiante es muy difícil entender qué ritmo es bueno y cuál es demasiado",
    "El calzado es lo más importante cuando empezás a correr",
    "Elegir bien el calzado te ahorra lesiones",
]


def test_cluster_takes_absorbs_fragments_and_partial_attempts_of_a_line() -> None:
    takes = [_take(index, text) for index, text in enumerate(RETAKE_SESSION)]

    clusters = cluster_takes(takes, TextSimilarity(language="es"), HeuristicEngine())

    indices = [[int(take.id.rsplit("-", 1)[1]) for take in cluster] for cluster in clusters]
    assert indices == [
        [0, 1, 2, 3, 4, 5, 6],
        [7],
        [8, 9, 10],
        [11, 19],
        *([index] for index in range(12, 19)),
        [20],
        [21],
    ]
