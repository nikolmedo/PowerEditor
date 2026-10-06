"""OpenAI Chat Completions, also used for OpenAI-compatible APIs such as DeepSeek.

`json_schema` mode sends the schema as a strict `response_format` (OpenAI requires
`additionalProperties: false` on every object). `json_object` mode only guarantees valid
JSON, so the schema goes into the system prompt and the answer is validated locally.
"""

import time
from typing import Any, Literal

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

OPENAI_BASE_URL = "https://api.openai.com/v1"
JsonMode = Literal["json_schema", "json_object"]


class OpenAICompatibleProvider(ApiProvider):
    def __init__(
        self,
        base_url: str,
        context: ProviderContext,
        *,
        kind: str,
        label: str,
        json_mode: JsonMode,
    ) -> None:
        super().__init__(base_url, context)
        self.kind = kind
        self.label = label
        self._json_mode = json_mode

    def list_models(self) -> list[ModelInfo]:
        data = self._request("GET", "/models").get("data", [])
        ids = {item["id"] for item in data if isinstance(item, dict) and "id" in item}
        return [ModelInfo(id=model_id) for model_id in sorted(ids)]

    def judge(self, request: JudgmentRequest) -> JudgmentResult:
        native = self._json_mode == "json_schema"
        body: dict[str, Any] = {
            "model": request.model,
            "messages": [
                {"role": "system", "content": system_prompt(request, include_schema=not native)},
                {"role": "user", "content": user_prompt(request)},
            ],
            "response_format": _response_format(request, self._json_mode),
        }
        if request.temperature is not None:
            body["temperature"] = request.temperature
        started = time.perf_counter()
        data = self._request("POST", "/chat/completions", body=body)
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("provider_bad_output", f"{self.label} sent no answer.") from exc
        if message.get("refusal"):
            raise ProviderError("provider_bad_output", f"{self.label} refused to answer.")
        usage = data.get("usage") or {}
        tokens = TokenUsage(
            input_tokens=as_int(usage.get("prompt_tokens")),
            output_tokens=as_int(usage.get("completion_tokens")),
        )
        return build_result(message.get("content") or "", request.output_schema, started, tokens)


def _response_format(request: JudgmentRequest, mode: JsonMode) -> dict[str, Any]:
    if mode == "json_object":
        return {"type": "json_object"}
    return {
        "type": "json_schema",
        "json_schema": {"name": "judgment", "schema": request.output_schema, "strict": True},
    }


def create_openai(config: ProviderConfig, context: ProviderContext) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        config.base_url or OPENAI_BASE_URL,
        context,
        kind="openai",
        label="OpenAI",
        json_mode="json_schema",
    )
