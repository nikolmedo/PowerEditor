"""Pinned runtimes the app downloads into `<data dir>/bin/<name>-<version>[-<arch>]/` at first run.

The packaged app is x64 and runs emulated on Windows ARM64. FFmpeg also has a native ARM64
build, chosen from the real host architecture (`runtime.host`); Node stays x64 because
Remotion has no win32-arm64 compositor.

- **ffmpeg**: BtbN FFmpeg-Builds, LGPL variant (no GPL code, so no libx264; ingest uses
  hardware encoders or Media Foundation, then libopenh264). Pinned to a month-end autobuild
  tag: BtbN prunes daily autobuilds after about two weeks but keeps month-end ones for about
  two years. Each SHA-256 matches both the release's `checksums.sha256` asset and the GitHub
  API asset digest.
- **ffmpeg (arm64)**: the 2026-09-30 winarm64 builds crash at startup (llvm-strip removed
  needed sections, https://github.com/BtbN/FFmpeg-Builds/issues/675, fixed in the 2026-10-03
  autobuilds), so the ARM64 entry stays on the 2026-08-31 month-end build (n8.1.2) until a
  later month-end build is checked on an ARM64 machine.
- **node**: the official nodejs.org portable zip; the SHA-256 is the `node-v24.21.0-win-x64.zip`
  line of https://nodejs.org/dist/v24.21.0/SHASUMS256.txt.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from powereditor.runtime.host import host_arch


@dataclass(frozen=True)
class RuntimeDownload:
    name: str
    version: str
    url: str
    sha256: str
    size: int
    """Expected download size in bytes, for progress when the server sends no length."""
    tools: dict[str, str]
    """Executable name → path inside the archive, below its single top-level folder."""
    keep: tuple[str, ...] = ()
    """Files or folders (below the top-level folder) to extract; empty extracts everything."""
    platform: str = "win32"
    license: str = ""
    arch: str = "x64"

    @property
    def dir_name(self) -> str:
        base = f"{self.name}-{self.version}"
        return base if self.arch == "x64" else f"{base}-{self.arch}"


FFMPEG = RuntimeDownload(
    name="ffmpeg",
    version="8.1.3",
    url=(
        "https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-09-30-13-08/"
        "ffmpeg-n8.1.3-9-g29e619e767-win64-lgpl-8.1.zip"
    ),
    sha256="4a7642b2264c03e8a0ce8a3825b933ee5580656f45695a086fe7e294045ffc0a",
    size=170_611_883,
    tools={"ffmpeg": "bin/ffmpeg.exe", "ffprobe": "bin/ffprobe.exe"},
    keep=("bin/ffmpeg.exe", "bin/ffprobe.exe", "LICENSE.txt"),
    license="LGPL-3.0-or-later",
)

FFMPEG_ARM64 = RuntimeDownload(
    name="ffmpeg",
    version="8.1.2",
    url=(
        "https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-08-31-13-27/"
        "ffmpeg-n8.1.2-50-g1a748fe2cd-winarm64-lgpl-8.1.zip"
    ),
    sha256="0ad4d6e7342d6d77bbae4ac230964ebd51bdd6192414392e5f521d295b39b111",
    size=95_498_313,
    tools={"ffmpeg": "bin/ffmpeg.exe", "ffprobe": "bin/ffprobe.exe"},
    keep=("bin/ffmpeg.exe", "bin/ffprobe.exe", "LICENSE.txt"),
    license="LGPL-3.0-or-later",
    arch="arm64",
)

NODE = RuntimeDownload(
    name="node",
    version="24.21.0",
    url="https://nodejs.org/dist/v24.21.0/node-v24.21.0-win-x64.zip",
    sha256="158f7685b44de51f6c0df1d153526cbcd3e1bc739a8dfc607721cef75de9e541",
    size=37_618_919,
    tools={"node": "node.exe"},
    keep=("node.exe", "LICENSE"),
    license="MIT",
)

ALL_DOWNLOADS: tuple[RuntimeDownload, ...] = (FFMPEG, FFMPEG_ARM64, NODE)


def downloads_for(
    arch: str, downloads: Sequence[RuntimeDownload] = ALL_DOWNLOADS
) -> tuple[RuntimeDownload, ...]:
    """One download per runtime: the native build for `arch` when there is one, else x64."""
    chosen: dict[str, RuntimeDownload] = {}
    for spec in downloads:
        if spec.arch not in (arch, "x64"):
            continue
        if spec.name not in chosen or spec.arch == arch:
            chosen[spec.name] = spec
    return tuple(chosen.values())


def resolution_order(
    arch: str, downloads: Sequence[RuntimeDownload] = ALL_DOWNLOADS
) -> tuple[RuntimeDownload, ...]:
    """Installed runtimes worth running on `arch`, native builds first: an x64 install keeps
    working on ARM64 until the native one is installed."""
    usable = [spec for spec in downloads if spec.arch in (arch, "x64")]
    return tuple(sorted(usable, key=lambda spec: spec.arch != arch))


DOWNLOADS = downloads_for(host_arch())
"""What this machine downloads."""
TOOL_DOWNLOADS = resolution_order(host_arch())
"""Where this machine looks for downloaded tools, best first."""
