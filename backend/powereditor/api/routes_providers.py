"""Provider registry, provider CRUD, API keys and per-feature model selection.

Providers live in `settings.json`; their API keys live in the secret store and are only
ever reported as set or not set.
"""

from typing import Annotated, Any, cast

import httpx
import keyring.errors
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import Field, ValidationError

from powereditor.api.routes_settings import SecretValue, ServiceDep
from powereditor.models import CamelModel
from powereditor.providers.base import (
    ModelInfo,
    ModelProvider,
    ProviderContext,
    ProviderError,
    ProviderErrorCode,
    Transport,
)
from powereditor.providers.config import (
    FEATURE_IDS,
    FeatureId,
    KindName,
    ModelRef,
    ProviderConfig,
    ProviderId,
    base_url_problem,
)
from powereditor.providers.registry import ProviderKindInfo, ProviderRegistry
from powereditor.settings_store import SettingsService, UserSettings

router = APIRouter(prefix="/api")


class ProviderCreate(CamelModel):
    id: ProviderId | None = None
    kind: KindName
    transport: Transport
    label: str = Field(min_length=1, max_length=80)
    enabled_models: list[str] = Field(default_factory=list)
    cli_path: str | None = None
    base_url: str | None = None
    custom_base_url_confirmed: bool = False


class ProviderUpdate(CamelModel):
    label: str | None = Field(default=None, min_length=1, max_length=80)
    enabled_models: list[str] | None = None
    cli_path: str | None = None
    base_url: str | None = None
    custom_base_url_confirmed: bool | None = None


class ProviderView(ProviderConfig):
    api_key_set: bool


class ApiKeyStatus(CamelModel):
    set: bool


class ProviderTestResult(CamelModel):
    ok: bool
    detail: str
    code: ProviderErrorCode | None = None
    version: str | None = None
    authenticated: bool | None = None


class FeatureModels(CamelModel):
    features: dict[FeatureId, ModelRef | None]


def get_registry(request: Request) -> ProviderRegistry:
    return cast(ProviderRegistry, request.app.state.provider_registry)


RegistryDep = Annotated[ProviderRegistry, Depends(get_registry)]


def _view(service: SettingsService, config: ProviderConfig) -> ProviderView:
    api_key_set = service.provider_api_key(config.id) is not None
    return ProviderView(**config.model_dump(), api_key_set=api_key_set)


def _require(service: SettingsService, provider_id: str) -> ProviderConfig:
    config = service.provider(provider_id)
    if config is None:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider_id}'")
    return config


def _unprocessable(exc: ValidationError) -> HTTPException:
    errors = exc.errors(include_url=False, include_context=False, include_input=False)
    return HTTPException(status_code=422, detail=errors)


def _trusted(config: ProviderConfig) -> ProviderConfig:
    if config.transport == "api" and (problem := base_url_problem(config)):
        raise HTTPException(status_code=422, detail=problem)
    return config


def _free_id(base: str, taken: set[str]) -> str:
    candidate, suffix = base, 2
    while candidate in taken:
        candidate, suffix = f"{base}-{suffix}", suffix + 1
    return candidate


def _build(request: Request, service: SettingsService, config: ProviderConfig) -> ModelProvider:
    transport: httpx.BaseTransport | None = request.app.state.provider_transport
    context = ProviderContext(api_key=service.provider_api_key(config.id), http_transport=transport)
    return get_registry(request).create(config, context)


def _features(settings: UserSettings) -> FeatureModels:
    return FeatureModels(
        features={feature: settings.feature_models.get(feature) for feature in FEATURE_IDS}
    )


@router.get("/providers/kinds")
def list_kinds(registry: RegistryDep) -> list[ProviderKindInfo]:
    return registry.kinds()


@router.get("/providers")
def list_providers(service: ServiceDep) -> list[ProviderView]:
    return [_view(service, config) for config in service.get_effective().providers]


@router.post("/providers", status_code=201)
def create_provider(
    body: ProviderCreate, service: ServiceDep, registry: RegistryDep
) -> ProviderView:
    if not registry.supports(body.kind, body.transport):
        detail = f"No provider '{body.kind}' with transport '{body.transport}'"
        raise HTTPException(status_code=422, detail=detail)
    created: list[ProviderConfig] = []

    def add(current: UserSettings) -> dict[str, Any]:
        taken = {provider.id for provider in current.providers}
        if body.id is not None and body.id in taken:
            raise HTTPException(status_code=409, detail=f"Provider '{body.id}' already exists")
        provider_id = body.id or _free_id(f"{body.kind}-{body.transport}".replace("_", "-"), taken)
        config = _trusted(ProviderConfig(**body.model_dump(exclude={"id"}), id=provider_id))
        created.append(config)
        return {"providers": [*current.providers, config]}

    try:
        service.mutate(add)
    except ValidationError as exc:
        raise _unprocessable(exc) from exc
    return _view(service, created[0])


