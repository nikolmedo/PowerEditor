import importlib.util
from pathlib import Path
from types import ModuleType

from powereditor.config import REPO_ROOT


def _build_backend() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "build_backend", REPO_ROOT / "scripts" / "build_backend.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _touch(root: Path, relative: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")


def test_gpl_check_flags_x264_x265_postproc_and_pyav(tmp_path: Path) -> None:
    for relative in (
        "av.libs/libx264-164.dll",
        "av.libs/libx265-215.dll",
        "av/__init__.pyc",
        "postproc-58.dll",
        "ctranslate2/ctranslate2.dll",
        "numpy.libs/libscipy_openblas64_.dll",
    ):
        _touch(tmp_path, relative)

    found = _build_backend().gpl_findings(tmp_path)

    assert found == [
        "av",
        "av.libs",
        "av.libs/libx264-164.dll",
        "av.libs/libx265-215.dll",
        "postproc-58.dll",
    ]


def test_gpl_check_passes_a_clean_build_and_skips_the_noticed_renderer(tmp_path: Path) -> None:
    _touch(tmp_path, "ctranslate2/ctranslate2.dll")
    # Remotion's compositor is a separate GPL program with its own notice and source offer.
    _touch(tmp_path, "composition/node_modules/@remotion/compositor/libx264-164.dll")

    assert _build_backend().gpl_findings(tmp_path) == []
