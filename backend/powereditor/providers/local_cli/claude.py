"""Claude Code CLI in print mode, signed in with a Claude account or an API key.

Flags verified 2026-10-06 at https://code.claude.com/docs/en/cli-reference and
https://code.claude.com/docs/en/headless (checked against 2.1.289): `-p` reads the prompt
from stdin, `--output-format json` prints `result`, `is_error` and `usage`, and
`--json-schema` adds a validated `structured_output`. `--tools ""` removes the built-in
tools, `--safe-mode` skips user customizations (hooks, MCP, plugins) while keeping the
normal sign-in, which `--bare` would not. `claude auth status` prints JSON and exits 1
when signed out.
"""

import json
from pathlib import Path

from powereditor.providers.base import (
    JudgmentRequest,
    ModelInfo,
    TokenUsage,
    as_int,
    full_prompt,
)
from powereditor.providers.local_cli.base import CHECK_TIMEOUT_S, LocalCliProvider, json_object

_NOTE = "Claude Code model alias; full model names also work."


class ClaudeCliProvider(LocalCliProvider):
    kind = "anthropic"
    label = "Claude Code CLI"
    executable = "claude"
    models = (
        ModelInfo(id="sonnet", note=_NOTE),
        ModelInfo(id="opus", note=_NOTE),
        ModelInfo(id="haiku", note=_NOTE),
    )

    def _auth_status(self) -> tuple[bool | None, str]:
        output = self._run(["auth", "status"], stdin=None, timeout_s=CHECK_TIMEOUT_S)
        method = (json_object(output.stdout) or {}).get("authMethod")
        if output.returncode == 0 and method not in (None, "none"):
            return True, f"Signed in ({method})."
        return False, "Not signed in; run `claude auth login`."

    def _invoke(self, request: JudgmentRequest, work: Path) -> tuple[str, TokenUsage | None]:
        args = [
            "-p",
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(request.output_schema, separators=(",", ":")),
            "--model",
            request.model,
            "--tools",
            "",
            "--no-session-persistence",
            "--safe-mode",
            "--strict-mcp-config",
            "--disable-slash-commands",
        ]
        output = self._run(args, stdin=full_prompt(request, include_schema=False), cwd=work)
        body = json_object(output.stdout)
        if output.returncode != 0 or body is None or body.get("is_error"):
            message = str(body.get("result")) if body and body.get("result") else None
            raise self._failure(output, message)
        usage = body.get("usage")
        tokens = (
            TokenUsage(
                input_tokens=as_int(usage.get("input_tokens")),
                output_tokens=as_int(usage.get("output_tokens")),
            )
            if isinstance(usage, dict)
            else None
        )
        structured = body.get("structured_output")
        if isinstance(structured, dict):
            return json.dumps(structured, ensure_ascii=False), tokens
        return str(body.get("result") or ""), tokens
