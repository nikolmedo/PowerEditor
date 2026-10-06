"""Entry point of the frozen build: the `powereditor` CLI.

Started without arguments (a double-click), it serves the app and opens the browser.
The desktop shell starts `powereditor-sidecar.exe serve --port 0 --parent-pid <pid>`.
"""

import multiprocessing
import sys

from powereditor.cli import app

if __name__ == "__main__":
    multiprocessing.freeze_support()
    app(args=sys.argv[1:] or ["serve", "--open"], prog_name="powereditor")
