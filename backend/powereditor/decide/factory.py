"""Build the decision engine from the user's per-feature model assignments."""

import logging

import httpx

from powereditor.decide.base import DecisionEngine
from powereditor.decide.heuristic import HeuristicEngine
from powereditor.decide.model_engine import FeatureRoute, ModelDecisionEngine
from powereditor.providers.base import ModelProvider, ProviderContext, ProviderError
from powereditor.providers.config import FEATURE_IDS, FeatureId, ProviderConfig
from powereditor.providers.registry import ProviderRegistry, default_registry
from powereditor.settings_store import SettingsService

logger = logging.getLogger(__name__)


def create_engine(
    service: SettingsService,
    registry: ProviderRegistry | None = None,
    http_transport: httpx.BaseTransport | None = None,
) -> DecisionEngine:
    """The heuristic engine, or a per-feature routing engine when any feature has a
    model. A provider that cannot be built is logged and its features stay heuristic."""
    settings = service.get_effective()
    heuristic = HeuristicEngine(settings.take_weights, settings.language)
    routes = feature_routes(service, registry or default_registry(), http_transport)
    if not routes:
        return heuristic
    return ModelDecisionEngine(heuristic, routes, settings.model_min_confidence)


def feature_routes(
    service: SettingsService,
    registry: ProviderRegistry,
    http_transport: httpx.BaseTransport | None = None,
) -> dict[FeatureId, FeatureRoute]:
    providers: dict[str, ModelProvider | None] = {}
    routes: dict[FeatureId, FeatureRoute] = {}
    for feature in FEATURE_IDS:
        assigned = service.feature_model(feature)
        if assigned is None:
            continue
        config, model = assigned
        if config.id not in providers:
            providers[config.id] = _build(service, registry, config, http_transport)
        provider = providers[config.id]
        if provider is not None:
            routes[feature] = FeatureRoute(
                config.id, config.kind, config.transport, model, provider
            )
    return routes


def _build(
    service: SettingsService,
    registry: ProviderRegistry,
    config: ProviderConfig,
    http_transport: httpx.BaseTransport | None,
) -> ModelProvider | None:
    api_key = service.provider_api_key(config.id)
    if api_key is None and config.kind == "typesafe":
        api_key = service.get_secret("typesafe_api_key")
    context = ProviderContext(api_key=api_key, http_transport=http_transport)
    try:
        return registry.create(config, context)
    except (ProviderError, KeyError) as exc:
        logger.warning(
            "Provider %r is unusable, its features use the heuristic: %s", config.id, exc
        )
        return None
