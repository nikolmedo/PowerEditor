"""Typed questions (Noul, Choice, Score) and how any provider answers them.

Feature prompts are written as these questions. A provider that speaks the primitives
natively (TypeSafe Jev) answers them directly through `QuestionProvider.ask`. Every
other provider gets one `JudgmentRequest` per state with a strict JSON Schema derived
from the questions: enums only, `additionalProperties: false` on every object and no
numeric or length constraints, so OpenAI and Anthropic strict modes accept it. Models
pick labels; probabilities and confidences are computed here, never by the model.
"""

import json
from collections.abc import Mapping
from typing import Annotated, Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from powereditor.models import CamelModel
from powereditor.providers.base import (
    JudgmentRequest,
    ModelProvider,
    ProviderError,
    TokenUsage,
)


class NoulQuestion(CamelModel):
    """Does a condition hold? Answered as the probability of yes."""

    type: Literal["noul"] = "noul"
    instructions: str = Field(min_length=1)
    when_true: str = Field(min_length=1)
    when_false: str = Field(min_length=1)


class ChoiceQuestion(CamelModel):
    """Which one of the options? Keys are short labels, values describe each option."""

    type: Literal["choice"] = "choice"
    instructions: str = Field(min_length=1)
    options: dict[str, str] = Field(min_length=2)


class ScoreQuestion(CamelModel):
    """Where on an ordered scale? `levels` go from the low end to the high end."""

    type: Literal["score"] = "score"
    instructions: str = Field(min_length=1)
    levels: list[str] = Field(min_length=2, max_length=10)


Question = Annotated[NoulQuestion | ChoiceQuestion | ScoreQuestion, Field(discriminator="type")]


class NoulAnswer(CamelModel):
    type: Literal["noul"] = "noul"
    probability: float = Field(ge=0.0, le=1.0)

    @property
    def value(self) -> bool:
        return self.probability >= 0.5

    @property
    def confidence(self) -> float:
        """0 at a coin flip, 1 when the probability is 0 or 1."""
        return abs(2 * self.probability - 1)


class ChoiceAnswer(CamelModel):
    type: Literal["choice"] = "choice"
    choice: str
    confidence: float = Field(ge=0.0, le=1.0)


class ScoreAnswer(CamelModel):
    type: Literal["score"] = "score"
    value: float = Field(ge=0.0, le=1.0)
    """Position on the scale normalized to 0 (lowest level) .. 1 (highest level)."""
    confidence: float = Field(ge=0.0, le=1.0)


Answer = NoulAnswer | ChoiceAnswer | ScoreAnswer


class QuestionAnswers(CamelModel):
    answers: dict[str, Answer]
    usage: TokenUsage | None = None


@runtime_checkable
class QuestionProvider(Protocol):
    """Providers that answer the primitives natively instead of free JSON."""

    def ask(
        self, model: str, state: Mapping[str, Any], questions: Mapping[str, Question]
    ) -> QuestionAnswers: ...


def ask_questions(
    provider: ModelProvider,
    model: str,
    state: Mapping[str, Any],
    questions: Mapping[str, Question],
) -> QuestionAnswers:
    """Answer every question about one `state` in a single provider call."""
    if isinstance(provider, QuestionProvider):
        return provider.ask(model, state, questions)
    result = provider.judge(judgment_request(model, state, questions))
    return QuestionAnswers(answers=parse_answers(result.output, questions), usage=result.usage)


# --- LLM translation ------------------------------------------------------------------

Certainty = Literal["low", "medium", "high"]
CERTAINTY_CONFIDENCE: dict[Certainty, float] = {"low": 0.3, "medium": 0.6, "high": 0.9}
"""Verbal certainty to confidence; a Noul's probability is (1 ± confidence) / 2."""

