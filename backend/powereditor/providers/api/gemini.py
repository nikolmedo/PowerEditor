"""Gemini API `generateContent` with `responseJsonSchema` (Gemini 2.5 and later).

The API reports an invalid key as HTTP 400 with reason `API_KEY_INVALID`, so that case
maps to `provider_unauthorized` as well.
"""

import time
from typing import Any

import httpx

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

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
MAX_PAGES = 10


class GeminiApiProvider(ApiProvider):
    kind = "gemini"
    label = "Gemini"

    def _headers(self, api_key: str) -> dict[str, str]:
        return {"x-goog-api-key": api_key}

    def _is_auth_failure(self, response: httpx.Response) -> bool:
        if response.status_code == 400 and "API_KEY_INVALID" in response.text:
            return True
        return super()._is_auth_failure(response)

    def list_models(self) -> list[ModelInfo]:
        models: list[ModelInfo] = []
        params: dict[str, Any] = {"pageSize": 1000}
        for _ in range(MAX_PAGES):
            data = self._request("GET", "/models", params=params)
            for item in data.get("models", []):
                if "generateContent" in item.get("supportedGenerationMethods", []):
                    model_id = str(item["name"]).removeprefix("models/")
                    models.append(ModelInfo(id=model_id, label=item.get("displayName")))
            token = data.get("nextPageToken")
            if not token:
                break
            params = {**params, "pageToken": token}
        return models

    def judge(self, request: JudgmentRequest) -> JudgmentResult:
        generation: dict[str, Any] = {
            "responseMimeType": "application/json",
            "responseJsonSchema": request.output_schema,
        }
        if request.temperature is not None:
            generation["temperature"] = request.temperature
        body = {
            "systemInstruction": {
                "parts": [{"text": system_prompt(request, include_schema=False)}]
            },
            "contents": [{"role": "user", "parts": [{"text": user_prompt(request)}]}],
            "generationConfig": generation,
        }
        model = request.model.removeprefix("models/")
        started = time.perf_counter()
        data = self._request("POST", f"/models/{model}:generateContent", body=body)
        try:
            parts = data["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("provider_bad_output", "Gemini sent no answer.") from exc
        text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
        usage = data.get("usageMetadata") or {}
        tokens = TokenUsage(
            input_tokens=as_int(usage.get("promptTokenCount")),
            output_tokens=as_int(usage.get("candidatesTokenCount")),
        )
        return build_result(text, request.output_schema, started, tokens)


def create_gemini(config: ProviderConfig, context: ProviderContext) -> GeminiApiProvider:
    return GeminiApiProvider(config.base_url or GEMINI_BASE_URL, context)