@router.get("/providers/{provider_id}")
def read_provider(provider_id: str, service: ServiceDep) -> ProviderView:
    return _view(service, _require(service, provider_id))


@router.patch("/providers/{provider_id}")
def update_provider(provider_id: str, body: ProviderUpdate, service: ServiceDep) -> ProviderView:
    _require(service, provider_id)
    changes = body.model_dump(include=body.model_fields_set)

    def patch(current: UserSettings) -> dict[str, Any]:
        providers = [
            _trusted(ProviderConfig(**{**p.model_dump(), **changes})) if p.id == provider_id else p
            for p in current.providers
        ]
        return {"providers": providers}

    try:
        service.mutate(patch)
    except ValidationError as exc:
        raise _unprocessable(exc) from exc
    return _view(service, _require(service, provider_id))


@router.delete("/providers/{provider_id}", status_code=204)
def delete_provider(provider_id: str, service: ServiceDep) -> Response:
    _require(service, provider_id)

    def remove(current: UserSettings) -> dict[str, Any]:
        # Under the settings lock and before anything is written: if the secret cannot be
        # cleared, the provider and its feature assignments stay untouched.
        service.clear_provider_api_key(provider_id)
        features = {
            feature: None if ref is not None and ref.provider_id == provider_id else ref
            for feature, ref in current.feature_models.items()
        }
        providers = [p for p in current.providers if p.id != provider_id]
        return {"providers": providers, "feature_models": features}

    try:
        service.mutate(remove)
    except keyring.errors.KeyringError as exc:
        raise HTTPException(status_code=503, detail="Secure storage is unavailable") from exc
    return Response(status_code=204)


@router.put("/providers/{provider_id}/api-key")
def store_api_key(provider_id: str, body: SecretValue, service: ServiceDep) -> ApiKeyStatus:
    _require(service, provider_id)
    try:
        service.set_provider_api_key(provider_id, body.value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Secret value must not be empty") from exc
    except keyring.errors.KeyringError as exc:
        raise HTTPException(status_code=503, detail="Secure storage is unavailable") from exc
    return ApiKeyStatus(set=True)


@router.delete("/providers/{provider_id}/api-key")
def delete_api_key(provider_id: str, service: ServiceDep) -> ApiKeyStatus:
    _require(service, provider_id)
    try:
        service.clear_provider_api_key(provider_id)
    except keyring.errors.KeyringError as exc:
        raise HTTPException(status_code=503, detail="Secure storage is unavailable") from exc
    return ApiKeyStatus(set=service.provider_api_key(provider_id) is not None)


@router.post("/providers/{provider_id}/test")
def test_provider(provider_id: str, request: Request, service: ServiceDep) -> ProviderTestResult:
    """API transports list models with the stored key; local clients report version and
    sign-in state. Neither sends a prompt."""
    config = _require(service, provider_id)
    try:
        provider = _build(request, service, config)
        if config.transport == "local_cli":
            return ProviderTestResult(**provider.check().model_dump())
        count = len(provider.list_models())
    except ProviderError as exc:
        return ProviderTestResult(ok=False, detail=exc.message, code=exc.code)
    return ProviderTestResult(ok=True, authenticated=True, detail=f"{count} models available.")


@router.get("/providers/{provider_id}/models")
def list_provider_models(
    provider_id: str, request: Request, service: ServiceDep
) -> list[ModelInfo]:
    config = _require(service, provider_id)
    try:
        return _build(request, service, config).list_models()
    except ProviderError as exc:
        raise HTTPException(
            status_code=502, detail={"code": exc.code, "message": exc.message}
        ) from exc


@router.get("/features/models")
def read_feature_models(service: ServiceDep) -> FeatureModels:
    return _features(service.get_effective())


@router.put("/features/models")
def replace_feature_models(body: FeatureModels, service: ServiceDep) -> FeatureModels:
    def replace(current: UserSettings) -> dict[str, Any]:
        known = {provider.id for provider in current.providers}
        unknown = sorted(
            {ref.provider_id for ref in body.features.values() if ref is not None} - known
        )
        if unknown:
            raise HTTPException(status_code=422, detail=f"Unknown provider: {', '.join(unknown)}")
        return {"feature_models": body.features}

    return _features(service.mutate(replace))
