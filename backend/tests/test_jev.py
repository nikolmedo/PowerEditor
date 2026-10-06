import json
from typing import Any

import httpx
import pytest

from powereditor.providers.base import JudgmentRequest, ProviderContext, ProviderError
from powereditor.providers.config import ProviderConfig
from powereditor.providers.jev import JevProvider
from powereditor.providers.questions import (
    ChoiceAnswer,
    ChoiceQuestion,
    NoulAnswer,
    NoulQuestion,
    Question,
    ScoreAnswer,
    ScoreQuestion,
    ask_questions,
)
from powereditor.providers.registry import default_registry

KEY = "ts-test-key"
QUESTIONS: dict[str, Question] = {
    "remark": NoulQuestion(instructions="Remark?", when_true="yes", when_false="no"),
    "best": ChoiceQuestion(instructions="Best?", options={"A": "first", "B": "second"}),
    "fluency": ScoreQuestion(instructions="Fluent?", levels=["low", "mid", "high"]),
}
ANSWERS: dict[str, Any] = {
    "remark": {"type": "noul", "noul": 0.95},
    "best": {"type": "choice", "choice": "B", "confidence": 0.8, "probabilities": {}},
    "fluency": {"type": "score", "score": 1.5, "confidence": 0.7, "legend": {}},
}


def _jev(handler: Any) -> JevProvider:
    config = ProviderConfig(id="jev", kind="typesafe", transport="api", label="Jev")
    context = ProviderContext(api_key=KEY, http_transport=httpx.MockTransport(handler))
    provider = default_registry().create(config, context)
    assert isinstance(provider, JevProvider)
    return provider


def test_jev_sends_system_one_questions_and_maps_answers() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = {"model": "jev-1.13.0", "answers": ANSWERS, "usage": {"input_tokens": 90}}
        return httpx.Response(200, json=body)

    result = ask_questions(_jev(handler), "jev-latest", {"segment_text": "hola"}, QUESTIONS)

    sent = json.loads(seen[0].content)
    assert str(seen[0].url) == "https://api.typesafe.ai/v1/systemone"
    assert seen[0].headers["authorization"] == f"Bearer {KEY}"
    assert sent["model"] == "jev-latest"
    assert sent["state"] == {"segment_text": "hola"}
    assert sent["questions"]["remark"] == {
        "type": "noul",
        "instructions": "Remark?",
        "criteria": {"true": "yes", "false": "no"},
    }
    assert sent["questions"]["best"]["criteria"] == {"A": "first", "B": "second"}
    assert sent["questions"]["fluency"]["criteria"] == ["low", "mid", "high"]
    assert result.answers["remark"] == NoulAnswer(probability=0.95)
    assert result.answers["best"] == ChoiceAnswer(choice="B", confidence=0.8)
    assert result.answers["fluency"] == ScoreAnswer(value=0.75, confidence=0.7)
    assert result.usage is not None
    assert result.usage.input_tokens == 90


@pytest.mark.parametrize(
    "answers",
    [
        {},
        {**ANSWERS, "best": {"type": "choice", "choice": "Z", "confidence": 0.9}},
        {**ANSWERS, "remark": {"type": "noul"}},
        {**ANSWERS, "fluency": {"type": "score", "score": "high", "confidence": 0.5}},
    ],
)
def test_malformed_jev_answers_are_bad_output(answers: dict[str, Any]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"answers": answers})

    with pytest.raises(ProviderError) as caught:
        _jev(handler).ask("jev-latest", {"x": "y"}, QUESTIONS)

    assert caught.value.code == "provider_bad_output"


def test_jev_does_not_take_free_json_judgments() -> None:
    request = JudgmentRequest(instructions="x", state={}, output_schema={}, model="jev-latest")

    with pytest.raises(ProviderError):
        _jev(lambda request: httpx.Response(500)).judge(request)


def test_jev_model_list_falls_back_to_known_ids() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"object": "unknown shape"})

    assert [m.id for m in _jev(handler).list_models()] == ["jev-latest", "jev-1.13.0"]


def test_jev_overload_is_retried() -> None:
    statuses = iter([529])
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if next(statuses, 200) == 529:
            return httpx.Response(529)
        return httpx.Response(200, json={"data": [{"id": "jev-1.13.0"}]})

    config = ProviderConfig(id="jev", kind="typesafe", transport="api", label="Jev")
    context = ProviderContext(
        api_key=KEY, http_transport=httpx.MockTransport(handler), sleep=sleeps.append
    )

    models = default_registry().create(config, context).list_models()

    assert [m.id for m in models] == ["jev-1.13.0"]
    assert sleeps == [1.0]
