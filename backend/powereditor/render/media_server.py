"""Loopback HTTP server that exposes a project's media folder to the headless renderer.

Remotion's browser cannot load local Windows paths, so renders stream mezzanines
from `http://127.0.0.1:<port>/<file name>` for the lifetime of the render.
"""

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

LOOPBACK = "127.0.0.1"


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return None


@contextmanager
def serve_directory(directory: Path) -> Iterator[str]:
    """Serve `directory` read-only on an ephemeral loopback port; yields the base URL."""
    handler = partial(_QuietHandler, directory=str(directory))
    server = ThreadingHTTPServer((LOOPBACK, 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://{LOOPBACK}:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
