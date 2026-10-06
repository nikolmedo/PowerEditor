"""Render docs/banner/banner.html to docs/banner.png (1280x640) with headless Chrome or Edge."""

import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "banner.html"
OUTPUT = HERE.parent / "banner.png"
BROWSERS = [
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
]


def find_browser() -> str:
    for name in ("google-chrome", "chromium", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    for path in BROWSERS:
        if path.is_file():
            return str(path)
    sys.exit("Chrome or Edge not found.")


def main() -> None:
    subprocess.run(
        [
            find_browser(),
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--allow-file-access-from-files",
            "--force-device-scale-factor=1",
            "--window-size=1280,640",
            "--virtual-time-budget=3000",
            f"--screenshot={OUTPUT}",
            SOURCE.as_uri(),
        ],
        check=True,
        capture_output=True,
    )
    print(OUTPUT)


if __name__ == "__main__":
    main()
