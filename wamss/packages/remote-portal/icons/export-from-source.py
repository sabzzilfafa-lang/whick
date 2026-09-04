#!/usr/bin/env python3
"""Whick Remote PWA icons from source-remote.png."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "source-remote.png"
SIZES = {
    "favicon-32.png": 32,
    "icon-48.png": 48,
    "apple-touch-icon.png": 180,
    "icon-192.png": 192,
    "icon-512.png": 512,
    "icon-512-maskable.png": 512,
}


def fit_square(img: Image.Image, size: int) -> Image.Image:
    side = min(img.size)
    left = (img.width - side) // 2
    top = (img.height - side) // 2
    cropped = img.crop((left, top, left + side, top + side))
    return cropped.resize((size, size), Image.Resampling.LANCZOS)


def maskable(img: Image.Image, size: int) -> Image.Image:
    """Android maskable — ~80% safe zone on cream background."""
    canvas = Image.new("RGBA", (size, size), (250, 244, 232, 255))
    inner = int(size * 0.78)
    icon = fit_square(img, inner)
    offset = (size - inner) // 2
    canvas.paste(icon, (offset, offset), icon if icon.mode == "RGBA" else None)
    return canvas.convert("RGB")


def rounded_preview(img: Image.Image, size: int, radius_ratio: float = 0.22) -> Image.Image:
    """Optional iOS-style preview — export keeps square PNGs for PWA."""
    out = img.resize((size, size), Image.Resampling.LANCZOS).convert("RGBA")
    radius = int(size * radius_ratio)
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size, size), radius=radius, fill=255)
    out.putalpha(mask)
    return out


def main() -> int:
    if not SRC.is_file():
        raise SystemExit(f"missing {SRC}")
    base = Image.open(SRC).convert("RGBA")
    for name, size in SIZES.items():
        out = ROOT / name
        if name == "icon-512-maskable.png":
            maskable(base, size).save(out, format="PNG", optimize=True)
        else:
            fit_square(base, size).save(out, format="PNG", optimize=True)
        print("wrote", out)

    ico_src = fit_square(base, 256)
    ico_path = ROOT.parent / "favicon.ico"
    ico_src.save(
        ico_path,
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print("wrote", ico_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
