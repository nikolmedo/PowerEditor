"""Codex CLI (`codex exec`), signed in with a ChatGPT plan or `CODEX_API_KEY`.

Flags verified 2026-10-06 at https://learn.chatgpt.com/docs/non-interactive-mode:
`--json` (JSONL events), `--output-schema <file>`, `-o <file>` (final message),
`--sandbox read-only`, `--skip-git-repo-check`, `--ephemeral`, `-` (prompt on stdin).
The answer is read from the `-o` file; token usage from the `turn.completed` event.
"""

import json
from pathlib import Path
from typing import Any

from powereditor.providers.base import (
    JudgmentRequest,
    ModelInfo,
    TokenUsage,
    as_int,
    full_prompt,
)
from powereditor.providers.local_cli.base import (
    CHECK_TIMEOUT_S,
    LocalCliProvider,
    first_line,
)

_NOTE = "Common Codex model; any model name your Codex plan accepts also works."


class CodexCliProvider(LocalCliProvider):
    kind = "openai"
    label = "Codex CLI"
    executable = "codex"
    models = (ModelInfo(id="gpt-5-codex", note=_NOTE), ModelInfo(id="gpt-5", note=_NOTE))

    def _auth_status(self) -> tuple[bool | None, str]:
        output = self._run(["login", "status"], stdin=None, timeout_s=CHECK_TIMEOUT_S)
        detail = first_line(output.stdout) or first_line(output.stderr)
        if output.returncode == 0:
            return True, detail or "Signed in."
        return False, detail or "Not signed in; run `codex login`."

    def _invoke(self, request: JudgmentRequest, work: Path) -> tuple[str, TokenUsage | None]:
        schema_path = work / "schema.json"
        answer_path = work / "answer.json"
        schema_path.write_text(json.dumps(request.output_schema), encoding="utf-8")
        args = [
            "exec",
            "--json",
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "--ephemeral",
            "--output-schema",
            str(schema_path),
            "-o",
            str(answer_path),
            "-m",
            request.model,
            "-",
        ]
        output = self._run(args, stdin=full_prompt(request, include_schema=False), cwd=work)
        events = _events(output.stdout)
        if output.returncode != 0:
            raise self._failure(output, _error_message(events))
        if not answer_path.is_file():
            return "", None
        return answer_path.read_text(encoding="utf-8"), _usage(events)


def _events(stdout: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _error_message(events: list[dict[str, Any]]) -> str | None:
    for event in reversed(events):
        if event.get("type") == "error" and isinstance(event.get("message"), str):
            return str(event["message"])
        error = event.get("error")
        if event.get("type") == "turn.failed" and isinstance(error, dict):
            return str(error.get("message", "turn failed"))
    return None


def _usage(events: list[dict[str, Any]]) -> TokenUsage | None:
    for event in reversed(events):
        usage = event.get("usage")
        if event.get("type") == "turn.completed" and isinstance(usage, dict):
            return TokenUsage(
                input_tokens=as_int(usage.get("input_tokens")),
                output_tokens=as_int(usage.get("output_tokens")),
            )
    return None