_CERTAINTY_SCHEMA = {"type": "string", "enum": list(CERTAINTY_CONFIDENCE)}
_PREAMBLE = (
    "Answer every question below about the input. Judge only what each question asks, "
    "from the input alone. Do not count, measure or calculate anything. For each answer "
    'also give "certainty": "high" when the input clearly decides it, "medium" when it '
    'probably does, "low" when it is unclear.'
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _NoulOut(_Strict):
    answer: Literal["yes", "no"]
    certainty: Certainty


class _ChoiceOut(_Strict):
    choice: str
    certainty: Certainty


class _ScoreOut(_Strict):
    level: str
    certainty: Certainty


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _answer_schema(question: Question) -> dict[str, Any]:
    if isinstance(question, NoulQuestion):
        label: dict[str, Any] = {"answer": {"type": "string", "enum": ["yes", "no"]}}
    elif isinstance(question, ChoiceQuestion):
        label = {"choice": {"type": "string", "enum": list(question.options)}}
    else:
        levels = [str(index) for index in range(len(question.levels))]
        label = {"level": {"type": "string", "enum": levels}}
    return _object({**label, "certainty": _CERTAINTY_SCHEMA})


def _describe(question_id: str, question: Question) -> str:
    lines = [f'Question "{question_id}": {question.instructions}']
    if isinstance(question, NoulQuestion):
        lines += [f'- "yes": {question.when_true}', f'- "no": {question.when_false}']
    elif isinstance(question, ChoiceQuestion):
        lines += [f'- "{key}": {text}' for key, text in question.options.items()]
    else:
        lines.append('Levels, from lowest to highest (answer the level number as "level"):')
        lines += [f'- "{index}": {text}' for index, text in enumerate(question.levels)]
    return "\n".join(lines)


def judgment_request(
    model: str, state: Mapping[str, Any], questions: Mapping[str, Question]
) -> JudgmentRequest:
    instructions = "\n\n".join(
        [_PREAMBLE, *(_describe(key, question) for key, question in questions.items())]
    )
    schema = _object({key: _answer_schema(question) for key, question in questions.items()})
    return JudgmentRequest(
        instructions=instructions, state=dict(state), output_schema=schema, model=model
    )


def _bad(question_id: str, reason: str) -> ProviderError:
    return ProviderError("provider_bad_output", f"Answer to {question_id!r} {reason}.")


def _parse_one(question_id: str, question: Question, raw: Any) -> Answer:
    try:
        if isinstance(question, NoulQuestion):
            noul = _NoulOut.model_validate(raw)
            confidence = CERTAINTY_CONFIDENCE[noul.certainty]
            sign = 1 if noul.answer == "yes" else -1
            return NoulAnswer(probability=(1 + sign * confidence) / 2)
        if isinstance(question, ChoiceQuestion):
            choice = _ChoiceOut.model_validate(raw)
            if choice.choice not in question.options:
                raise _bad(question_id, f"picks unknown option {choice.choice!r}")
            return ChoiceAnswer(
                choice=choice.choice, confidence=CERTAINTY_CONFIDENCE[choice.certainty]
            )
        score = _ScoreOut.model_validate(raw)
    except ValidationError as exc:
        raise _bad(question_id, "does not match its schema") from exc
    top = len(question.levels) - 1
    if not score.level.isdigit() or int(score.level) > top:
        raise _bad(question_id, f"picks unknown level {score.level!r}")
    return ScoreAnswer(
        value=scale_fraction(int(score.level), len(question.levels)),
        confidence=CERTAINTY_CONFIDENCE[score.certainty],
    )


def scale_fraction(position: float, level_count: int) -> float:
    """Position on a scale of `level_count` levels as 0..1; a one-level scale is neutral."""
    top = level_count - 1
    return position / top if top > 0 else 0.5


def parse_answers(
    output: Mapping[str, Any], questions: Mapping[str, Question]
) -> dict[str, Answer]:
    missing = [key for key in questions if key not in output]
    if missing:
        raise ProviderError("provider_bad_output", f"Missing answers: {', '.join(missing)}.")
    return {key: _parse_one(key, question, output[key]) for key, question in questions.items()}


def state_key(state: Mapping[str, Any]) -> str:
    """Stable text form of a state, for memoizing answers."""
    return json.dumps(state, sort_keys=True, ensure_ascii=False)
