import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from powereditor.providers.base import JudgmentRequest, ModelProvider, ProviderError
from powereditor.providers.config import ProviderConfig
from powereditor.providers.registry import ProviderContext, default_registry

Handler = Callable[[httpx.Request], httpx.Response]

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"same": {"type": "boolean"}},
    "required": ["same"],
    "additionalProperties": False,
}
ANSWER = '{"same": true}'
KEY = "sk-test-key"


def _provider(kind: str, handler: Handler, sleeps: list[float] | None = None) -> ModelProvider:
    config = ProviderConfig(id=f"my-{kind}", kind=kind, transport="api", label=kind)
    recorded = sleeps if sleeps is not None else []
    context = ProviderContext(
        api_key=KEY, http_transport=httpx.MockTransport(handler), sleep=recorded.append
    )
    return default_registry().create(config, context)


def _request(model: str = "m1") -> JudgmentRequest:
    return JudgmentRequest(
        instructions="Same line?", state={"a": "uno", "b": "uno"}, output_schema=SCHEMA, model=model
    )


def _chat_completion(request: httpx.Request) -> httpx.Response:
    body = {
        "choices": [{"message": {"role": "assistant", "content": ANSWER}}],
        "usage": {"prompt_tokens": 31, "completion_tokens": 4},
    }
    return httpx.Response(200, json=body)


def test_openai_judge_requests_strict_json_schema() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _chat_completion(request)

    result = _provider("openai", handler).judge(_request("gpt-test"))

    sent = json.loads(seen[0].content)
    assert str(seen[0].url) == "https://api.openai.com/v1/chat/completions"
    assert seen[0].headers["authorization"] == f"Bearer {KEY}"
    assert sent["model"] == "gpt-test"
    assert sent["response_format"]["type"] == "json_schema"
    assert sent["response_format"]["json_schema"]["schema"] == SCHEMA
    assert sent["response_format"]["json_schema"]["strict"] is True
    assert result.output == {"same": True}
    assert result.raw_text == ANSWER
    assert (result.usage.input_tokens, result.usage.output_tokens) == (31, 4)  # type: ignore[union-attr]


def test_deepseek_uses_json_object_mode_with_schema_in_prompt() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _chat_completion(request)

    result = _provider("deepseek", handler).judge(_request("deepseek-chat"))

    sent = json.loads(seen[0].content)
    assert str(seen[0].url) == "https://api.deepseek.com/chat/completions"
    assert sent["response_format"] == {"type": "json_object"}
    assert '"required": [' in sent["messages"][0]["content"]
    assert "json" in sent["messages"][0]["content"].lower()
    assert result.output == {"same": True}


def test_deepseek_empty_content_is_bad_output() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": ""}}]})

    with pytest.raises(ProviderError) as caught:
        _provider("deepseek", handler).judge(_request())

    assert caught.value.code == "provider_bad_output"


def test_gemini_judge_uses_response_json_schema() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = {
            "candidates": [{"content": {"parts": [{"text": ANSWER}], "role": "model"}}],
            "usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 3},
        }
        return httpx.Response(200, json=body)

    result = _provider("gemini", handler).judge(_request("gemini-2.5-flash"))

    sent = json.loads(seen[0].content)
    assert seen[0].url.path == "/v1beta/models/gemini-2.5-flash:generateContent"
    assert seen[0].headers["x-goog-api-key"] == KEY
    assert sent["generationConfig"]["responseMimeType"] == "application/json"
    assert sent["generationConfig"]["responseJsonSchema"] == SCHEMA
    assert result.output == {"same": True}
    assert (result.usage.input_tokens, result.usage.output_tokens) == (20, 3)  # type: ignore[union-attr]


def test_gemini_invalid_key_reported_as_400_is_unauthorized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        error = {
            "code": 400,
            "status": "INVALID_ARGUMENT",
            "details": [{"reason": "API_KEY_INVALID"}],
        }
        return httpx.Response(400, json={"error": error})

    with pytest.raises(ProviderError) as caught:
        _provider("gemini", handler).list_models()

    assert caught.value.code == "provider_unauthorized"


