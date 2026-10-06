"""Stand-in for the Codex, Gemini and Claude Code CLIs in tests.

Usage: python fake_cli.py <codex|gemini|claude> <cli args...>. The prompt arrives on stdin.
FAKE_CLI_MODE picks the behavior (ok, garbage, auth_error, sleep) and FAKE_CLI_RECORD,
when set, receives the argv and stdin as JSON so tests can assert on the invocation.
"""

import json
import os
import sys
import time
from pathlib import Path

ANSWER = {"same": True, "confidence": 0.9}


def _record(flavor: str, args: list[str], stdin: str) -> None:
    target = os.environ.get("FAKE_CLI_RECORD")
    if target:
        payload = {"flavor": flavor, "args": args, "stdin": stdin}
        Path(target).write_text(json.dumps(payload), encoding="utf-8")


def _answer_text(mode: str) -> str:
    return "not json at all" if mode == "garbage" else json.dumps(ANSWER)


def _codex(args: list[str], mode: str) -> int:
    if args[:2] == ["login", "status"]:
        if mode == "auth_error":
            print("Not logged in", file=sys.stderr)
            return 1
        print("Logged in using ChatGPT")
        return 0
    if mode == "auth_error":
        print(json.dumps({"type": "error", "message": "401 Unauthorized: please login"}))
        return 1
    output_path = Path(args[args.index("-o") + 1])
    output_path.write_text(_answer_text(mode), encoding="utf-8")
    print(json.dumps({"type": "thread.started", "thread_id": "t1"}))
    usage = {"input_tokens": 120, "cached_input_tokens": 0, "output_tokens": 9}
    print(json.dumps({"type": "turn.completed", "usage": usage}))
    return 0


def _gemini(mode: str) -> int:
    if mode == "auth_error":
        error = {"type": "AuthError", "message": "Please set an Auth method", "code": 41}
        print(json.dumps({"error": error}))
        return 41
    stats = {"models": {"gemini-2.5-flash": {"tokens": {"prompt": 80, "candidates": 7}}}}
    fenced = f"```json\n{_answer_text(mode)}\n```"
    print(json.dumps({"response": fenced, "stats": stats}))
    return 0


def _claude(args: list[str], mode: str) -> int:
    if args[:2] == ["auth", "status"]:
        method = "none" if mode == "auth_error" else "claude.ai"
        print(json.dumps({"loggedIn": method != "none", "authMethod": method}))
        return 1 if mode == "auth_error" else 0
    if mode == "auth_error":
        print(json.dumps({"type": "result", "is_error": True, "result": "Not logged in"}))
        return 1
    body: dict[str, object] = {
        "type": "result",
        "is_error": False,
        "result": _answer_text(mode),
        "usage": {"input_tokens": 50, "output_tokens": 6},
    }
    if mode == "ok":
        body["structured_output"] = ANSWER
    print(json.dumps(body))
    return 0


def main() -> int:
    flavor, args = sys.argv[1], sys.argv[2:]
    mode = os.environ.get("FAKE_CLI_MODE", "ok")
    if args == ["--version"]:
        print(f"{flavor} 9.9.9")
        return 0
    stdin = "" if args[:1] in (["login"], ["auth"]) else sys.stdin.read()
    _record(flavor, args, stdin)
    if mode == "sleep":
        time.sleep(30)
    if flavor == "codex":
        return _codex(args, mode)
    if flavor == "gemini":
        return _gemini(mode)
    return _claude(args, mode)


if __name__ == "__main__":
    sys.exit(main())
