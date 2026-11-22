"""Stock avatars: eight original characters, drawn in each theme's own hand.

A character is SVG on a 64-unit canvas using five palette slots:
    {fur}  main body      {dark} outline / features
    {lite} highlight      {acc}  accent detail      {eye}  eye shine
Each theme supplies a palette and a frame; some themes also restyle the
character itself (pixelated, line art).
"""
from __future__ import annotations

import re

CHARACTERS: dict[str, tuple[str, str]] = {
    'fox': ('Fox', (
        '<polygon points="14,26 18,6 30,20" fill="{fur}"/><polygon points="50,26 46,6 34,20" fill="{fur}"/>'
        '<polygon points="18,22 20,11 26,19" fill="{acc}"/><polygon points="46,22 44,11 38,19" fill="{acc}"/>'
        '<path d="M12 30c0-10 9-14 20-14s20 4 20 14c0 12-9 22-20 24C21 52 12 42 12 30z" fill="{fur}"/>'
        '<path d="M20 38c4 6 8 9 12 9s8-3 12-9c-4 2-8 3-12 3s-8-1-12-3z" fill="{lite}"/>'
        '<circle cx="24" cy="31" r="3.2" fill="{dark}"/><circle cx="40" cy="31" r="3.2" fill="{dark}"/>'
        '<circle cx="25" cy="30" r="1" fill="{eye}"/><circle cx="41" cy="30" r="1" fill="{eye}"/>'
        '<path d="M29 41h6l-3 3z" fill="{dark}"/>'
    )),
    'robot': ('Robot', (
        '<line x1="32" y1="6" x2="32" y2="14" stroke="{dark}" stroke-width="3"/>'
        '<circle cx="32" cy="6" r="3.5" fill="{acc}"/>'
        '<rect x="12" y="14" width="40" height="34" rx="8" fill="{fur}"/>'
        '<rect x="7" y="26" width="6" height="12" rx="2" fill="{dark}"/><rect x="51" y="26" width="6" height="12" rx="2" fill="{dark}"/>'
        '<rect x="17" y="22" width="30" height="14" rx="5" fill="{dark}"/>'
        '<circle cx="25" cy="29" r="3.5" fill="{acc}"/><circle cx="39" cy="29" r="3.5" fill="{acc}"/>'
        '<circle cx="26" cy="28" r="1.1" fill="{eye}"/><circle cx="40" cy="28" r="1.1" fill="{eye}"/>'
        '<rect x="22" y="40" width="20" height="4" rx="2" fill="{lite}"/>'
        '<rect x="18" y="50" width="28" height="10" rx="4" fill="{fur}"/><rect x="28" y="52" width="8" height="5" rx="1.5" fill="{acc}"/>'
    )),
    'owl': ('Owl', (
        '<path d="M14 18l6 6M50 18l-6 6" stroke="{dark}" stroke-width="3" stroke-linecap="round"/>'
        '<path d="M12 30c0-11 9-18 20-18s20 7 20 18v14c0 9-9 16-20 16S12 53 12 44z" fill="{fur}"/>'
        '<path d="M20 42c4 4 8 6 12 6s8-2 12-6v6c-3 5-8 8-12 8s-9-3-12-8z" fill="{lite}"/>'
        '<circle cx="23" cy="30" r="8" fill="{lite}"/><circle cx="41" cy="30" r="8" fill="{lite}"/>'
        '<circle cx="23" cy="30" r="4.2" fill="{dark}"/><circle cx="41" cy="30" r="4.2" fill="{dark}"/>'
        '<circle cx="24.5" cy="28.6" r="1.3" fill="{eye}"/><circle cx="42.5" cy="28.6" r="1.3" fill="{eye}"/>'
        '<path d="M29 36h6l-3 5z" fill="{acc}"/>'
    )),
    'cat': ('Cat', (
        '<polygon points="13,30 15,8 29,20" fill="{fur}"/><polygon points="51,30 49,8 35,20" fill="{fur}"/>'
        '<polygon points="17,24 18,14 25,20" fill="{acc}"/><polygon points="47,24 46,14 39,20" fill="{acc}"/>'
        '<ellipse cx="32" cy="35" rx="21" ry="18" fill="{fur}"/>'
        '<ellipse cx="23.5" cy="33" rx="3.5" ry="4.6" fill="{dark}"/><ellipse cx="40.5" cy="33" rx="3.5" ry="4.6" fill="{dark}"/>'
        '<circle cx="24.5" cy="31.6" r="1.2" fill="{eye}"/><circle cx="41.5" cy="31.6" r="1.2" fill="{eye}"/>'
        '<path d="M29.5 40h5l-2.5 2.5z" fill="{acc}"/>'
        '<path d="M8 38l10 1M8 43l10-1M56 38l-10 1M56 43l-10-1" stroke="{lite}" stroke-width="1.6" stroke-linecap="round"/>'
    )),
    'astronaut': ('Astronaut', (
        '<rect x="15" y="44" width="34" height="16" rx="7" fill="{lite}"/><rect x="27" y="48" width="10" height="7" rx="2" fill="{acc}"/>'
        '<circle cx="32" cy="28" r="20" fill="{lite}"/>'
        '<rect x="16" y="18" width="32" height="22" rx="11" fill="{dark}"/>'
        '<path d="M21 23c3-2 7-3 11-3" stroke="{eye}" stroke-width="2.4" stroke-linecap="round" fill="none"/>'
        '<rect x="9" y="24" width="5" height="10" rx="2" fill="{acc}"/><rect x="50" y="24" width="5" height="10" rx="2" fill="{acc}"/>'
        '<circle cx="40" cy="32" r="2.4" fill="{fur}"/>'
    )),
    'ghost': ('Ghost', (
        '<path d="M12 32c0-12 9-22 20-22s20 10 20 22v24l-5-4-5 4-5-4-5 4-5-4-5 4-5-4-5 4z" fill="{fur}"/>'
        '<path d="M18 22c2-4 6-7 10-8" stroke="{lite}" stroke-width="3" stroke-linecap="round" fill="none"/>'
        '<ellipse cx="25" cy="31" rx="3.6" ry="5" fill="{dark}"/><ellipse cx="39" cy="31" rx="3.6" ry="5" fill="{dark}"/>'
        '<circle cx="26" cy="29.4" r="1.2" fill="{eye}"/><circle cx="40" cy="29.4" r="1.2" fill="{eye}"/>'
        '<ellipse cx="32" cy="41" rx="3" ry="2.2" fill="{acc}"/>'
    )),
    'frog': ('Frog', (
        '<ellipse cx="32" cy="40" rx="22" ry="16" fill="{fur}"/>'
        '<circle cx="21" cy="24" r="9" fill="{fur}"/><circle cx="43" cy="24" r="9" fill="{fur}"/>'
        '<circle cx="21" cy="24" r="5.5" fill="{lite}"/><circle cx="43" cy="24" r="5.5" fill="{lite}"/>'
        '<circle cx="21" cy="24" r="3" fill="{dark}"/><circle cx="43" cy="24" r="3" fill="{dark}"/>'
        '<circle cx="22" cy="23" r="1" fill="{eye}"/><circle cx="44" cy="23" r="1" fill="{eye}"/>'
        '<path d="M20 42c4 4 8 5 12 5s8-1 12-5" stroke="{dark}" stroke-width="2.6" stroke-linecap="round" fill="none"/>'
        '<circle cx="16" cy="42" r="2.6" fill="{acc}"/><circle cx="48" cy="42" r="2.6" fill="{acc}"/>'
    )),
    'knight': ('Knight', (
        '<path d="M32 4c4 2 6 6 6 10h-12c0-4 2-8 6-10z" fill="{acc}"/>'
        '<path d="M12 30c0-11 9-18 20-18s20 7 20 18v22c0 4-3 6-6 6H18c-3 0-6-2-6-6z" fill="{fur}"/>'
        '<rect x="15" y="27" width="34" height="6" rx="3" fill="{dark}"/>'
        '<rect x="30" y="33" width="4" height="20" rx="2" fill="{dark}"/>'
        '<path d="M18 20c3-3 8-5 14-5" stroke="{lite}" stroke-width="3" stroke-linecap="round" fill="none"/>'
        '<circle cx="21" cy="45" r="1.6" fill="{lite}"/><circle cx="43" cy="45" r="1.6" fill="{lite}"/>'
        '<rect x="22" y="29" width="5" height="2" rx="1" fill="{eye}"/><rect x="37" y="29" width="5" height="2" rx="1" fill="{eye}"/>'
    )),
}