def test_gemini_lists_only_generate_content_models() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        models = [
            {
                "name": "models/gemini-2.5-flash",
                "displayName": "Gemini 2.5 Flash",
                "supportedGenerationMethods": ["generateContent", "countTokens"],
            },
            {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},
        ]
        return httpx.Response(200, json={"models": models})

    models = _provider("gemini", handler).list_models()

    assert [(m.id, m.label) for m in models] == [("gemini-2.5-flash", "Gemini 2.5 Flash")]


def test_anthropic_judge_uses_output_config_json_schema() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = {
            "content": [{"type": "text", "text": ANSWER}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 40, "output_tokens": 5},
        }
        return httpx.Response(200, json=body)

    result = _provider("anthropic", handler).judge(_request("claude-test"))

    sent = json.loads(seen[0].content)
    assert str(seen[0].url) == "https://api.anthropic.com/v1/messages"
    assert seen[0].headers["x-api-key"] == KEY
    assert seen[0].headers["anthropic-version"] == "2023-06-01"
    assert sent["output_config"] == {"format": {"type": "json_schema", "schema": SCHEMA}}
    assert sent["max_tokens"] > 0
    assert result.output == {"same": True}


def test_anthropic_lists_models_across_pages() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("after_id") == "b":
            return httpx.Response(200, json={"data": [{"id": "c"}], "has_more": False})
        data = [{"id": "a", "display_name": "A"}, {"id": "b", "display_name": "B"}]
        return httpx.Response(200, json={"data": data, "has_more": True, "last_id": "b"})

    models = _provider("anthropic", handler).list_models()

    assert [m.id for m in models] == ["a", "b", "c"]


def test_openai_lists_models_sorted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "gpt-b"}, {"id": "gpt-a"}]})

    assert [m.id for m in _provider("openai", handler).list_models()] == ["gpt-a", "gpt-b"]


def test_retries_rate_limits_and_server_errors_with_backoff() -> None:
    statuses = iter([429, 503])
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        status = next(statuses, 200)
        if status != 200:
            return httpx.Response(status)
        return _chat_completion(request)

    result = _provider("openai", handler, sleeps).judge(_request())

    assert result.output == {"same": True}
    assert sleeps == [1.0, 2.0]


def test_retries_connection_errors_then_reports_unavailable() -> None:
    calls: list[int] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(ProviderError) as caught:
        _provider("openai", handler, sleeps).list_models()

    assert caught.value.code == "provider_unavailable"
    assert len(calls) == 3
    assert sleeps == [1.0, 2.0]


@pytest.mark.parametrize(
    ("status", "code"), [(401, "provider_unauthorized"), (400, "provider_unavailable")]
)
def test_client_errors_are_not_retried(status: int, code: str) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(status, json={"error": {"message": "nope"}})

    with pytest.raises(ProviderError) as caught:
        _provider("openai", handler).judge(_request())

    assert caught.value.code == code
    assert len(calls) == 1


def test_read_timeout_is_reported_without_retry() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(ProviderError) as caught:
        _provider("anthropic", handler).judge(_request())

    assert caught.value.code == "provider_timeout"
    assert len(calls) == 1


def test_missing_api_key_is_unauthorized_without_a_request() -> None:
    config = ProviderConfig(id="o", kind="openai", transport="api", label="OpenAI")
    context = ProviderContext(api_key=None, http_transport=httpx.MockTransport(_chat_completion))

    with pytest.raises(ProviderError) as caught:
        default_registry().create(config, context).judge(_request())

    assert caught.value.code == "provider_unauthorized"


def test_check_reports_model_count() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "gpt-a"}]})

    check = _provider("openai", handler).check()

    assert check.ok is True
    assert check.authenticated is True
    assert "1 model" in check.detail
