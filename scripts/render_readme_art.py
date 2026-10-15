"""
README art, drawn in the app's own tokens.

GitHub strips stylesheets from Markdown, so the only way a README can look
like the product is with images. This renders every non-screenshot asset the
README uses, from the same tokens and glyphs the app ships:

* `hero-banner.png` — the Discover screenshot framed on the theme background
  with the wordmark and tagline (Pillow; real pixels, no mock frames);
* `h-<slug>.svg` — section headers: accent bar, kicker, title;
* `card-<slug>.svg` — feature cards with the rail icon from
  `frontend/shared/src/railIcons.tsx` and three lines of copy;
* `poster-<name>.png` — how-to video tiles: the clip's poster frame, a play
  badge and the title strip (from `docs/media/video/howto/index.json`).

    python scripts/render_readme_art.py

Deterministic given the inputs; safe to re-run after every capture.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets" / "readme"
HOWTO = ROOT / "docs" / "media" / "video" / "howto"
ICONS_TSX = ROOT / "frontend" / "shared" / "src" / "railIcons.tsx"
SHARED_ICONS_TSX = ROOT / "frontend" / "shared" / "src" / "generatedIconPaths.tsx"

T = {
    "bg": "#0b0d10",
    "surface": "#141820",
    "surface2": "#1c2230",
    "text": "#f2f4f8",
    "muted": "#c4ccd8",
    "accent": "#2fd67b",
    "accent2": "#86efac",
    "teal": "#12a4a0",
    "mint": "#4ef2a1",
}
FONT_STACK = "'Segoe UI', system-ui, -apple-system, 'Helvetica Neue', Arial, sans-serif"


# --------------------------------------------------------------------------
# icons — lifted from the shared rail set so README glyphs are product glyphs
# --------------------------------------------------------------------------

def load_rail_icons() -> dict[str, str]:
    icons: dict[str, str] = {}
    sources = (
        (SHARED_ICONS_TSX, "export const sharedIconPaths"),
        (ICONS_TSX, "export const railIconPaths"),
    )
    for path, declaration in sources:
        src = path.read_text(encoding="utf-8")
        body = src.split(declaration, 1)[1]
        for m in re.finditer(r"\n  '?([a-z-]+)'?: \(\s*<>(.*?)</>\s*\),", body, re.S):
            name, jsx = m.group(1), m.group(2)
            svg = re.sub(r"\b(strokeWidth|strokeLinecap|strokeLinejoin|fillRule|clipRule)=",
                         lambda mm: {"strokeWidth": "stroke-width", "strokeLinecap": "stroke-linecap",
                                     "strokeLinejoin": "stroke-linejoin", "fillRule": "fill-rule",
                                     "clipRule": "clip-rule"}[mm.group(1)] + "=", jsx)
            icons[name] = " ".join(svg.split())
    return icons


ICONS = load_rail_icons()


def icon_svg(name: str, size: int, color: str) -> str:
    if name not in ICONS:
        raise ValueError(f"README card references unknown shared rail icon: {name}")
    inner = ICONS[name]
    return (
        f'<svg width="{size}" height="{size}" viewBox="-1 -1 26 26" fill="none" stroke="{color}" '
        f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
        f'style="color:{color}">{inner}</svg>'
    )


# --------------------------------------------------------------------------
# SVG pieces
# --------------------------------------------------------------------------

def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def header_svg(kicker: str, title: str, width: int = 1200, height: int = 88) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{_esc(title)}">
  <defs>
    <linearGradient id="bar" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{T['teal']}"/><stop offset=".5" stop-color="{T['accent']}"/><stop offset="1" stop-color="{T['mint']}"/>
    </linearGradient>
    <linearGradient id="glow" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{T['accent']}" stop-opacity=".16"/><stop offset=".55" stop-color="{T['accent']}" stop-opacity="0"/>
    </linearGradient>
  </defs>
  <rect width="{width}" height="{height}" rx="14" fill="{T['surface']}"/>
  <rect width="{width}" height="{height}" rx="14" fill="url(#glow)"/>
  <rect x=".5" y=".5" width="{width-1}" height="{height-1}" rx="13.5" fill="none" stroke="#ffffff" stroke-opacity=".12"/>
  <rect x="18" y="18" width="6" height="{height-36}" rx="3" fill="url(#bar)"/>
  <text x="44" y="36" fill="{T['accent']}" font-family="{FONT_STACK}" font-size="13" font-weight="700" letter-spacing="3">{_esc(kicker.upper())}</text>
  <text x="44" y="66" fill="{T['text']}" font-family="{FONT_STACK}" font-size="28" font-weight="800">{_esc(title)}</text>
</svg>
"""


