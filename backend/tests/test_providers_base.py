from typing import Any

import pytest

from powereditor.providers.base import (
    JudgmentRequest,
    ProviderError,
    parse_output,
    system_prompt,
    user_prompt,
)
from powereditor.providers.registry import ProviderRegistry, default_registry

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"same": {"type": "boolean"}, "confidence": {"type": "number"}},
    "required": ["same", "confidence"],
    "additionalProperties": False,
}


def _request() -> JudgmentRequest:
    return JudgmentRequest(
        instructions="Are A and B attempts at the same line?",
        state={"a": "hola a todos", "b": "hola a todos, otra vez"},
        output_schema=SCHEMA,
        model="m1",
    )


def test_prompts_carry_instructions_state_and_optionally_the_schema() -> None:
    request = _request()

    assert system_prompt(request, include_schema=False).startswith("Are A and B attempts")
    assert '"additionalProperties"' not in system_prompt(request, include_schema=False)
    assert '"additionalProperties": false' in system_prompt(request, include_schema=True)
    assert '"b": "hola a todos, otra vez"' in user_prompt(request)


def test_parse_output_accepts_plain_and_fenced_json() -> None:
    assert parse_output('{"same": true, "confidence": 0.7}', SCHEMA) == {
        "same": True,
        "confidence": 0.7,
    }
    fenced = 'Sure:\n```json\n{"same": false, "confidence": 0.2}\n```'
    assert parse_output(fenced, SCHEMA) == {"same": False, "confidence": 0.2}


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("no json here", "not valid JSON"),
        ("[1, 2]", "not a JSON object"),
        ('{"same": "yes", "confidence": 0.5}', "does not match the schema"),
        ('{"same": true}', "does not match the schema"),
    ],
)
def test_parse_output_rejects_invalid_answers(text: str, reason: str) -> None:
    with pytest.raises(ProviderError) as caught:
        parse_output(text, SCHEMA)

    assert caught.value.code == "provider_bad_output"
    assert reason in caught.value.message


def test_default_registry_lists_builtin_kinds_and_transports() -> None:
    registry = default_registry()

    assert registry.available_transports("openai") == ["api", "local_cli"]
    assert registry.available_transports("gemini") == ["api", "local_cli"]
    assert registry.available_transports("anthropic") == ["api", "local_cli"]
    assert registry.available_transports("deepseek") == ["api"]
    assert registry.available_transports("unknown") == []
    assert [info.kind for info in registry.kinds()] == ["anthropic", "deepseek", "gemini", "openai"]


def test_registry_accepts_new_kinds_without_touching_builtins() -> None:
    registry = ProviderRegistry()
    registry.register("acme", "api", lambda config, context: pytest.fail("not created"))

    assert registry.available_transports("acme") == ["api"]
    assert registry.kinds()[0].label == "acme"
    with pytest.raises(ValueError, match="already registered"):
        registry.register("acme", "api", lambda config, context: pytest.fail("not created"))
