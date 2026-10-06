"""User-facing provider settings: registered providers and per-feature model choices.

API keys never live here; they go to the secret store under `provider:<id>:api_key`.
"""

from typing import Annotated, Literal, get_args
from urllib.parse import urlsplit

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
    custom_base_url_confirmed: bool = False


KNOWN_API_HOSTS: dict[str, frozenset[str]] = {
    "openai": frozenset({"api.openai.com"}),
    "deepseek": frozenset({"api.deepseek.com"}),
    "gemini": frozenset({"generativelanguage.googleapis.com"}),
    "anthropic": frozenset({"api.anthropic.com"}),
    "typesafe": frozenset({"api.typesafe.ai"}),
}
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class ModelRef(CamelModel):
    provider_id: ProviderId
    model: str = Field(min_length=1, max_length=200)


def provider_secret_name(provider_id: str) -> str:
    return f"provider:{provider_id}:api_key"


def base_url_problem(config: ProviderConfig) -> str | None:
    """Why `config.base_url` must not receive the API key, or None when it may.

    The provider's own host is always trusted. Any other host needs the user's explicit
    `custom_base_url_confirmed`, and plain HTTP is only allowed for a loopback server.
    """
    if config.base_url is None:
        return None
    parts = urlsplit(config.base_url)
    host = (parts.hostname or "").lower()
    if not host or parts.username is not None or parts.password is not None:
        return "The base URL must be a plain http(s) URL without credentials."
    if parts.scheme == "http" and host not in LOOPBACK_HOSTS:
        return "Plain http is only allowed for localhost; use https."
    if host in KNOWN_API_HOSTS.get(config.kind, frozenset()) and parts.scheme == "https":
        return None
    if not config.custom_base_url_confirmed:
        return (
            f"{host} is not the official {config.kind} API host; confirm the custom base URL "
            "to send the API key there."
        )
    return None
