"""TypeSafe Jev over the System One HTTP API: typed Noul, Choice and Score answers.

Verified 2026-10-06 against https://docs.typesafe.ai/api.md, /primitives/noul.md,
/primitives/choice.md, /primitives/score.md and /models.md:

- `POST https://api.typesafe.ai/v1/systemone` with `Authorization: Bearer <key>` and a
  body `{"model", "state", "questions": {id: {"type", "instructions", "criteria"}}}`.
  Noul criteria are optional `{"true", "false"}` descriptions, Choice criteria map each
  option to its description, Score criteria are 2-10 level descriptions, low to high.
- Answers come back under `answers[id]`: `noul` (probability of yes), `choice` with
  `confidence`, `score` (0..top level, probability-weighted) with `confidence`, plus
  `usage.input_tokens` / `usage.output_tokens`.
- Models: `jev-1.13.0`, aliases `jev-latest` and `jev-preview`; `GET /v1/models` lists
  them (its body is not documented, so unknown shapes fall back to the known ids).
- 529 means overloaded and is retried with the other transient statuses.

Plain `httpx` is used instead of the `typesafe-sdk` package to keep the same retry, error
mapping and test transport as the other API providers.
"""

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from powereditor.providers.api.base import ApiProvider
from powereditor.providers.base import (
    JudgmentRequest,
    JudgmentResult,
    ModelInfo,
    ProviderContext,
    ProviderError,
    TokenUsage,
    as_int,
)
from powereditor.providers.config import ProviderConfig
from powereditor.providers.questions import (
    Answer,
    ChoiceAnswer,
    ChoiceQuestion,
    NoulAnswer,
    NoulQuestion,
    Question,
    QuestionAnswers,
    ScoreAnswer,
    scale_fraction,
)

TYPESAFE_BASE_URL = "https://api.typesafe.ai/v1"
KNOWN_MODELS = (
    ModelInfo(id="jev-latest", note="Most recent stable Jev release."),
    ModelInfo(id="jev-1.13.0", label="Jev 1.13"),
)


class JevProvider(ApiProvider):
    kind = "typesafe"
    label = "TypeSafe Jev"

    def list_models(self) -> list[ModelInfo]:
        data = self._request("GET", "/models")
        items = data.get("data") if isinstance(data.get("data"), list) else data.get("models")
        ids = [
            item["id"]
            for item in items or []
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]
        return [ModelInfo(id=model_id) for model_id in ids] or list(KNOWN_MODELS)

    def judge(self, request: JudgmentRequest) -> JudgmentResult:
        raise ProviderError(
            "provider_bad_output", "Jev answers typed questions (Noul, Choice, Score) only."
        )

    def ask(
        self, model: str, state: Mapping[str, Any], questions: Mapping[str, Question]
    ) -> QuestionAnswers:
        body = {
            "model": model,
            "state": dict(state),
            "questions": {key: _question(question) for key, question in questions.items()},
        }
        data = self._request("POST", "/systemone", body=body)
        answers = data.get("answers")
        if not isinstance(answers, dict):
            raise ProviderError("provider_bad_output", "Jev sent no answers.")
        parsed = {
            key: _answer(key, question, answers.get(key)) for key, question in questions.items()
        }
        usage = data.get("usage") or {}
        tokens = TokenUsage(
            input_tokens=as_int(usage.get("input_tokens")),
            output_tokens=as_int(usage.get("output_tokens")),
        )
        return QuestionAnswers(answers=parsed, usage=tokens)


def _question(question: Question) -> dict[str, Any]:
    payload: dict[str, Any] = {"type": question.type, "instructions": question.instructions}
    if isinstance(question, NoulQuestion):
        payload["criteria"] = {"true": question.when_true, "false": question.when_false}
    elif isinstance(question, ChoiceQuestion):
        payload["criteria"] = dict(question.options)
    else:
        payload["criteria"] = list(question.levels)
    return payload


def _answer(key: str, question: Question, raw: Any) -> Answer:
    if not isinstance(raw, dict):
        raise ProviderError("provider_bad_output", f"Jev sent no answer for {key!r}.")
    try:
        if isinstance(question, NoulQuestion):
            return NoulAnswer(probability=raw["noul"])
        if isinstance(question, ChoiceQuestion):
            answer = ChoiceAnswer(choice=raw["choice"], confidence=raw["confidence"])
            if answer.choice not in question.options:
                raise ProviderError("provider_bad_output", f"Jev picked an unknown {key!r}.")
            return answer
        value = scale_fraction(float(raw["score"]), len(question.levels))
        return ScoreAnswer(value=value, confidence=raw["confidence"])
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise ProviderError("provider_bad_output", f"Jev sent a malformed {key!r}.") from exc


def create_jev(config: ProviderConfig, context: ProviderContext) -> JevProvider:
    return JevProvider(config.base_url or TYPESAFE_BASE_URL, context)
