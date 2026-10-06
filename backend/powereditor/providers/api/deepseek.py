"""DeepSeek: OpenAI-compatible API in JSON mode (no JSON Schema enforcement).

Verified 2026-10-06 at https://api-docs.deepseek.com/guides/json_mode: base URL
`https://api.deepseek.com`, `response_format={"type": "json_object"}`, the prompt must
mention "json", and the API "may occasionally return empty content" (reported as
`provider_bad_output`).
"""

from powereditor.providers.api.openai import OpenAICompatibleProvider
from powereditor.providers.base import ProviderContext
from powereditor.providers.config import ProviderConfig

DEEPSEEK_BASE_URL = "https://api.deepseek.com"


def create_deepseek(config: ProviderConfig, context: ProviderContext) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        config.base_url or DEEPSEEK_BASE_URL,
        context,
        kind="deepseek",
        label="DeepSeek",
        json_mode="json_object",
    )
