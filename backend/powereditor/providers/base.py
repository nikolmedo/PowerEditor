"""The model provider contract shared by API and local CLI transports.

A provider answers one judgment at a time: literal instructions, the minimal state the
question needs, and the JSON Schema of the answer. Every transport returns the answer
parsed and validated against that schema, so features never see free text.
"""

import json
import re
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol

import httpx
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import Field

from powereditor.models import CamelModel

if TYPE_CHECKING:
    from powereditor.providers.config import ProviderConfig

ProviderKind = str
"""Open registry key such as "openai" or "gemini"; new kinds need no code changes here."""

Transport = Literal["api", "local_cli"]
ProviderErrorCode = Literal[
    "provider_unauthorized",
    "provider_unavailable",
    "provider_bad_output",
    "provider_timeout",
    "cli_not_found",
]

_FENCED_JSON = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)


class ProviderError(Exception):
    def __init__(self, code: ProviderErrorCode, message: str) -> None:
        super().__init__(message)
        self.code: ProviderErrorCode = code
        self.message = message


class ModelInfo(CamelModel):
    id: str
    label: str | None = None
    note: str | None = None


class TokenUsage(CamelModel):
    input_tokens: int | None = None
    output_tokens: int | None = None


class CheckResult(CamelModel):
    ok: bool
    detail: str
    version: str | None = None
    authenticated: bool | None = None


class JudgmentRequest(CamelModel):
    instructions: str = Field(min_length=1)
    state: dict[str, Any]
    output_schema: dict[str, Any]
    model: str = Field(min_length=1)
    temperature: float | None = Field(default=0.0, ge=0.0, le=2.0)
    """None leaves the provider default; local CLIs ignore it."""


class JudgmentResult(CamelModel):
    output: dict[str, Any]
    raw_text: str
    usage: TokenUsage | None = None
    latency_s: float


class ModelProvider(Protocol):
    @property
    def kind(self) -> ProviderKind: ...

    @property
    def transport(self) -> Transport: ...

    def check(self) -> CheckResult:
        """Cheap readiness probe: credentials or local client, without asking a question."""
        ...

    def list_models(self) -> list[ModelInfo]: ...

    def judge(self, request: JudgmentRequest) -> JudgmentResult: ...


@dataclass(frozen=True)
class ProviderContext:
    """Runtime dependencies a factory needs; tests swap the network, clock and PATH lookup."""

    api_key: str | None = None
    http_transport: httpx.BaseTransport | None = None
    sleep: Callable[[float], None] = time.sleep
    which: Callable[[str], str | None] = field(default=shutil.which)


ProviderFactory = Callable[["ProviderConfig", ProviderContext], ModelProvider]


def system_prompt(request: JudgmentRequest, *, include_schema: bool) -> str:
    """Instructions plus the output contract; the schema goes in when the transport
    cannot enforce it natively."""
    parts = [request.instructions.strip(), "Answer with a single JSON object and nothing else."]
    if include_schema:
        schema = json.dumps(request.output_schema, indent=2, ensure_ascii=False)
        parts.append(f"The JSON object must match this JSON Schema:\n{schema}")
    return "\n\n".join(parts)


def user_prompt(request: JudgmentRequest) -> str:
    return "Input (JSON):\n" + json.dumps(request.state, indent=2, ensure_ascii=False)


def full_prompt(request: JudgmentRequest, *, include_schema: bool) -> str:
    """Single-text prompt for transports without a separate system message."""
    return f"{system_prompt(request, include_schema=include_schema)}\n\n{user_prompt(request)}"


def parse_output(text: str, schema: dict[str, Any]) -> dict[str, Any]:
    """Extract the JSON object from a model answer and validate it against `schema`."""
    candidate = text.strip()
    if fenced := _FENCED_JSON.search(candidate):
        candidate = fenced.group(1)
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ProviderError("provider_bad_output", "The answer is not valid JSON.") from exc
    if not isinstance(value, dict):
        raise ProviderError("provider_bad_output", "The answer is not a JSON object.")
    validate_output(value, schema)
    return value


def validate_output(value: dict[str, Any], schema: dict[str, Any]) -> None:
    try:
        errors = sorted(Draft202012Validator(schema).iter_errors(value), key=str)
    except SchemaError as exc:
        raise ProviderError("provider_bad_output", f"Invalid output schema: {exc.message}") from exc
    if errors:
        first = errors[0]
        where = "/".join(str(part) for part in first.absolute_path) or "<root>"
        raise ProviderError(
            "provider_bad_output",
            f"The answer does not match the schema at {where}: {first.message}",
        )


def build_result(
    text: str, schema: dict[str, Any], started: float, usage: TokenUsage | None
) -> JudgmentResult:
    if not text.strip():
        raise ProviderError("provider_bad_output", "The provider returned an empty answer.")
    return JudgmentResult(
        output=parse_output(text, schema),
        raw_text=text,
        usage=usage,
        latency_s=time.perf_counter() - started,
    )


def as_int(value: Any) -> int | None:
    return value if isinstance(value, int) else None
