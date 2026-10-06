import importlib.util
from pathlib import Path
from types import ModuleType

from powereditor.config import REPO_ROOT


def _build_installer() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "build_installer", REPO_ROOT / "scripts" / "build_installer.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_nsis_license_is_utf8_with_bom_and_crlf(tmp_path: Path) -> None:
    source = tmp_path / "LICENSE"
    source.write_bytes("Required Notice: Copyright 2026 Nicolás Olmedo\n\nTerms\r\n".encode())
    target = tmp_path / "build" / "license.txt"

    _build_installer().write_nsis_license(source, target)

    assert target.read_bytes() == (
        b"\xef\xbb\xbf" + "Required Notice: Copyright 2026 Nicolás Olmedo\r\n\r\nTerms\r\n".encode()
    )
