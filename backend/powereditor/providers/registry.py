"""Provider factories keyed by (kind, transport).

Features ask the registry for a provider built from a `ProviderConfig`; they never import
an adapter. A new provider registers a factory here (or on its own registry instance)
and nothing else changes.
"""

from powereditor.models import CamelModel
from powereditor.providers.api.anthropic import create_anthropic
from powereditor.providers.api.deepseek import create_deepseek
from powereditor.providers.api.gemini import create_gemini
from powereditor.providers.api.openai import create_openai
from powereditor.providers.base import (
    ModelProvider,
    ProviderContext,
    ProviderFactory,
    ProviderKind,
    Transport,
)
from powereditor.providers.config import ProviderConfig
from powereditor.providers.local_cli.claude import ClaudeCliProvider
from powereditor.providers.local_cli.codex import CodexCliProvider
from powereditor.providers.local_cli.gemini import GeminiCliProvider

__all__ = ["ProviderContext", "ProviderKindInfo", "ProviderRegistry", "default_registry"]

_TRANSPORT_ORDER: tuple[Transport, ...] = ("api", "local_cli")


class ProviderKindInfo(CamelModel):
    kind: ProviderKind
    label: str
    transports: list[Transport]


class ProviderRegistry:
    def __init__(self) -> None:
        self._factories: dict[tuple[ProviderKind, Transport], ProviderFactory] = {}
        self._labels: dict[ProviderKind, str] = {}

    def register(
        self,
        kind: ProviderKind,
        transport: Transport,
        factory: ProviderFactory,
        *,
        label: str | None = None,
    ) -> None:
        if (kind, transport) in self._factories:
            raise ValueError(f"provider {kind!r} with transport {transport!r} already registered")
        self._factories[(kind, transport)] = factory
        self._labels.setdefault(kind, label or kind)

    def available_transports(self, kind: ProviderKind) -> list[Transport]:
        return [t for t in _TRANSPORT_ORDER if (kind, t) in self._factories]

    def kinds(self) -> list[ProviderKindInfo]:
        return [
            ProviderKindInfo(kind=kind, label=label, transports=self.available_transports(kind))
            for kind, label in sorted(self._labels.items())
        ]

    def supports(self, kind: ProviderKind, transport: Transport) -> bool:
        return (kind, transport) in self._factories

    def create(self, config: ProviderConfig, context: ProviderContext) -> ModelProvider:
        factory = self._factories.get((config.kind, config.transport))
        if factory is None:
            raise KeyError(f"no provider registered for {config.kind!r} over {config.transport!r}")
        return factory(config, context)


def default_registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register("openai", "api", create_openai, label="OpenAI")
    registry.register("openai", "local_cli", CodexCliProvider.from_config)
    registry.register("gemini", "api", create_gemini, label="Google Gemini")
    registry.register("gemini", "local_cli", GeminiCliProvider.from_config)
    registry.register("anthropic", "api", create_anthropic, label="Anthropic Claude")
    registry.register("anthropic", "local_cli", ClaudeCliProvider.from_config)
    registry.register("deepseek", "api", create_deepseek, label="DeepSeek")
    return registry
