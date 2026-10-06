import subprocess
import sys


def kill_tree(process: "subprocess.Popen[str]") -> None:
    """Kill a child process and its descendants so its pipes close."""
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True, check=False
        )
    process.kill()
