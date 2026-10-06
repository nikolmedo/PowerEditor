"""Run `powereditor serve` as a sidecar of the desktop shell.

The shell starts `powereditor serve --port 0 --parent-pid <its pid>` and reads stdout until
one line `POWEREDITOR_READY {"port": N, "token": "..."}`: the server binds a free loopback
port itself, so the line is printed only once the ASGI lifespan startup finished and the
socket accepts connections. With `--parent-pid` the server watches the parent and shuts down
cleanly (running jobs are cancelled) once it is gone, so a crashed shell never leaves an
orphan backend. The watch holds the parent's process handle on Windows (and follows
`getppid()` elsewhere), so a new process that reuses the PID is never taken for the parent.
"""

import json
import os
import socket
import sys
import threading
import time
from collections.abc import Callable

import uvicorn

# Waits up to the given seconds for the parent to exit; True once it is gone.
ExitWaiter = Callable[[float], bool]

READY_PREFIX = "POWEREDITOR_READY"
PARENT_POLL_S = 1.0


def ready_line(port: int, token: str | None) -> str:
    """The READY line; `token` is None when the server does not require one."""
    return f"{READY_PREFIX} {json.dumps({'port': port, 'token': token})}"


def announce(line: str) -> None:
    """Print one line for the parent; a windowed build may have no stdout at all."""
    if sys.stdout is not None:
        sys.stdout.write(f"{line}\n")
        sys.stdout.flush()


def bind_loopback(host: str, port: int) -> socket.socket:
    """A listening-ready socket on `host:port`; port 0 picks a free one."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
    except OSError:
        sock.close()
        raise
    return sock


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _SYNCHRONIZE = 0x00100000
    _STILL_ACTIVE = 259
    _ERROR_ACCESS_DENIED = 5
    _WAIT_TIMEOUT = 0x102

    def _process_alive(pid: int) -> bool:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ctypes.get_last_error() == _ERROR_ACCESS_DENIED
        try:
            code = wintypes.DWORD()
            return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and (
                code.value == _STILL_ACTIVE
            )
        finally:
            kernel32.CloseHandle(handle)

    def _exit_waiter(pid: int) -> ExitWaiter | None:
        """Wait on the parent's handle, opened now: a reused PID cannot fool it."""
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        handle = kernel32.OpenProcess(_SYNCHRONIZE, False, pid)
        if not handle:
            return None

        def wait(timeout_s: float) -> bool:
            gone = kernel32.WaitForSingleObject(handle, int(timeout_s * 1000)) != _WAIT_TIMEOUT
            if gone:
                kernel32.CloseHandle(handle)
            return bool(gone)

        return wait

else:

    def _exit_waiter(pid: int) -> ExitWaiter | None:
        """When `pid` is the real parent, its death reparents this process."""
        if pid != os.getppid():
            return None

        def wait(timeout_s: float) -> bool:
            time.sleep(timeout_s)
            return os.getppid() != pid

        return wait

    def _process_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True


def parent_alive(pid: int) -> bool:
    return pid > 0 and _process_alive(pid)


def watch_parent(
    pid: int, on_exit: Callable[[], None], poll_s: float = PARENT_POLL_S
) -> threading.Thread:
    """Call `on_exit` (once, from a daemon thread) when process `pid` is gone."""
    waiter = _exit_waiter(pid) if pid > 0 else None

    def poll_pid(timeout_s: float) -> bool:
        if not parent_alive(pid):
            return True
        time.sleep(timeout_s)
        return False

    wait = waiter or poll_pid

    def poll() -> None:
        while not wait(poll_s):
            pass
        on_exit()

    thread = threading.Thread(target=poll, name="parent-watch", daemon=True)
    thread.start()
    return thread


class AnnouncingServer(uvicorn.Server):
    """A uvicorn server that calls `on_started` once its sockets accept connections."""

    def __init__(self, config: uvicorn.Config, on_started: Callable[[], None]) -> None:
        super().__init__(config)
        self._on_started = on_started

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        await super().startup(sockets=sockets)
        if self.started:
            self._on_started()
