"""Text normalization shared by take clustering, features and the heuristic engine."""

import re
import unicodedata
from collections.abc import Sequence

_WORD = re.compile(r"[a-z0-9]+")

# Hesitations only: words like "este", "bueno" or "like" are often real content.
FILLERS: dict[str, frozenset[str]] = {
    "es": frozenset({"eh", "ehm", "em", "emm", "mm", "mmm", "hmm", "ah", "eee", "o sea"}),
    "en": frozenset({"uh", "uhm", "um", "umm", "er", "erm", "hmm", "mm", "ah", "you know"}),
}


def _word_set(words: str) -> frozenset[str]:
    return frozenset(words.split())


# A phrase that stops on one of these words was most likely cut off.
FUNCTION_WORDS: dict[str, frozenset[str]] = {
    "es": _word_set(
        "de la el los las un una y o que a en por para con del al se lo mi tu su pero como"
    ),
    "en": _word_set("the a an and or to of in for with that my your but as at is"),
}


def _for_language(table: dict[str, frozenset[str]], language: str | None) -> frozenset[str]:
    if language in table:
        return table[language]
    return frozenset().union(*table.values())


def fillers_for(language: str | None) -> frozenset[str]:
    """Filler words for `language`; every known language when it is unknown."""
    return _for_language(FILLERS, language)


def function_words_for(language: str | None) -> frozenset[str]:
    return _for_language(FUNCTION_WORDS, language)


def tokens(text: str) -> list[str]:
    """Lowercase, accent-free word tokens without punctuation."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return _WORD.findall(plain)


def _filler_spans(words: Sequence[str], fillers: frozenset[str]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(words):
        pair = " ".join(words[index : index + 2])
        if index + 1 < len(words) and pair in fillers:
            spans.append((index, index + 2))
            index += 2
        elif words[index] in fillers:
            spans.append((index, index + 1))
            index += 1
        else:
            index += 1
    return spans


def count_fillers(words: Sequence[str], language: str | None) -> int:
    return len(_filler_spans(words, fillers_for(language)))


def content_tokens(text: str, language: str | None) -> list[str]:
    """Tokens of `text` with filler words removed."""
    words = tokens(text)
    dropped = {
        index
        for start, end in _filler_spans(words, fillers_for(language))
        for index in range(start, end)
    }
    return [word for index, word in enumerate(words) if index not in dropped]


def looks_cut_off(text: str, language: str | None) -> bool:
    """True when a phrase trails off: a cut word, an ellipsis or a dangling function word."""
    stripped = text.rstrip()
    if stripped.endswith(("-", "...", "…")):
        return True
    words = content_tokens(stripped, language)
    return bool(words) and words[-1] in function_words_for(language)
