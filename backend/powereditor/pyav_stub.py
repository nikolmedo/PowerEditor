"""A stand-in for PyAV in the frozen build.

The PyAV wheel bundles FFmpeg libraries together with GPL x264 and x265 DLLs, so the
PyInstaller build leaves the `av` package out. PowerEditor never decodes through PyAV (Whisper
reads 16 kHz WAV samples, see `transcribe/local_whisper.py`), but `faster_whisper.audio`
imports `av` at module level. The runtime hook `packaging/rthook_pyav.py` registers this
stand-in so that import succeeds; any actual use of PyAV fails with a clear error.
"""

import importlib.util
from collections.abc import Callable, MutableMapping
from importlib.machinery import ModuleSpec
from types import ModuleType

MESSAGE = (
    "PyAV is not part of the PowerEditor build: audio reaches faster-whisper as WAV samples "
    "decoded with numpy, never through PyAV"
)


class PyAvUnavailableError(RuntimeError):
    pass


class _MissingPyAv(ModuleType):
    def __getattr__(self, name: str) -> object:
        if name.startswith("__"):
            raise AttributeError(name)
        raise PyAvUnavailableError(MESSAGE)


def install(
    modules: MutableMapping[str, ModuleType],
    find_spec: Callable[[str], ModuleSpec | None] = importlib.util.find_spec,
) -> bool:
    """Register the stand-in as `av` unless PyAV is importable; True when it was registered."""
    if "av" in modules or find_spec("av") is not None:
        return False
    modules["av"] = _MissingPyAv("av", MESSAGE)
    return True
