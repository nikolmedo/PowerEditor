"""Gemini CLI in headless mode, signed in with a Google account or an API key.

Flags verified 2026-10-06 against `gemini --help` (0.61.0) and
https://geminicli.com/docs/cli/headless/: `-p` runs headless and "is appended to input on
stdin", `--output-format json` prints `{"response", "stats", "error"}`, and
`--approval-mode plan` is the read-only mode. The CLI has no JSON Schema flag, so the
schema goes into the prompt and the answer is validated locally.
"""

from pathlib import Path
from typing import Any

from powereditor.providers.base import (
    JudgmentRequest,
    ModelInfo,
    ProviderError,
    TokenUsage,
    as_int,
    full_prompt,
)
from powereditor.providers.local_cli.base import LocalCliProvider, json_object

AUTH_ERROR_TYPE = "AuthError"
HEADLESS_INSTRUCTION = "Follow the instructions above and answer with the JSON object only."
_NOTE = "Common Gemini model; any model name the Gemini CLI accepts also works."


class GeminiCliProvider(LocalCliProvider):
    kind = "gemini"
    label = "Gemini CLI"
    executable = "gemini"
    models = (
        ModelInfo(id="gemini-2.5-pro", note=_NOTE),
        ModelInfo(id="gemini-2.5-flash", note=_NOTE),
    )

    def _invoke(self, request: JudgmentRequest, work: Path) -> tuple[str, TokenUsage | None]:
        args = [
            "-p",
            HEADLESS_INSTRUCTION,
            "--output-format",
            "json",
            "-m",
            request.model,
            "--approval-mode",
            "plan",
        ]
        output = self._run(args, stdin=full_prompt(request, include_schema=True), cwd=work)
        body = json_object(output.stdout)
        error = body.get("error") if body else None
        if output.returncode != 0 or error:
            details = error if isinstance(error, dict) else {}
            message = _error_message(details) if details else None
            raise self._failure(output, message, auth=details.get("type") == AUTH_ERROR_TYPE)
        response = body.get("response") if body else None
        if not isinstance(response, str):
            raise ProviderError("provider_bad_output", "Gemini CLI printed no response.")
        return response, _usage(body.get("stats") if body else None)


def _error_message(error: dict[str, Any]) -> str:
    return f"{error.get('type', 'Error')}: {error.get('message', 'unknown error')}"


def _usage(stats: Any) -> TokenUsage | None:
    """Sum `stats.models.*.tokens`; older builds report flat `inputTokens/outputTokens`."""
    if not isinstance(stats, dict):
        return None
    models = stats.get("models")
    if isinstance(models, dict) and models:
        tokens = [m.get("tokens", {}) for m in models.values() if isinstance(m, dict)]
        return TokenUsage(
            input_tokens=sum(int(t.get("prompt", 0)) for t in tokens),
            output_tokens=sum(int(t.get("candidates", 0)) for t in tokens),
        )
    return TokenUsage(
        input_tokens=as_int(stats.get("inputTokens")),
        output_tokens=as_int(stats.get("outputTokens")),
    )
