"""Group takes that are repeated attempts at the same line."""

import importlib.util
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import accumulate
from typing import Any, Protocol

from rapidfuzz import fuzz

from powereditor.decide.base import DecisionEngine
from powereditor.models import Take
from powereditor.pipeline.take_text import content_tokens, function_words_for

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
# Below this many words, character similarity confuses different short phrases, so a
# take this short is a fragment: it matches a line only by being said inside it.
MIN_FUZZY_WORDS = 3


class SimilarityModel(Protocol):
    """Similarity in [0, 1] between two take texts."""

    @property
    def name(self) -> str: ...

    def __call__(self, first: str, second: str) -> float: ...


class TextSimilarity:
    """rapidfuzz similarity on filler-free, accent-free text.

    `partial_ratio` and `token_set_ratio` both score a cut-off attempt as a match of
    the complete one. Short phrases compare whole words instead: a fragment said word
    for word inside the other text is a full match, unless it is only function words.
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
            short, other = sorted((a, b), key=len)
            if _contains(other, short) and set(short) - function_words_for(self.language):
                return 1.0
            return len(set(a) & set(b)) / len(set(a) | set(b))
        left, right = " ".join(a), " ".join(b)
        return max(fuzz.token_set_ratio(left, right), fuzz.partial_ratio(left, right)) / 100


def _contains(words: list[str], run: list[str]) -> bool:
    size = len(run)
    return any(words[start : start + size] == run for start in range(len(words) - size + 1))


def _is_fragment(take: Take) -> bool:
    return len(content_tokens(take.text, None)) < MIN_FUZZY_WORDS


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
    """Grouping of `takes` (in recording order); groups and their takes keep that order.

    Each take is compared with the earlier groups whose last take is inside the window,
    which counts full takes only, so a run of fragments does not push a retake out of it.
    A group matches directly at `same_threshold` or above, through `engine.same_take` in
    the grey zone. A full take joins its best match and also merges every other group it
    matches, so an earlier partial attempt is absorbed once the complete line arrives;
    merging two groups of several takes needs `same_threshold`, a lone take the usual
    rule. A fragment joins only its best match. Against a full take a group is scored by
    its full takes only, so a one-word fragment it absorbed does not attract other lines.
    """
    params = params or ClusterParams()
    fragment = [_is_fragment(take) for take in takes]
    full_seen = list(accumulate(not flag for flag in fragment))
    groups: list[list[int]] = []
    for index, take in enumerate(takes):
        candidates: list[tuple[float, int, int]] = []
        for group_index, group in enumerate(groups):
            last = group[-1]
            if not _within_window(takes[last], take, full_seen[index] - full_seen[last], params):
                continue
            members = group if fragment[index] else [m for m in group if not fragment[m]]
            score, anchor = max((similarity(takes[m].text, take.text), m) for m in members or group)
            candidates.append((score, anchor, group_index))
        candidates.sort(reverse=True)
        if fragment[index]:
            candidates = candidates[:1]
        matched = {
            group_index
            for rank, (score, anchor, group_index) in enumerate(candidates)
            if score >= params.same_threshold
            or (
                (rank == 0 or len(groups[group_index]) == 1)
                and _joins(score, takes[anchor], take, engine, params)
            )
        }
        if not matched:
            groups.append([index])
            continue
        merged = sorted([index, *(m for g in matched for m in groups[g])])
        target = min(matched)
        groups = [
            merged if g == target else group
            for g, group in enumerate(groups)
            if g == target or g not in matched
        ]
    return [[takes[m] for m in group] for group in groups]


def _joins(
    score: float, anchor: Take, take: Take, engine: DecisionEngine, params: ClusterParams
) -> bool:
    if score >= params.same_threshold:
        return True
    return score >= params.grey_threshold and engine.same_take(anchor, take, score).same
