import asyncio
import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi import FastAPI

from powereditor import sidecar
from powereditor.sidecar import (
    READY_PREFIX,
    AnnouncingServer,
    bind_loopback,
    parent_alive,
    ready_line,
    watch_parent,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]
STARTUP_TIMEOUT_S = 60


def test_ready_line_is_one_prefixed_json_object() -> None:
    line = ready_line(51234, "secret")

    prefix, payload = line.split(" ", 1)
    assert prefix == READY_PREFIX
    assert json.loads(payload) == {"port": 51234, "token": "secret"}
    assert "\n" not in line


def test_port_zero_binds_a_free_loopback_port() -> None:
    with bind_loopback("127.0.0.1", 0) as sock:
        host, port = sock.getsockname()[:2]

    assert host == "127.0.0.1"
    assert port > 0


def test_parent_alive_follows_a_process_until_it_exits() -> None:
    child = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdin.read()"], stdin=subprocess.PIPE
    )
    try:
        assert parent_alive(child.pid)
    finally:
        assert child.stdin is not None
        child.stdin.close()
        child.wait(10)

    assert not parent_alive(child.pid)
    assert parent_alive(os.getpid())


def test_watch_parent_calls_back_once_the_parent_is_gone() -> None:
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait(10)
    gone: list[bool] = []

    watch_parent(child.pid, lambda: gone.append(True), poll_s=0.05).join(5)

    assert gone == [True]


@pytest.mark.skipif(sys.platform != "win32", reason="process handles are a Windows API")
def test_watch_parent_is_not_fooled_by_a_reused_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    """The watch holds the parent's process handle, so a new process reusing the PID is
    never mistaken for the parent."""
    child = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdin.read()"], stdin=subprocess.PIPE
    )
    gone = threading.Event()
    watcher = watch_parent(child.pid, gone.set, poll_s=0.05)
    monkeypatch.setattr(sidecar, "parent_alive", lambda pid: True)  # the PID is "taken" again

    assert child.stdin is not None
    child.stdin.close()
    child.wait(10)
    watcher.join(5)

    assert gone.is_set()


def run_announcing(app: FastAPI) -> list[bool]:
    """Serve `app` until it announces itself (then stop) or gives up; return the flags seen."""
    seen: list[bool] = []
    sock = bind_loopback("127.0.0.1", 0)
    config = uvicorn.Config(app, log_level="critical")
    server = AnnouncingServer(config, on_started=lambda: seen.append(app.state.ready))

    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not seen and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.02)
    server.should_exit = True
    thread.join(10)
    return seen


def test_ready_is_announced_after_the_lifespan_startup() -> None:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await asyncio.sleep(0.2)
        app.state.ready = True
        yield

    app = FastAPI(lifespan=lifespan)
    app.state.ready = False

    assert run_announcing(app) == [True]


def test_ready_is_never_announced_when_the_lifespan_startup_fails() -> None:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        raise RuntimeError("startup failed")
        yield

    app = FastAPI(lifespan=lifespan)
    app.state.ready = False

    assert run_announcing(app) == []


def test_serve_announces_its_port_and_exits_with_its_parent() -> None:
    """End to end: `serve --port 0 --parent-pid` from a real process."""
    parent = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdin.read()"], stdin=subprocess.PIPE
    )
    server = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "from powereditor.cli import app; app()",
            "serve",
            "--port",
            "0",
            "--parent-pid",
            str(parent.pid),
        ],
        cwd=BACKEND_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        assert server.stdout is not None
        deadline = time.monotonic() + STARTUP_TIMEOUT_S
        line = ""
        while time.monotonic() < deadline and not line.startswith(READY_PREFIX):
            line = server.stdout.readline()
            if not line and server.poll() is not None:
                break
        assert line.startswith(READY_PREFIX), line
        ready = json.loads(line.split(" ", 1)[1])
        health_url = f"http://127.0.0.1:{ready['port']}/api/health"
        assert httpx.get(health_url, timeout=10).status_code == 401
        health = httpx.get(health_url, headers={"X-PowerEditor-Token": ready["token"]}, timeout=10)
        assert health.json()["status"] == "ok"
        assert len(ready["token"]) >= 32

        assert parent.stdin is not None
        parent.stdin.close()
        parent.wait(10)
        assert server.wait(30) == 0
    finally:
        for process in (parent, server):
            if process.poll() is None:
                process.kill()
                process.wait(10)


@pytest.mark.parametrize("pid", [0, -1])
def test_invalid_pids_are_never_alive(pid: int) -> None:
    assert not parent_alive(pid)
