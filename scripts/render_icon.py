"""Draw the desktop app icon (`desktop/build/icon.png` and `icon.ico`).

Usage (from the repo root): uv run --with pillow python scripts/render_icon.py

Pillow cannot read SVG, so the shapes of `desktop/build/icon.svg` are drawn here again on
a 1024 px canvas; change both together.
"""

from pathlib import Path

from PIL import Image, ImageDraw

BUILD = Path(__file__).resolve().parents[1] / "desktop" / "build"
BACKGROUND = "#1a1c1f"
ACCENT = "#e9a23b"
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def draw(size: int = 1024) -> Image.Image:
    scale = 4  # draw large, then downsample for smooth edges
    canvas = Image.new("RGBA", (size * scale, size * scale), (0, 0, 0, 0))
    pen = ImageDraw.Draw(canvas)

    def at(x: float, y: float) -> tuple[float, float]:
        return (x * scale * size / 1024, y * scale * size / 1024)

    pen.rounded_rectangle(
        (*at(64, 64), *at(960, 960)), radius=200 * scale * size / 1024, fill=BACKGROUND
    )
    pen.polygon([at(332, 260), at(332, 764), at(772, 512)], fill=ACCENT)
    pen.polygon([at(520, 200), at(584, 200), at(504, 824), at(440, 824)], fill=BACKGROUND)
    return canvas.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    icon = draw()
    icon.resize((512, 512), Image.Resampling.LANCZOS).save(BUILD / "icon.png")
    icon.save(BUILD / "icon.ico", sizes=ICO_SIZES)
    print(f"wrote {BUILD / 'icon.png'} and {BUILD / 'icon.ico'}")


if __name__ == "__main__":
    main()
