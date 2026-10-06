"""Anthropic Messages API with structured outputs (`output_config.format`).

Structured outputs require `additionalProperties: false` on every object and reject
numeric and string-length constraints; the answer is validated locally either way.
"""

import time
from typing import Any

from powereditor.providers.api.base import ApiProvider
from powereditor.providers.base import (
    JudgmentRequest,
    JudgmentResult,
    ModelInfo,
    ProviderContext,
    ProviderError,
    TokenUsage,
    as_int,
    build_result,
    system_prompt,
    user_prompt,
)
from powereditor.providers.config import ProviderConfig

ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"
MAX_OUTPUT_TOKENS = 1024
MAX_PAGES = 10


class AnthropicApiProvider(ApiProvider):
    kind = "anthropic"
    label = "Anthropic"

    def _headers(self, api_key: str) -> dict[str, str]:
        return {"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION}

    def list_models(self) -> list[ModelInfo]:
        models: list[ModelInfo] = []
        params: dict[str, Any] = {"limit": 1000}
        for _ in range(MAX_PAGES):
            data = self._request("GET", "/models", params=params)
            models.extend(_model_info(item) for item in _items(data.get("data")))
            if not data.get("has_more") or not data.get("last_id"):
                break
            params = {**params, "after_id": data["last_id"]}
        return models

    def judge(self, request: JudgmentRequest) -> JudgmentResult:
        body: dict[str, Any] = {
            "model": request.model,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "system": system_prompt(request, include_schema=False),
            "messages": [{"role": "user", "content": user_prompt(request)}],
            "output_config": {"format": {"type": "json_schema", "schema": request.output_schema}},
        }
        if request.temperature is not None:
            body["temperature"] = request.temperature
        started = time.perf_counter()
        data = self._request("POST", "/messages", body=body)
        if data.get("stop_reason") == "refusal":
            raise ProviderError("provider_bad_output", "Anthropic refused to answer.")
        text = "".join(
            block.get("text", "")
            for block in data.get("content", [])
            if isinstance(block, dict) and block.get("type") == "text"
        )
        usage = data.get("usage") or {}
        tokens = TokenUsage(
            input_tokens=as_int(usage.get("input_tokens")),
            output_tokens=as_int(usage.get("output_tokens")),
        )
        return build_result(text, request.output_schema, started, tokens)


def _items(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise ProviderError("provider_bad_output", "Anthropic sent an unexpected model list.")
    return value


def _model_info(item: Any) -> ModelInfo:
    if not isinstance(item, dict) or not isinstance(item.get("id"), str):
        raise ProviderError("provider_bad_output", "Anthropic sent a model without an id.")
    label = item.get("display_name")
    return ModelInfo(id=item["id"], label=label if isinstance(label, str) else None)


def create_anthropic(config: ProviderConfig, context: ProviderContext) -> AnthropicApiProvider:
    return AnthropicApiProvider(config.base_url or ANTHROPIC_BASE_URL, context)
