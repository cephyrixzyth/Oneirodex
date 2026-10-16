#!/usr/bin/env python3
"""Rasterise the Oneirodex mark into the PNG brand assets.

There is no cairosvg on the build boxes, so this redraws the *same geometry* as
``oneirodex/static/newstyle/oneirodex_mark.svg`` with Pillow. If you change the
SVG, change this too — they are intentionally a matched pair, and the SVG is the
source of truth for proportions.

Supersamples 8x then downscales, which is what keeps the rounded corners and the
leaning case from aliasing at favicon sizes.

Usage:
  python scripts/render-brand-assets.py
  python scripts/render-brand-assets.py --preview   # just write a large preview
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
NEWSTYLE = ROOT / "oneirodex" / "static" / "newstyle"
README_ASSETS = ROOT / "docs" / "assets" / "readme"
ICONS = ROOT / "oneirodex" / "static" / "icons"

SS = 8  # supersample factor

PLATE = (0x0b, 0x0d, 0x10, 255)
TINT = (0x8f, 0xf0, 0xc4)


def _lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def accent(t: float) -> tuple[int, int, int]:
    """Matches the SVG gradient: #12a4a0 -> #2fd67b -> #4ef2a1 (bottom-left up)."""
    c0, c1, c2 = (0x12, 0xa4, 0xa0), (0x2f, 0xd6, 0x7b), (0x4e, 0xf2, 0xa1)
    return _lerp(c0, c1, t / 0.45) if t <= 0.45 else _lerp(c1, c2, (t - 0.45) / 0.55)


def draw_mark(size: int) -> Image.Image:
    n = size * SS
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = n / 64.0

    def rr(x, y, w, h, r, fill):
        d.rounded_rectangle([x * u, y * u, (x + w) * u, (y + h) * u],
                            radius=r * u, fill=fill)

    rr(0, 0, 64, 64, 15, PLATE)
    d.rounded_rectangle([0.75 * u, 0.75 * u, 63.25 * u, 63.25 * u],
                        radius=14.25 * u, outline=(0x2f, 0xd6, 0x7b, 66),
                        width=max(1, round(1.5 * u)))

    # case frame
    rr(12.4, 17, 3.2, 30, 1.5, accent(0.30) + (255,))
    rr(48.4, 17, 3.2, 30, 1.5, accent(0.80) + (255,))
    rr(12.4, 44.4, 39.2, 3.2, 1.5, accent(0.45) + (255,))

    # collection
    rr(19.5, 26.5, 4.6, 17.7, 1.3, TINT + (199,))
    rr(25.0, 22.0, 5.4, 22.2, 1.3, accent(0.45) + (255,))
    rr(31.4, 24.5, 4.2, 19.7, 1.3, TINT + (148,))
    rr(36.6, 20.5, 5.0, 23.7, 1.3, accent(0.70) + (255,))

    # leaning case — drawn on its own layer so it can rotate about its base
    lean = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    ImageDraw.Draw(lean).rounded_rectangle(
        [42.2 * u, 23.5 * u, 47.0 * u, 44.2 * u], radius=1.3 * u,
        fill=TINT + (184,))
    img.alpha_composite(lean.rotate(-13, resample=Image.BICUBIC,
                                    center=(44.6 * u, 44.2 * u)))

    return img.resize((size, size), Image.LANCZOS)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()

    if args.preview:
        out = ROOT / "brand-preview.png"
        draw_mark(512).save(out)
        print("preview:", out)
        return 0

    targets = [
        (README_ASSETS / "app-icon.png", 512),
        (NEWSTYLE / "oneirodex_logo.png", 512),
        (NEWSTYLE / "oneirodex_logo_small.png", 128),
        # Tab / touch icons — keep these filenames stable for browser entry points.
        (ICONS / "favicon.png", 64),
        (ICONS / "favicon-32.png", 32),
        (ICONS / "favicon-48.png", 48),
        (ICONS / "apple-touch-icon.png", 180),
        (ICONS / "icon-192.png", 192),
    ]
    for path, size in targets:
        path.parent.mkdir(parents=True, exist_ok=True)
        draw_mark(size).save(path)
        print(f"  {path.relative_to(ROOT)}  {size}px")

    ico = ICONS / "favicon.ico"
    draw_mark(256).save(ico, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (256, 256)])
    print(f"  {ico.relative_to(ROOT)}  multi-size")
    print("\nBrand assets generated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
