"""Local subscription clients (Codex, Gemini CLI, Claude Code) driven as subprocesses.

Every call uses an argument list, sends the prompt on stdin (no command-line length
limit, no quoting of user text), runs in an empty temporary directory so no project
configuration is picked up, and kills the whole process tree on timeout. Model names
are checked against a conservative pattern because npm-installed clients are `.cmd`
shims on Windows, where `cmd.exe` would interpret shell metacharacters.
"""

import json
import re
import subprocess
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Self

from powereditor.process import hidden_console_flags, kill_tree
from powereditor.providers.base import (
    CheckResult,
    JudgmentRequest,
    JudgmentResult,
    ModelInfo,
    ProviderContext,
    ProviderError,
    TokenUsage,
    Transport,
    build_result,
)
from powereditor.providers.config import ProviderConfig

JUDGE_TIMEOUT_S = 180.0
CHECK_TIMEOUT_S = 30.0
KILL_GRACE_S = 5.0
DETAIL_CHARS = 300
CLI_SUFFIXES = ("", ".exe", ".cmd", ".bat")
_SAFE_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@\[\]-]{0,199}$")
_AUTH_FAILURE = re.compile(
    r"\b(unauthori[sz]ed|not (logged|signed) in|please (log ?in|sign in)"
    r"|authentication (failed|required)|invalid api key)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CliOutput:
    returncode: int
    stdout: str
    stderr: str


def run_cli(
    args: Sequence[str], *, stdin: str | None, cwd: Path | None, timeout_s: float
) -> CliOutput:
    try:
        process = subprocess.Popen(
            list(args),
            stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=cwd,
            creationflags=hidden_console_flags(),
        )
    except FileNotFoundError as exc:
        raise ProviderError("cli_not_found", f"{args[0]} was not found.") from exc
    except OSError as exc:
        raise ProviderError("provider_unavailable", f"Could not start {args[0]}: {exc}.") from exc
    with process:
        try:
            stdout, stderr = process.communicate(stdin, timeout=timeout_s)
        except subprocess.TimeoutExpired as exc:
            _stop(process)
            message = f"The client did not finish within {timeout_s:.0f} s."
            raise ProviderError("provider_timeout", message) from exc
    return CliOutput(process.returncode, stdout, stderr)


def _stop(process: "subprocess.Popen[str]") -> None:
    """Kill the client tree; if a survivor still holds the pipes, close them instead of
    waiting for it."""
    kill_tree(process)
    try:
        process.communicate(timeout=KILL_GRACE_S)
    except subprocess.TimeoutExpired:
        process.kill()
        for pipe in (process.stdin, process.stdout, process.stderr):
            if pipe is not None:
                pipe.close()


def resolve_command(
    executable: str, cli_path: str | None, which: Callable[[str], str | None]
) -> list[str] | None:
    """The client command, or None when it is missing. A configured `cli_path` must be
    the expected client (`codex`, `codex.exe`, ...), never an arbitrary program."""
    if cli_path:
        path = Path(cli_path)
        allowed = {f"{executable}{suffix}" for suffix in CLI_SUFFIXES}
        if path.name.lower() not in allowed:
            raise ProviderError(
                "cli_not_found",
                f"The client path must point to {executable} (got {path.name!r}).",
            )
        return [cli_path] if path.is_file() else None
    found = which(executable)
    return [found] if found else None


def json_object(text: str) -> dict[str, Any] | None:
    """The JSON object in a client's stdout, tolerating log lines around it."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        value = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


class LocalCliProvider:
    kind: ClassVar[str]
    label: ClassVar[str]
    executable: ClassVar[str]
    models: ClassVar[tuple[ModelInfo, ...]]
    transport: Transport = "local_cli"

    def __init__(self, command: list[str] | None, *, timeout_s: float = JUDGE_TIMEOUT_S) -> None:
        self._command = command
        self._timeout_s = timeout_s

    @classmethod
    def from_config(cls, config: ProviderConfig, context: ProviderContext) -> Self:
        return cls(resolve_command(cls.executable, config.cli_path, context.which))

    def list_models(self) -> list[ModelInfo]:
        return list(self.models)

    def check(self) -> CheckResult:
        try:
            output = self._run(["--version"], stdin=None, timeout_s=CHECK_TIMEOUT_S)
            version = first_line(output.stdout) or None
            if output.returncode != 0:
                return CheckResult(ok=False, version=version, detail=self._describe(output))
            authenticated, detail = self._auth_status()
        except ProviderError as exc:
            return CheckResult(ok=False, detail=exc.message)
        return CheckResult(
            ok=authenticated is not False,
            version=version,
            authenticated=authenticated,
            detail=detail,
        )

    def judge(self, request: JudgmentRequest) -> JudgmentResult:
        if not _SAFE_MODEL.fullmatch(request.model):
            raise ProviderError(
                "provider_unavailable", f"Unsupported model name {request.model!r}."
            )
        started = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="powereditor-cli-") as work:
            text, usage = self._invoke(request, Path(work))
        return build_result(text, request.output_schema, started, usage)

    def _auth_status(self) -> tuple[bool | None, str]:
        return None, f"{self.label} has no sign-in status command; sign-in is checked on first use."

    def _invoke(self, request: JudgmentRequest, work: Path) -> tuple[str, TokenUsage | None]:
        raise NotImplementedError

    def _run(
        self,
        args: list[str],
        *,
        stdin: str | None,
        cwd: Path | None = None,
        timeout_s: float | None = None,
    ) -> CliOutput:
        if self._command is None:
            raise ProviderError("cli_not_found", f"{self.label} not found ({self.executable}).")
        return run_cli(
            [*self._command, *args], stdin=stdin, cwd=cwd, timeout_s=timeout_s or self._timeout_s
        )

    def _describe(self, output: CliOutput) -> str:
        text = (output.stderr.strip() or output.stdout.strip())[-DETAIL_CHARS:]
        return f"{self.label} exited with code {output.returncode}: {text or 'no output'}"

    def _failure(
        self, output: CliOutput, message: str | None = None, *, auth: bool = False
    ) -> ProviderError:
        """Map a failed run; `auth` is set by adapters that get a structured auth error."""
        detail = message or self._describe(output)
        if auth or _AUTH_FAILURE.search(detail):
            return ProviderError("provider_unauthorized", detail)
        return ProviderError("provider_unavailable", detail)