def card_svg(icon: str, title: str, lines: list[str], width: int = 380, height: int = 210) -> str:
    rows = "".join(
        f'<text x="26" y="{112 + i * 26}" fill="{T["muted"]}" font-family="{FONT_STACK}" font-size="15">'
        f'<tspan fill="{T["accent"]}" font-weight="700">·</tspan> {_esc(line)}</text>'
        for i, line in enumerate(lines[:4])
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{_esc(title)}">
  <defs>
    <linearGradient id="top" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{T['teal']}"/><stop offset=".5" stop-color="{T['accent']}"/><stop offset="1" stop-color="{T['mint']}"/>
    </linearGradient>
    <radialGradient id="halo" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate(44 50) scale(120)">
      <stop offset="0" stop-color="{T['accent']}" stop-opacity=".18"/><stop offset="1" stop-color="{T['accent']}" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="{width}" height="{height}" rx="16" fill="{T['surface']}"/>
  <rect width="{width}" height="{height}" rx="16" fill="url(#halo)"/>
  <rect x=".5" y=".5" width="{width-1}" height="{height-1}" rx="15.5" fill="none" stroke="#ffffff" stroke-opacity=".12"/>
  <rect x="26" y="0" width="64" height="3" rx="1.5" fill="url(#top)"/>
  <g transform="translate(26 28)">
    <rect width="44" height="44" rx="11" fill="{T['surface2']}"/>
    <rect x=".5" y=".5" width="43" height="43" rx="10.5" fill="none" stroke="{T['accent']}" stroke-opacity=".35"/>
    <g transform="translate(10 10)">{icon_svg(icon, 24, T['accent'])}</g>
  </g>
  <text x="84" y="57" fill="{T['text']}" font-family="{FONT_STACK}" font-size="20" font-weight="800">{_esc(title)}</text>
  {rows}
</svg>
"""


# --------------------------------------------------------------------------
# raster pieces
# --------------------------------------------------------------------------

def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for c in candidates:
        if Path(c).exists():
            return ImageFont.truetype(c, size)
    return ImageFont.load_default()


def _rounded(img: Image.Image, radius: int) -> Image.Image:
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, img.width - 1, img.height - 1], radius=radius, fill=255)
    out = img.convert("RGBA")
    out.putalpha(mask)
    return out


def _shadowed(canvas: Image.Image, tile: Image.Image, xy: tuple[int, int], blur: int = 28, alpha: int = 150) -> None:
    x, y = xy
    shadow = Image.new("RGBA", (tile.width + blur * 4, tile.height + blur * 4), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        [blur * 2, blur * 2 + 10, blur * 2 + tile.width, blur * 2 + tile.height + 10], radius=22, fill=(0, 0, 0, alpha)
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(blur))
    canvas.alpha_composite(shadow, (x - blur * 2, y - blur * 2))
    canvas.alpha_composite(tile, (x, y))


def _hex(h: str, a: int = 255) -> tuple[int, int, int, int]:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a)


def _backdrop(w: int, h: int) -> Image.Image:
    canvas = Image.new("RGBA", (w, h), _hex(T["bg"]))
    d = ImageDraw.Draw(canvas)
    # Grid, faint, fading out from the centre like the title cards.
    grid = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    g = ImageDraw.Draw(grid)
    for x in range(0, w, 64):
        g.line([(x, 0), (x, h)], fill=(255, 255, 255, 14))
    for y in range(0, h, 64):
        g.line([(0, y), (w, y)], fill=(255, 255, 255, 14))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).ellipse([-w * 0.1, -h * 0.4, w * 1.1, h * 1.4], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(w // 6))
    grid.putalpha(Image.eval(mask, lambda v: v // 6))
    canvas.alpha_composite(grid)
    # Accent glow.
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([w * 0.15, -h * 0.2, w * 0.85, h * 0.9], fill=_hex(T["accent"], 46))
    glow = glow.filter(ImageFilter.GaussianBlur(w // 7))
    canvas.alpha_composite(glow)
    del d
    return canvas


def render_hero(shot: Path, out: Path) -> None:
    W, H = 1920, 780
    canvas = _backdrop(W, H)
    d = ImageDraw.Draw(canvas)

    # Wordmark row.
    mark = Image.open(OUT / "app-icon.png").convert("RGBA").resize((84, 84), Image.LANCZOS)
    canvas.alpha_composite(mark, (96, 64))
    d.text((200, 62), "Oneirodex", font=_font(54, bold=True), fill=_hex(T["text"]))
    d.text((202, 124), "SELF-HOSTED GAME LIBRARY FOR HOUSEHOLDS", font=_font(16, bold=True), fill=_hex(T["accent"]))
    tag = "Scan folders  ·  identify with IGDB / Steam / GOG  ·  invite the household  ·  download, play, chat"
    d.text((W - 96 - d.textlength(tag, font=_font(20)), 92), tag, font=_font(20), fill=_hex(T["muted"]))

    # The real screenshot, framed.
    shot_img = Image.open(shot).convert("RGB")
    target_w = W - 192
    scale = target_w / shot_img.width
    frame = shot_img.resize((target_w, int(shot_img.height * scale)), Image.LANCZOS)
    # Crop to the banner: the top of the page is where the chrome and first
    # shelf are; the rest falls below the fold like it would in a browser.
    visible_h = H - 190
    frame = frame.crop((0, 0, target_w, min(frame.height, visible_h + 40)))
    tile = _rounded(frame, 18)
    border = Image.new("RGBA", tile.size, (0, 0, 0, 0))
    ImageDraw.Draw(border).rounded_rectangle([0, 0, tile.width - 1, tile.height - 1], radius=18,
                                             outline=(255, 255, 255, 40), width=1)
    tile.alpha_composite(border)
    _shadowed(canvas, tile, (96, 190))

    # Fade the bottom edge into the background so the crop reads as a fold.
    fade = Image.new("RGBA", (W, 140), (0, 0, 0, 0))
    fd = ImageDraw.Draw(fade)
    for i in range(140):
        fd.line([(0, i), (W, i)], fill=_hex(T["bg"], int(255 * (i / 140) ** 1.6)))
    canvas.alpha_composite(fade, (0, H - 140))
    # Accent rule at the very bottom, same as the title cards.
    d = ImageDraw.Draw(canvas)
    for x in range(W):
        t = x / W
        r = int(0x12 + (0x4e - 0x12) * t); g = int(0xa4 + (0xf2 - 0xa4) * t); b = int(0xa0 + (0xa1 - 0xa0) * t)
        d.line([(x, H - 6), (x, H)], fill=(r, g, b, 255))
    canvas.convert("RGB").save(out, optimize=True)
    print("hero  :", out.relative_to(ROOT))


def render_poster_tile(poster: Path, title: str, seconds: int, out: Path) -> None:
    src = Image.open(poster).convert("RGB")
    w = 640
    img = src.resize((w, int(src.height * w / src.width)), Image.LANCZOS)
    tile = _rounded(img, 14)
    d = ImageDraw.Draw(tile)
    # Title strip.
    strip_h = 52
    strip = Image.new("RGBA", (w, strip_h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(strip)
    for i in range(strip_h):
        sd.line([(0, i), (w, i)], fill=(11, 13, 16, int(120 + 135 * i / strip_h)))
    tile.alpha_composite(strip, (0, tile.height - strip_h))
    d = ImageDraw.Draw(tile)
    d.text((18, tile.height - 38), title, font=_font(18, bold=True), fill=_hex(T["text"]))
    dur = f"{seconds // 60}:{seconds % 60:02d}"
    d.text((w - 18 - d.textlength(dur, font=_font(14)), tile.height - 34), dur, font=_font(14), fill=_hex(T["accent2"]))
    # Play badge.
    r = 34
    cx, cy = w // 2, (tile.height - strip_h) // 2
    badge = Image.new("RGBA", tile.size, (0, 0, 0, 0))
    bd = ImageDraw.Draw(badge)
    bd.ellipse([cx - r - 6, cy - r - 6, cx + r + 6, cy + r + 6], fill=(11, 13, 16, 140))
    bd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=_hex(T["accent"]))
    bd.polygon([(cx - 10, cy - 16), (cx - 10, cy + 16), (cx + 18, cy)], fill=_hex(T["bg"]))
    tile.alpha_composite(badge)
    # Rounded border.
    ImageDraw.Draw(tile).rounded_rectangle([0, 0, w - 1, tile.height - 1], radius=14, outline=(255, 255, 255, 38), width=1)
    tile.save(out, optimize=True)


# --------------------------------------------------------------------------

HEADERS = [
    ("what", "01 · Overview", "What is Oneirodex?"),
    ("features", "02 · Features", "Everything a household library needs"),
    ("screens", "03 · Screens", "The app, as it is"),
    ("videos", "04 · How-to videos", "Narrated walkthroughs of every feature"),
    ("quickstart", "05 · Quick start", "Three ways in — pick one"),
    ("scan", "06 · Scan locations", "NAS shares, second disks, extra mounts"),
    ("config", "07 · Configuration", "The environment that matters"),
    ("architecture", "08 · Architecture", "At a glance"),
    ("troubleshooting", "09 · Troubleshooting", "Quick triage"),
    ("docs", "10 · Documentation", "Start here"),
    ("dev", "11 · Development", "Build, test, ratchets"),
    ("license", "12 · Licence", "AGPL-3.0 — and what that means for a server"),
]

CARDS = [
    ("library", "library", "Library & discovery", [
        "Multi-threaded scans · IGDB, Steam, GOG, RAWG",
        "Filters, badges (NEW · UPDATE · MISSING)",
        "Discover shelves as timed events",
        "Systems hub · DAT set completion",
    ]),
    ("household", "friends", "Household access", [
        "Invite-based membership, parental ACL",
        "Themes, decade rooms, colour cabinets",
        "Six icon packs · era fonts, self-installing",
        "Mobile density: hamburger nav, touch targets",
    ]),
    ("play", "ways-to-play", "Play & companion", [
        "Browser play via WebRetro · cloud saves · cheats",
        "Desktop companion: install, launch, update",
        "Big Picture for the TV · VR / Quest PWA",
        "Emulator BIOS admin, honest Play buttons",
    ]),
    ("social", "chat", "Social & support", [
        "Rooms, spaces, threads, reactions, DMs",
        "Friends dock, pop-out, presence",
        "Optional LiveKit voice & screenshare",
        "Report issue → admin inbox → GitHub",
    ]),
    ("admin", "admin", "Admin & ops", [
        "Libraries & scans, unmatched, filters",
        "Ops board: services, queues, log, /pulse",
        "Users, invites, whitelist, support inbox",
        "Art studio covers with no cloud AI",
    ]),
    ("modules", "integrations", "Optional modules", [
        "*arr + hardlink pipeline · Ollama AI assist",
        "OIDC / Authentik SSO — off by default",
        "Generated art on your own A1111 endpoint",
        "Malware heuristics · optional ClamAV",
    ]),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for slug, kicker, title in HEADERS:
        (OUT / f"h-{slug}.svg").write_text(header_svg(kicker, title), encoding="utf-8")
    print(f"headers: {len(HEADERS)} -> {OUT.relative_to(ROOT)}/h-*.svg")
    for slug, icon, title, lines in CARDS:
        (OUT / f"card-{slug}.svg").write_text(card_svg(icon, title, lines), encoding="utf-8")
    print(f"cards  : {len(CARDS)} -> {OUT.relative_to(ROOT)}/card-*.svg")

    discover = OUT / "screenshot-discover.png"
    if discover.exists():
        render_hero(discover, OUT / "hero-banner.png")
    else:
        print("hero  : skipped — no screenshot-discover.png yet (run capture_docs_media.py)")

    index = HOWTO / "index.json"
    if index.exists():
        n = 0
        for e in json.loads(index.read_text(encoding="utf-8")):
            if not e.get("poster"):
                continue
            poster = HOWTO / e["poster"]
            if poster.exists():
                render_poster_tile(poster, e["title"], int(e["seconds"]), OUT / f"poster-{e['name']}.png")
                n += 1
        print(f"posters: {n} -> {OUT.relative_to(ROOT)}/poster-*.png")


if __name__ == "__main__":
    main()