# Per theme: palette per character slot, background and frame.
# Palettes rotate per character so a theme's set is not eight copies of one colour.
THEME_AVATAR_STYLE = {
    'default': {
        'palettes': [
            dict(fur='#3ddc84', dark='#0b1a14', lite='#c9f8de', acc='#7a5cff', eye='#ffffff'),
            dict(fur='#7a5cff', dark='#120b29', lite='#d8ceff', acc='#3ddc84', eye='#ffffff'),
            dict(fur='#36c9e8', dark='#07202a', lite='#c9f2fb', acc='#ff6fae', eye='#ffffff'),
        ],
        'frame': 'aurora', 'bg': ('#0d1f1a', '#1a1035'),
    },
    'greenhouse': {
        'palettes': [
            dict(fur='#7fbf6a', dark='#1d2b17', lite='#e7f4cf', acc='#c98b4a', eye='#fffbe8'),
            dict(fur='#b98652', dark='#2a1a0d', lite='#f3e2c8', acc='#75e6a4', eye='#fffbe8'),
            dict(fur='#5fa37e', dark='#102519', lite='#d6f1df', acc='#f2d06b', eye='#fffbe8'),
        ],
        'frame': 'wreath', 'bg': ('#16301f', '#0a1a10'),
    },
    'afterglow': {
        'palettes': [
            dict(fur='#ff5b9b', dark='#2a0a1f', lite='#ffd0e3', acc='#65eaff', eye='#ffffff'),
            dict(fur='#65eaff', dark='#08222b', lite='#d4fbff', acc='#ff5b9b', eye='#ffffff'),
            dict(fur='#ffd45b', dark='#2b2106', lite='#fff2c4', acc='#a45bff', eye='#ffffff'),
        ],
        'frame': 'pixel', 'bg': ('#2a0b24', '#12061a'),
    },
    'monochrome': {
        'palettes': [dict(fur='#15171a', dark='#d9e0e8', lite='#15171a', acc='#15171a', eye='#15171a')],
        'frame': 'lineart', 'bg': ('#1b1e22', '#101215'),
    },
    'signal': {
        'palettes': [
            dict(fur='#f1b85b', dark='#2a1a04', lite='#ffe2a8', acc='#c9711f', eye='#fff6e0'),
            dict(fur='#d98d2b', dark='#24140a', lite='#f9cf8c', acc='#ffe2a8', eye='#fff6e0'),
        ],
        'frame': 'dial', 'bg': ('#2a1a07', '#120b03'),
    },
    'tape-deck': {
        'palettes': [
            dict(fur='#c4a3ff', dark='#2a1c45', lite='#efe4ff', acc='#ff9a52', eye='#ffffff'),
            dict(fur='#ff9a52', dark='#3a1d0b', lite='#ffe1c9', acc='#c4a3ff', eye='#ffffff'),
            dict(fur='#8fd3c8', dark='#14302c', lite='#e0f6f2', acc='#ff9ad5', eye='#ffffff'),
        ],
        'frame': 'blob', 'bg': ('#2b1d45', '#1a1030'),
    },
    'deep-space': {
        'palettes': [
            dict(fur='#6ac7ff', dark='#071a2e', lite='#dff3ff', acc='#b7e4ff', eye='#ffffff'),
            dict(fur='#9a8cff', dark='#100c2e', lite='#e6e2ff', acc='#6ac7ff', eye='#ffffff'),
            dict(fur='#d7e3f0', dark='#0b1522', lite='#ffffff', acc='#ff8a5c', eye='#ffffff'),
        ],
        'frame': 'planet', 'bg': ('#0b1c33', '#03070f'),
    },
    'tideglass': {
        'palettes': [
            dict(fur='#81e1d2', dark='#062a2a', lite='#dcfbf5', acc='#efc586', eye='#ffffff'),
            dict(fur='#efc586', dark='#2e1e08', lite='#fff1d6', acc='#81e1d2', eye='#ffffff'),
            dict(fur='#4fa8c9', dark='#05202c', lite='#d4eef7', acc='#efc586', eye='#ffffff'),
        ],
        'frame': 'porthole', 'bg': ('#0b3140', '#051a24'),
    },
}


