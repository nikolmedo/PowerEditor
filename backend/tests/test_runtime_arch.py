from pathlib import Path

import pytest

from powereditor.resources import tool_candidates
from powereditor.runtime.host import detect_host_arch
from powereditor.runtime.manager import RuntimeManager
from powereditor.runtime.manifest import (
    ALL_DOWNLOADS,
    FFMPEG,
    FFMPEG_ARM64,
    NODE,
    downloads_for,
    resolution_order,
)


@pytest.mark.parametrize(
    ("native", "machine", "expected"),
    [
        (0xAA64, "AMD64", "arm64"),
        (0x8664, "AMD64", "x64"),
        (None, "AMD64", "x64"),
        (None, "ARM64", "arm64"),
        (None, "aarch64", "arm64"),
        (None, "x86_64", "x64"),
    ],
)
def test_host_arch_sees_through_x64_emulation(
    native: int | None, machine: str, expected: str
) -> None:
    assert detect_host_arch(lambda: native, lambda: machine) == expected


def test_an_arm64_host_downloads_the_native_ffmpeg_and_the_x64_node() -> None:
    assert downloads_for("arm64") == (FFMPEG_ARM64, NODE)
    assert downloads_for("x64") == (FFMPEG, NODE)
    assert downloads_for("riscv64") == (FFMPEG, NODE)


def test_native_builds_install_into_their_own_folder() -> None:
    assert FFMPEG.dir_name == "ffmpeg-8.1.3"
    assert FFMPEG_ARM64.dir_name == "ffmpeg-8.1.2-arm64"
    assert "winarm64-lgpl" in FFMPEG_ARM64.url
    assert FFMPEG_ARM64.license == FFMPEG.license
    assert FFMPEG_ARM64.tools == FFMPEG.tools
    assert len({spec.dir_name for spec in ALL_DOWNLOADS}) == len(ALL_DOWNLOADS)


def _install_fake(bin_dir: Path, dir_name: str) -> Path:
    tool = bin_dir / dir_name / "bin" / "ffmpeg.exe"
    tool.parent.mkdir(parents=True)
    tool.write_bytes(b"")
    return tool


def test_an_existing_x64_ffmpeg_keeps_working_until_the_native_one_is_installed(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    x64 = _install_fake(bin_dir, FFMPEG.dir_name)
    order = resolution_order("arm64")

    def which(name: str) -> None:
        return None

    assert tool_candidates("ffmpeg", None, bin_dir, None, which, order) == [str(x64)]
    status = next(
        s
        for s in RuntimeManager(bin_dir=bin_dir, downloads=downloads_for("arm64")).statuses()
        if s.name == "ffmpeg"
    )
    assert (status.installed, status.version) == (False, FFMPEG_ARM64.version)
    assert status.download_bytes == FFMPEG_ARM64.size

    native = _install_fake(bin_dir, FFMPEG_ARM64.dir_name)
    assert tool_candidates("ffmpeg", None, bin_dir, None, which, order) == [str(native), str(x64)]
    x64_order = resolution_order("x64")
    assert tool_candidates("ffmpeg", None, bin_dir, None, which, x64_order) == [str(x64)]
