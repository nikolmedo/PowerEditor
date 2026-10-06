import importlib
import sys
from importlib.machinery import ModuleSpec
from types import ModuleType

import pytest

from powereditor.pyav_stub import PyAvUnavailableError, install


def _not_found(name: str) -> ModuleSpec | None:
    return None


def test_install_registers_a_stand_in_when_pyav_is_missing() -> None:
    modules: dict[str, ModuleType] = {}

    assert install(modules, find_spec=_not_found) is True

    stub = modules["av"]
    with pytest.raises(PyAvUnavailableError, match="PyAV is not part of the PowerEditor build"):
        stub.open("clip.mp4")
    with pytest.raises(AttributeError):
        _ = stub.__path__


def test_install_leaves_a_real_pyav_alone() -> None:
    real = ModuleType("av")
    modules = {"av": real}

    assert install(modules, find_spec=_not_found) is False
    assert install({}, find_spec=lambda name: ModuleSpec(name, None)) is False
    assert modules["av"] is real


def test_faster_whisper_imports_over_the_stand_in(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [
        m for m in sys.modules if m == "faster_whisper" or m.startswith("faster_whisper.")
    ]:
        monkeypatch.delitem(sys.modules, name)
    modules: dict[str, ModuleType] = {}
    install(modules, find_spec=_not_found)
    monkeypatch.setitem(sys.modules, "av", modules["av"])

    faster_whisper = importlib.import_module("faster_whisper")

    assert faster_whisper.WhisperModel.__name__ == "WhisperModel"
    with pytest.raises(PyAvUnavailableError):
        faster_whisper.decode_audio("clip.wav")
