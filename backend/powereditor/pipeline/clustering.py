"""Group takes that are repeated attempts at the same line."""

import importlib.util
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from rapidfuzz import fuzz

from powereditor.decide.base import DecisionEngine
from powereditor.models import Take
from powereditor.pipeline.take_text import content_tokens

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
# Below this many words, character similarity confuses different short phrases.
MIN_FUZZY_WORDS = 3


class SimilarityModel(Protocol):
    """Similarity in [0, 1] between two take texts."""

    @property
    def name(self) -> str: ...

    def __call__(self, first: str, second: str) -> float: ...


class TextSimilarity:
    """rapidfuzz similarity on filler-free, accent-free text.

    `partial_ratio` and `token_set_ratio` both score a cut-off attempt as a match of
    the complete one. Short phrases compare whole words instead.
    """

    name = "text"

    def __init__(self, language: str | None = None) -> None:
        self.language = language

    def __call__(self, first: str, second: str) -> float:
        a = content_tokens(first, self.language)
        b = content_tokens(second, self.language)
        if not a or not b:
            return 0.0
        if min(len(a), len(b)) < MIN_FUZZY_WORDS:
            return len(set(a) & set(b)) / len(set(a) | set(b))
        left, right = " ".join(a), " ".join(b)
        return max(fuzz.token_set_ratio(left, right), fuzz.partial_ratio(left, right)) / 100


class EmbeddingSimilarity:
    """Cosine similarity of multilingual sentence embeddings, floored by text similarity.

    Needs the optional `embeddings` extra; the model downloads on first use.
    """

    name = f"embeddings:{EMBEDDING_MODEL}"

    def __init__(self, language: str | None = None) -> None:
        from sentence_transformers import SentenceTransformer

        self._model: Any = SentenceTransformer(EMBEDDING_MODEL)
        self._text = TextSimilarity(language)

    def __call__(self, first: str, second: str) -> float:
        vectors = self._model.encode(
            [f"query: {first}", f"query: {second}"], normalize_embeddings=True
        )
        cosine = float(vectors[0] @ vectors[1])
        return max(min(cosine, 1.0), self._text(first, second), 0.0)


def create_similarity(kind: str, language: str | None) -> SimilarityModel:
    """The configured similarity model, falling back to text when embeddings are missing."""
    if kind == "embeddings":
        if importlib.util.find_spec("sentence_transformers") is not None:
            return EmbeddingSimilarity(language)
        logger.warning("sentence-transformers is not installed; using text similarity")
    return TextSimilarity(language)


@dataclass(frozen=True)
class ClusterParams:
    same_threshold: float = 0.8
    grey_threshold: float = 0.5
    # Only takes this close are compared, so repeated phrases far apart stay separate.
    window_takes: int = 6
    window_seconds: float = 120.0


def _within_window(earlier: Take, later: Take, distance: int, params: ClusterParams) -> bool:
    if distance > params.window_takes:
        return False
    # Time only orders takes inside one file; across files only the take count applies.
    return (
        earlier.source_id != later.source_id or later.start - earlier.end <= params.window_seconds
    )


def cluster_takes(
    takes: Sequence[Take],
    similarity: SimilarityModel,
    engine: DecisionEngine,
    params: ClusterParams | None = None,
) -> list[list[Take]]:
    """Greedy grouping of `takes` (in recording order); groups keep that order.

    Each take joins the most similar earlier group whose last take is inside the
    window: directly at `same_threshold` or above, through `engine.same_take` in the
    grey zone. Otherwise it starts a new group.
    """
    params = params or ClusterParams()
    groups: list[list[Take]] = []
    last_index: list[int] = []
    for index, take in enumerate(takes):
        best: tuple[float, int] | None = None
        for group_index, group in enumerate(groups):
            if not _within_window(group[-1], take, index - last_index[group_index], params):
                continue
            score = max(similarity(member.text, take.text) for member in group)
            if best is None or score > best[0]:
                best = (score, group_index)
        if best is not None and _joins(best[0], groups[best[1]][-1], take, engine, params):
            groups[best[1]].append(take)
            last_index[best[1]] = index
        else:
            groups.append([take])
            last_index.append(index)
    return groups


def _joins(
    score: float, anchor: Take, take: Take, engine: DecisionEngine, params: ClusterParams
) -> bool:
    if score >= params.same_threshold:
        return True
    return score >= params.grey_threshold and engine.same_take(anchor, take, score).same
