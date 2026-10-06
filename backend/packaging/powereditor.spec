# PyInstaller spec for the PowerEditor backend (onedir).
#
# Build it with `python scripts/build_backend.py` from the repo root, which builds the web app
# and passes its folder as POWEREDITOR_BUILD_WEB (web/dist).
# The staged Remotion renderer is copied into `_internal/composition` by the build script after
# PyInstaller runs: as data here, PyInstaller would scan its native files (compositor, ffmpeg)
# for DLL dependencies and copy unrelated system DLLs next to the executable.
#
# Output: dist/backend/powereditor/ with two executables over the same files:
#   powereditor.exe          console build (CLI, debugging)
#   powereditor-sidecar.exe  windowed build the desktop shell starts (no console window)
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

SPEC_DIR = Path(SPECPATH)  # noqa: F821 (defined by PyInstaller)
BACKEND_DIR = SPEC_DIR.parent
WEB_DIR = Path(os.environ["POWEREDITOR_BUILD_WEB"])

datas = [
    (str(WEB_DIR), "powereditor/web"),
    # Silero VAD ONNX model.
    *collect_data_files("faster_whisper"),
    # JSON Schema metaschemas loaded at runtime.
    *collect_data_files("jsonschema_specifications"),
    # importlib.metadata lookups: the app version, keyring backends (entry points).
    *copy_metadata("powereditor"),
    *copy_metadata("keyring"),
    *copy_metadata("fastapi"),
]
hiddenimports = [
    # uvicorn imports the app factory from a string.
    "powereditor.api.app",
    "keyring.backends.Windows",
]
# Optional extras stay out even when installed in the build environment.
excludes = ["cv2", "sentence_transformers", "torch", "opentimelineio", "tkinter", "pytest"]
# PyAV stays out too: its wheel bundles GPL x264/x265 DLLs, and PowerEditor never decodes
# through it. The runtime hook lets faster-whisper import without it (powereditor/pyav_stub.py).
excludes += ["av"]
hiddenimports += ["powereditor.pyav_stub"]

a = Analysis(  # noqa: F821
    [str(SPEC_DIR / "entry.py")],
    pathex=[str(BACKEND_DIR)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    runtime_hooks=[str(SPEC_DIR / "rthook_pyav.py")],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821


def executable(name: str, console: bool) -> object:
    return EXE(  # noqa: F821
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=name,
        console=console,
        upx=False,
    )


coll = COLLECT(  # noqa: F821
    executable("powereditor", console=True),
    executable("powereditor-sidecar", console=False),
    a.binaries,
    a.datas,
    upx=False,
    name="powereditor",
)
