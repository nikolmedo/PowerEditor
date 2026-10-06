"""User-facing provider settings: registered providers and per-feature model choices.

API keys never live here; they go to the secret store under `provider:<id>:api_key`.
"""

from typing import Annotated, Literal, get_args

from pydantic import Field, StringConstraints

from powereditor.models import CamelModel
from powereditor.providers.base import Transport

ProviderId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]
KindName = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9_-]{0,31}$")]

FeatureId = Literal[
    "off_take_detection",
    "idea_completeness",
    "same_take_grey_zone",
    "fluency_score",
    "best_take_choice",
    "topic_change",
    "cta_detection",
]
FEATURE_IDS: tuple[FeatureId, ...] = get_args(FeatureId)


class ProviderConfig(CamelModel):
    id: ProviderId
    kind: KindName
    transport: Transport
    label: str = Field(min_length=1, max_length=80)
    enabled_models: list[str] = Field(default_factory=list)
    cli_path: str | None = None
    base_url: str | None = Field(default=None, pattern=r"^https?://\S+$")


class ModelRef(CamelModel):
    provider_id: ProviderId
    model: str = Field(min_length=1, max_length=200)


def provider_secret_name(provider_id: str) -> str:
    return f"provider:{provider_id}:api_key"
