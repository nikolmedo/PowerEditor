"""PyInstaller runtime hook: register the PyAV stand-in before the app imports faster-whisper.

The build excludes PyAV (see powereditor.spec and powereditor/pyav_stub.py).
"""

import sys

from powereditor.pyav_stub import install

install(sys.modules)