def _character(name, palette):
    return CHARACTERS[name][1].format(**palette)


def _lineart(svg_fragment, stroke, fill):
    """Graphite: every shape becomes a hairline drawing on paper-dark."""
    out = re.sub(r'fill="#[0-9a-fA-F]{6}"', f'fill="{fill}"', svg_fragment)
    out = re.sub(r'stroke="#[0-9a-fA-F]{6}"', f'stroke="{stroke}"', out)
    out = re.sub(r'(<(?:path|polygon|rect|circle|ellipse))(?![^>]*stroke=)', rf'\1 stroke="{stroke}" stroke-width="1.6"', out)
    return out


def _frame(kind, bg, accent, body):
    a, b = bg
    defs = (f'<defs><radialGradient id="g" cx="35%" cy="30%" r="80%">'
            f'<stop offset="0" stop-color="{a}"/><stop offset="1" stop-color="{b}"/></radialGradient></defs>')
    if kind == 'aurora':
        deco = (f'<path d="M-4 20C10 10 22 26 36 16S58 4 70 12" stroke="{accent}" stroke-opacity="0.35" stroke-width="5" fill="none"/>'
                f'<path d="M-4 28C12 20 26 34 40 24S60 14 70 20" stroke="#7a5cff" stroke-opacity="0.3" stroke-width="4" fill="none"/>')
        return f'{defs}<rect width="64" height="64" rx="14" fill="url(#g)"/>{deco}<g transform="translate(4 6) scale(0.875)">{body}</g>'
    if kind == 'wreath':
        leaves = ''.join(
            f'<ellipse cx="{x}" cy="{y}" rx="4.2" ry="2" transform="rotate({r} {x} {y})" fill="#75e6a4" fill-opacity="0.75"/>'
            for x, y, r in ((9, 46, -50), (14, 54, -30), (22, 59, -10), (55, 46, 50), (50, 54, 30), (42, 59, 10))
        )
        return f'{defs}<circle cx="32" cy="32" r="31" fill="url(#g)"/>{leaves}<g transform="translate(6 5) scale(0.8)">{body}</g>'
    if kind == 'dial':
        ticks = ''.join(
            f'<rect x="31.2" y="1.5" width="1.6" height="{4 if i % 3 == 0 else 2.4}" fill="{accent}" transform="rotate({i * 15} 32 32)"/>'
            for i in range(24)
        )
        rings = f'<circle cx="32" cy="32" r="22" fill="none" stroke="{accent}" stroke-opacity="0.18"/><circle cx="32" cy="32" r="14" fill="none" stroke="{accent}" stroke-opacity="0.18"/>'
        return f'{defs}<circle cx="32" cy="32" r="31" fill="url(#g)"/>{rings}{ticks}<g transform="translate(9 10) scale(0.72)">{body}</g>'
    if kind == 'blob':
        return (f'{defs}<path d="M32 2c14 0 30 8 30 26s-12 34-30 34S2 50 2 32 18 2 32 2z" fill="url(#g)"/>'
                f'<circle cx="52" cy="12" r="5" fill="#ff9a52" fill-opacity="0.6"/><circle cx="10" cy="52" r="3.4" fill="#8fd3c8" fill-opacity="0.6"/>'
                f'<g transform="translate(5 5) scale(0.85)">{body}</g>')
    if kind == 'planet':
        stars = ''.join(f'<circle cx="{x}" cy="{y}" r="{r}" fill="#ffffff" fill-opacity="0.8"/>' for x, y, r in ((8, 10, 0.8), (54, 8, 0.6), (58, 30, 0.7), (6, 40, 0.5), (48, 52, 0.6)))
        ring = f'<ellipse cx="32" cy="52" rx="30" ry="6" fill="none" stroke="{accent}" stroke-opacity="0.45" stroke-width="2"/>'
        return f'{defs}<rect width="64" height="64" rx="32" fill="url(#g)"/>{stars}{ring}<g transform="translate(6 3) scale(0.8)">{body}</g>'
    if kind == 'porthole':
        rivets = ''.join(
            f'<circle cx="32" cy="3.2" r="1.4" fill="#efc586" transform="rotate({i * 45} 32 32)"/>' for i in range(8)
        )
        return (f'{defs}<circle cx="32" cy="32" r="31" fill="#b88a45"/><circle cx="32" cy="32" r="27" fill="url(#g)"/>{rivets}'
                f'<path d="M14 50c6-3 12-3 18 0s12 3 18 0" stroke="#81e1d2" stroke-opacity="0.35" stroke-width="2" fill="none"/>'
                f'<g transform="translate(8 8) scale(0.75)">{body}</g>')
    if kind == 'pixel':
        bulbs = ''.join(
            f'<rect x="{x}" y="{y}" width="4" height="4" fill="{accent if i % 2 else "#65eaff"}"/>'
            for i, (x, y) in enumerate([(4 + 8 * k, 1) for k in range(8)] + [(4 + 8 * k, 59) for k in range(8)])
        )
        return (f'<rect width="64" height="64" fill="{b}"/><rect x="2" y="6" width="60" height="52" fill="{a}"/>'
                f'{bulbs}<g transform="translate(6 8) scale(0.8)">{body}</g>')
    if kind == 'lineart':
        marks = ''.join(f'<path d="{d}" stroke="{accent}" stroke-width="1" fill="none"/>' for d in ('M2 8V2h6', 'M56 2h6v6', 'M62 56v6h-6', 'M8 62H2v-6'))
        return f'<rect width="64" height="64" fill="{a}"/>{marks}<g transform="translate(6 6) scale(0.8125)">{body}</g>'
    raise ValueError(kind)


