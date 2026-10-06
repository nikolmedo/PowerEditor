import subprocess
import sys

from powereditor.process import ProcessScope, process_scope, tracked

SLEEPER = [sys.executable, "-c", "import time; time.sleep(60)"]


def _sleeper() -> "subprocess.Popen[str]":
    return subprocess.Popen(SLEEPER, stdout=subprocess.DEVNULL, text=True)


def test_cancel_kills_tracked_processes() -> None:
    scope = ProcessScope()
    with process_scope(scope), _sleeper() as process, tracked(process):
        scope.cancel()
        assert process.wait(timeout=10) != 0
    assert scope.cancelled


def test_process_started_after_cancel_is_killed_at_once() -> None:
    scope = ProcessScope()
    scope.cancel()
    with process_scope(scope), _sleeper() as process, tracked(process):
        assert process.wait(timeout=10) != 0


def test_tracking_without_scope_leaves_process_alone() -> None:
    with _sleeper() as process:
        with tracked(process):
            assert process.poll() is None
        process.kill()
        process.wait(timeout=10)
