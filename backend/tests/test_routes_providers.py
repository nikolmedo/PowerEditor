import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from powereditor.api.app import create_app
from powereditor.config import Settings
from powereditor.paths import AppPaths
from powereditor.providers.config import ProviderConfig
from powereditor.settings_store import InMemorySecretStore, SettingsService
from tests.api_client import local_client

KEY = "sk-provider-secret"


def _service(data_dir: Path) -> SettingsService:
    return SettingsService(
        paths=AppPaths(data_dir=data_dir),
        secrets=InMemorySecretStore(),
        env=Settings(_env_file=None),
        cuda_available=lambda: False,
    )


def _models_handler(request: httpx.Request) -> httpx.Response:
    if request.headers.get("authorization") != f"Bearer {KEY}":
        return httpx.Response(401, json={"error": {"message": "bad key"}})
    return httpx.Response(200, json={"data": [{"id": "gpt-b"}, {"id": "gpt-a"}]})


@pytest.fixture
def service(tmp_path: Path) -> SettingsService:
    return _service(tmp_path)


@pytest.fixture
def client(service: SettingsService) -> TestClient:
    app = create_app(
        settings_service=service, provider_transport=httpx.MockTransport(_models_handler)
    )
    return local_client(app)


def _create(client: TestClient, **body: Any) -> dict[str, Any]:
    payload = {"kind": "openai", "transport": "api", "label": "OpenAI", **body}
    response = client.post("/api/providers", json=payload)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def test_lists_provider_kinds_with_transports(client: TestClient) -> None:
    kinds = {item["kind"]: item["transports"] for item in client.get("/api/providers/kinds").json()}

    assert kinds["openai"] == ["api", "local_cli"]
    assert kinds["deepseek"] == ["api"]


def test_provider_crud_round_trip(client: TestClient, service: SettingsService) -> None:
    created = _create(client, enabledModels=["gpt-a"])

    assert created["id"] == "openai-api"
    assert created["apiKeySet"] is False
    assert _create(client)["id"] == "openai-api-2"

    patched = client.patch("/api/providers/openai-api", json={"label": "Work"}).json()
    assert patched["label"] == "Work"
    assert patched["enabledModels"] == ["gpt-a"]
    assert [p["id"] for p in client.get("/api/providers").json()] == ["openai-api", "openai-api-2"]
    stored = json.loads(service.paths.settings_file.read_text(encoding="utf-8"))
    assert stored["providers"][0]["label"] == "Work"

    assert client.delete("/api/providers/openai-api-2").status_code == 204
    assert client.get("/api/providers/openai-api-2").status_code == 404


def test_create_rejects_unknown_kind_transport_and_duplicate_id(client: TestClient) -> None:
    base = {"label": "x"}
    unknown = client.post("/api/providers", json={**base, "kind": "acme", "transport": "api"})
    no_cli = client.post(
        "/api/providers", json={**base, "kind": "deepseek", "transport": "local_cli"}
    )
    _create(client, id="mine")
    duplicate = client.post(
        "/api/providers", json={**base, "id": "mine", "kind": "openai", "transport": "api"}
    )

    assert unknown.status_code == 422
    assert no_cli.status_code == 422
    assert duplicate.status_code == 409


def test_api_key_is_stored_as_secret_and_never_returned(
    client: TestClient, service: SettingsService
) -> None:
    _create(client)

    stored = client.put("/api/providers/openai-api/api-key", json={"value": f"  {KEY} "})
    listing = client.get("/api/providers").text

    assert stored.json() == {"set": True}
    assert service.provider_api_key("openai-api") == KEY
    assert KEY not in listing
    assert KEY not in service.paths.settings_file.read_text(encoding="utf-8")
    assert client.delete("/api/providers/openai-api/api-key").json() == {"set": False}
    assert service.provider_api_key("openai-api") is None


def test_validation_errors_do_not_echo_the_key(client: TestClient) -> None:
    _create(client)

    response = client.put("/api/providers/openai-api/api-key", json={"value": KEY, "x": KEY})

    assert response.status_code == 422
    assert KEY not in response.text


def test_test_endpoint_and_models_use_the_stored_key(client: TestClient) -> None:
    _create(client)

    before = client.post("/api/providers/openai-api/test").json()
    client.put("/api/providers/openai-api/api-key", json={"value": KEY})
    after = client.post("/api/providers/openai-api/test").json()
    models = client.get("/api/providers/openai-api/models").json()

    assert before["ok"] is False
    assert before["code"] == "provider_unauthorized"
    assert after["ok"] is True
    assert [m["id"] for m in models] == ["gpt-a", "gpt-b"]


def test_models_endpoint_reports_provider_errors(client: TestClient) -> None:
    _create(client)

    response = client.get("/api/providers/openai-api/models")

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "provider_unauthorized"


def test_feature_models_default_to_heuristic_and_validate_references(client: TestClient) -> None:
    _create(client, enabledModels=["gpt-a"])

    initial = client.get("/api/features/models").json()["features"]
    assert initial["best_take_choice"] is None
    assert len(initial) == 7

    ref = {"providerId": "openai-api", "model": "gpt-a"}
    saved = client.put("/api/features/models", json={"features": {"best_take_choice": ref}})
    bad = client.put(
        "/api/features/models",
        json={"features": {"fluency_score": {"providerId": "nope", "model": "x"}}},
    )

    assert saved.json()["features"]["best_take_choice"] == ref
    assert saved.json()["features"]["cta_detection"] is None
    assert bad.status_code == 422


def test_deleting_a_provider_clears_its_secret_and_feature_assignments(
    client: TestClient, service: SettingsService
) -> None:
    _create(client)
    client.put("/api/providers/openai-api/api-key", json={"value": KEY})
    ref = {"providerId": "openai-api", "model": "gpt-a"}
    client.put("/api/features/models", json={"features": {"topic_change": ref}})

    client.delete("/api/providers/openai-api")

    assert service.provider_api_key("openai-api") is None
    assert client.get("/api/features/models").json()["features"]["topic_change"] is None


def test_feature_model_resolution_falls_back_when_provider_is_missing(
    service: SettingsService,
) -> None:
    provider = ProviderConfig(id="p1", kind="openai", transport="api", label="P1")
    service.update({"providers": [provider.model_dump(by_alias=True)]})
    service.update(
        {
            "featureModels": {
                "cta_detection": {"providerId": "p1", "model": "m"},
                "topic_change": {"providerId": "gone", "model": "m"},
            }
        }
    )

    resolved = service.feature_model("cta_detection")

    assert resolved is not None
    assert (resolved[0].id, resolved[1]) == ("p1", "m")
    assert service.feature_model("topic_change") is None
    assert service.feature_model("fluency_score") is None


def test_duplicate_provider_ids_are_rejected(service: SettingsService) -> None:
    provider = {"id": "p1", "kind": "openai", "transport": "api", "label": "P1"}

    with pytest.raises(ValueError, match="duplicate provider id"):
        service.update({"providers": [provider, provider]})