def _svg(inner):
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">{inner}</svg>\n'


def render_avatars(theme: str) -> dict[str, str]:
    style = THEME_AVATAR_STYLE[theme]
    palettes = style['palettes']
    out = {}
    for index, name in enumerate(CHARACTERS):
        palette = palettes[index % len(palettes)]
        body = _character(name, palette)
        accent = palettes[0]['fur'] if style['frame'] != 'lineart' else palettes[0]['dark']
        if style['frame'] == 'lineart':
            body = _lineart(body, stroke=palette['dark'], fill=style['bg'][0])
        out[name] = _svg(_frame(style['frame'], style['bg'], accent, body))
    if style['frame'] == 'pixel':
        out = {name: pixelate(svg) for name, svg in out.items()}
    return out


def pixelate(svg: str, grid: int = 24) -> str:
    """Re-draw an avatar on a coarse pixel grid (Afterglow Arcade).

    Rasterises with a headless browser, then emits one rect per pixel run so the
    result stays a crisp SVG at any size.
    """
    import io as _io

    from PIL import Image

    png = _rasterize(svg, 192)
    img = Image.open(_io.BytesIO(png)).convert('RGBA').resize((grid, grid), Image.BOX)
    img = img.quantize(colors=10, method=Image.Quantize.FASTOCTREE).convert('RGBA')
    unit = 64 / grid
    rects = []
    for y in range(grid):
        x = 0
        while x < grid:
            r, g, b, a = img.getpixel((x, y))
            run = 1
            while x + run < grid and img.getpixel((x + run, y)) == (r, g, b, a):
                run += 1
            if a > 40:
                rects.append(f'<rect x="{x * unit:.3g}" y="{y * unit:.3g}" width="{run * unit:.3g}" height="{unit:.3g}" fill="#{r:02x}{g:02x}{b:02x}"/>')
            x += run
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" shape-rendering="crispEdges">{"".join(rects)}</svg>\n'


_BROWSER = {}


def _rasterize(svg: str, size: int) -> bytes:
    from playwright.sync_api import sync_playwright

    if 'page' not in _BROWSER:
        pw = sync_playwright().start()
        browser = pw.chromium.launch()
        _BROWSER.update(pw=pw, browser=browser, page=browser.new_page(viewport={'width': size, 'height': size}))
    page = _BROWSER['page']
    page.set_content(
        f'<html><body style="margin:0;background:transparent">'
        f'<div style="width:{size}px;height:{size}px">{svg.replace("<svg ", f"<svg width=\"{size}\" height=\"{size}\" ")}</div>'
        f'</body></html>'
    )
    return page.screenshot(omit_background=True, clip={'x': 0, 'y': 0, 'width': size, 'height': size})


def close_rasterizer():
    if 'browser' in _BROWSER:
        _BROWSER['browser'].close()
        _BROWSER['pw'].stop()
        _BROWSER.clear()


def avatar_labels() -> dict[str, str]:
    return {name: label for name, (label, _svg) in CHARACTERS.items()}
