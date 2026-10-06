"""Pinned runtimes the app downloads into `<data dir>/bin/<name>-<version>/` at first run.

Every entry is a Windows x64 build: the packaged app targets Windows, and on ARM64 hosts
both tools run under x64 emulation (Remotion has no win32-arm64 compositor).

- **ffmpeg**: BtbN FFmpeg-Builds, LGPL variant (no GPL code, so no libx264; ingest falls
  back to libopenh264). Pinned to a month-end autobuild tag: BtbN prunes daily autobuilds
  after about two weeks but keeps month-end ones for about two years. The SHA-256 matches
  both the release's `checksums.sha256` asset and the GitHub API asset digest.
- **node**: the official nodejs.org portable zip; the SHA-256 is the `node-v24.21.0-win-x64.zip`
  line of https://nodejs.org/dist/v24.21.0/SHASUMS256.txt.
"""

from dataclasses import dataclass


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

    @property
    def dir_name(self) -> str:
        return f"{self.name}-{self.version}"


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
    license="LGPL-2.1-or-later",
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

DOWNLOADS: tuple[RuntimeDownload, ...] = (FFMPEG, NODE)
