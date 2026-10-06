"""Shared HTTP plumbing for API providers: auth check, bounded retry, error mapping.

Only rate limits (429), overload and server errors (5xx, 529) and failed connections are
retried, with exponential backoff. A read timeout, or a connection that broke after a
POST was sent, is not retried: the request may already be running and billing on the
provider side. The API key only ever goes in request headers, never in messages.
"""

from typing import Any

import httpx

from powereditor.providers.base import (
    CheckResult,
    ModelInfo,
    ProviderContext,
    ProviderError,
    Transport,
)

REQUEST_TIMEOUT_S = 60.0
MAX_ATTEMPTS = 3
BACKOFF_S = 1.0
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504, 529})


class ApiProvider:
    """Base for HTTP providers; subclasses set `kind`, `label` and the endpoints."""

    kind = "api"
    label = "API"
    transport: Transport = "api"

    def __init__(self, base_url: str, context: ProviderContext) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = context.api_key
        self._transport = context.http_transport
        self._sleep = context.sleep

    def _headers(self, api_key: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {api_key}"}

    def _is_auth_failure(self, response: httpx.Response) -> bool:
        return response.status_code in (401, 403)

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self._api_key:
            raise ProviderError("provider_unauthorized", f"No {self.label} API key is configured.")
        last_error: ProviderError | None = None
        with httpx.Client(transport=self._transport, timeout=REQUEST_TIMEOUT_S) as client:
            for attempt in range(MAX_ATTEMPTS):
                if attempt:
                    self._sleep(BACKOFF_S * 2 ** (attempt - 1))
                try:
                    response = client.request(
                        method,
                        f"{self._base_url}{path}",
                        json=body,
                        params=params,
                        headers=self._headers(self._api_key),
                    )
                except httpx.ConnectTimeout as exc:
                    last_error = self._unavailable(f"connection timed out ({type(exc).__name__})")
                    continue
                except httpx.TimeoutException as exc:
                    message = f"{self.label} did not answer in time."
                    raise ProviderError("provider_timeout", message) from exc
                except httpx.TransportError as exc:
                    last_error = self._unavailable(f"connection failed ({type(exc).__name__})")
                    if method != "GET" and not isinstance(exc, httpx.ConnectError):
                        raise last_error from exc
                    continue
                if response.status_code in RETRYABLE_STATUS:
                    last_error = self._unavailable(f"HTTP {response.status_code}")
                    continue
                return self._parse(response)
        assert last_error is not None
        raise last_error

    def _parse(self, response: httpx.Response) -> dict[str, Any]:
        if self._is_auth_failure(response):
            raise ProviderError(
                "provider_unauthorized",
                f"{self.label} rejected the API key (HTTP {response.status_code}).",
            )
        if not response.is_success:
            raise self._unavailable(f"HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError("provider_bad_output", f"{self.label} sent invalid JSON.") from exc
        if not isinstance(data, dict):
            raise ProviderError("provider_bad_output", f"{self.label} sent an unexpected body.")
        return data

    def _unavailable(self, reason: str) -> ProviderError:
        return ProviderError("provider_unavailable", f"{self.label} request failed: {reason}.")

    def list_models(self) -> list[ModelInfo]:
        raise NotImplementedError

    def check(self) -> CheckResult:
        try:
            count = len(self.list_models())
        except ProviderError as exc:
            return CheckResult(ok=False, detail=exc.message, authenticated=_auth_state(exc))
        noun = "model" if count == 1 else "models"
        return CheckResult(
            ok=True, authenticated=True, detail=f"{self.label} lists {count} {noun}."
        )


def _auth_state(error: ProviderError) -> bool | None:
    return False if error.code == "provider_unauthorized" else None
