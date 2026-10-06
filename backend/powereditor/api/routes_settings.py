from typing import Annotated, Any, cast

import httpx
import keyring.errors
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import ValidationError

from powereditor.models import CamelModel
from powereditor.settings_store import (
    SECRET_NAMES,
    SecretName,
    SecretSource,
    SettingsService,
    UserSettings,
)

OPENAI_MODELS_URL = "https://api.openai.com/v1/models"
OPENAI_TEST_TIMEOUT_SECONDS = 10.0

router = APIRouter(prefix="/api")


class SecretStatus(CamelModel):
    set: bool
    source: SecretSource | None


class SecretsStatus(CamelModel):
    openai_api_key: SecretStatus
    typesafe_api_key: SecretStatus


class SettingsResponse(CamelModel):
    settings: UserSettings
    resolved_whisper_model: str
    secrets: SecretsStatus


class SecretValue(CamelModel):
    value: str


class KeyTestResult(CamelModel):
    ok: bool
    detail: str


def get_service(request: Request) -> SettingsService:
    return cast(SettingsService, request.app.state.settings_service)


ServiceDep = Annotated[SettingsService, Depends(get_service)]


def _secret_status(service: SettingsService, name: SecretName) -> SecretStatus:
    source = service.secret_source(name)
    return SecretStatus(set=source is not None, source=source)


def _settings_response(service: SettingsService) -> SettingsResponse:
    return SettingsResponse(
        settings=service.get_effective(),
        resolved_whisper_model=service.resolved_whisper_model(),
        secrets=SecretsStatus(
            openai_api_key=_secret_status(service, "openai_api_key"),
            typesafe_api_key=_secret_status(service, "typesafe_api_key"),
        ),
    )


def _secret_name(name: str) -> SecretName:
    if name not in SECRET_NAMES:
        raise HTTPException(status_code=404, detail=f"Unknown secret '{name}'")
    return name


@router.get("/settings")
def read_settings(service: ServiceDep) -> SettingsResponse:
    return _settings_response(service)


@router.patch("/settings")
def update_settings(
    service: ServiceDep, changes: Annotated[dict[str, Any], Body()]
) -> SettingsResponse:
    try:
        service.update(changes)
    except ValidationError as exc:
        errors = exc.errors(include_url=False, include_context=False, include_input=False)
        raise HTTPException(status_code=422, detail=errors) from exc
    return _settings_response(service)


@router.put("/secrets/{name}")
def store_secret(name: str, body: SecretValue, service: ServiceDep) -> SecretStatus:
    secret_name = _secret_name(name)
    try:
        service.set_secret(secret_name, body.value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Secret value must not be empty") from exc
    except keyring.errors.KeyringError as exc:
        raise HTTPException(status_code=503, detail="Secure storage is unavailable") from exc
    return _secret_status(service, secret_name)


@router.delete("/secrets/{name}")
def delete_secret(name: str, service: ServiceDep) -> SecretStatus:
    secret_name = _secret_name(name)
    try:
        service.clear_secret(secret_name)
    except keyring.errors.KeyringError as exc:
        raise HTTPException(status_code=503, detail="Secure storage is unavailable") from exc
    return _secret_status(service, secret_name)


@router.post("/secrets/openai_api_key/test")
def test_openai_key(request: Request, service: ServiceDep) -> KeyTestResult:
    api_key = service.get_secret("openai_api_key")
    if not api_key:
        return KeyTestResult(ok=False, detail="No OpenAI API key is configured.")
    transport: httpx.BaseTransport | None = request.app.state.openai_transport
    try:
        with httpx.Client(transport=transport, timeout=OPENAI_TEST_TIMEOUT_SECONDS) as client:
            response = client.get(OPENAI_MODELS_URL, headers={"Authorization": f"Bearer {api_key}"})
    except httpx.HTTPError as exc:
        return KeyTestResult(ok=False, detail=f"Could not reach OpenAI ({type(exc).__name__}).")
    if response.is_success:
        return KeyTestResult(ok=True, detail="OpenAI accepted the API key.")
    if response.status_code in (401, 403):
        return KeyTestResult(
            ok=False, detail=f"OpenAI rejected the API key (HTTP {response.status_code})."
        )
    return KeyTestResult(ok=False, detail=f"OpenAI returned HTTP {response.status_code}.")
