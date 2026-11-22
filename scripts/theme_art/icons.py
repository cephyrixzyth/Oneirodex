"""Icon geometry shared by every theme, and one renderer per theme.

Icons are CSS masks in the UI (one colour, tinted by the theme), so a theme's
identity lives in the *shape language*, not the colour: each renderer draws the
same 17 glyphs in a different hand. Geometry is on a 24-unit grid.

Primitives:
    ('line', x1, y1, x2, y2)
    ('rect', x, y, w, h, r)          closed, may be filled by a renderer
    ('circle', cx, cy, r)            closed
    ('poly', [(x, y), ...], closed)  closed polygons may be filled
    ('dot', cx, cy, r)               always solid
"""
from __future__ import annotations

import math


def _star(cx, cy, outer, inner, points=5, rotate=-90):
    pts = []
    for i in range(points * 2):
        radius = outer if i % 2 == 0 else inner
        angle = math.radians(rotate + i * 180 / points)
        pts.append((round(cx + radius * math.cos(angle), 2), round(cy + radius * math.sin(angle), 2)))
    return pts


def _heart(cx, cy, size, steps=28):
    pts = []
    for i in range(steps):
        t = math.pi * 2 * i / steps
        x = 16 * math.sin(t) ** 3
        y = -(13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t))
        pts.append((round(cx + x * size / 17, 2), round(cy + y * size / 17, 2)))
    return pts


def _gear(cx, cy, outer, inner, teeth=8):
    pts = []
    for i in range(teeth * 4):
        angle = math.radians(i * 360 / (teeth * 4) - 90 + 360 / (teeth * 8))
        radius = outer if (i % 4) in (1, 2) else inner
        pts.append((round(cx + radius * math.cos(angle), 2), round(cy + radius * math.sin(angle), 2)))
    return pts


def _arc(cx, cy, r, start, end, steps=18):
    return [
        (round(cx + r * math.cos(math.radians(start + (end - start) * i / steps)), 2),
         round(cy + r * math.sin(math.radians(start + (end - start) * i / steps)), 2))
        for i in range(steps + 1)
    ]


GLYPHS: dict[str, list] = {
    'library': [
        ('rect', 4.5, 5, 3.5, 14, 0.8), ('rect', 9.5, 7, 3.5, 12, 0.8),
        ('poly', [(15, 8.2), (18.2, 7.4), (20.6, 18.2), (17.4, 19)], True),
        ('line', 3, 21, 21, 21),
    ],
    'discover': [
        ('circle', 12, 12, 9),
        ('poly', [(15.6, 8.4), (13.4, 13.4), (8.4, 15.6), (10.6, 10.6)], True),
    ],
    'download': [
        ('line', 12, 3.5, 12, 15), ('poly', [(7, 10.5), (12, 15.5), (17, 10.5)], False),
        ('line', 4.5, 20, 19.5, 20),
    ],
    'favorites': [('poly', _star(12, 12.6, 9.5, 4.1), True)],
    'settings': [('poly', _gear(12, 12, 9.4, 7.2), True), ('circle', 12, 12, 3)],
    'systems': [
        ('rect', 3.5, 3.5, 7, 7, 1.6), ('rect', 13.5, 3.5, 7, 7, 1.6),
        ('rect', 3.5, 13.5, 7, 7, 1.6), ('rect', 13.5, 13.5, 7, 7, 1.6),
    ],
    'user': [
        ('circle', 12, 8, 4),
        ('poly', [(4.5, 21), (5.2, 17.6), (8.4, 15.2), (15.6, 15.2), (18.8, 17.6), (19.5, 21)], False),
    ],
    'menu': [('line', 4, 6.5, 20, 6.5), ('line', 4, 12, 20, 12), ('line', 4, 17.5, 20, 17.5)],
    'more': [('dot', 5.5, 12, 1.9), ('dot', 12, 12, 1.9), ('dot', 18.5, 12, 1.9)],
    'play': [('poly', [(8, 5), (19, 12), (8, 19)], True)],
    'collections': [
        ('rect', 3.5, 8.5, 13, 12, 1.6),
        ('poly', [(7, 5.5), (19, 5.5), (20.5, 7), (20.5, 17)], False),
    ],
    'news': [
        ('rect', 3, 4.5, 18, 15, 1.6),
        ('line', 6.5, 8.5, 17.5, 8.5), ('line', 6.5, 12, 12.5, 12), ('line', 6.5, 15.5, 12.5, 15.5),
        ('rect', 14.5, 11.5, 3, 4, 0.4),
    ],
    'wishlist': [('poly', _heart(12, 12.4, 9.6), True)],
    'updates': [
        ('poly', _arc(12, 12, 7.6, -60, 225), False),
        ('poly', [(13.5, 3.6), (16, 5.6), (13.5, 8)], False),
        ('line', 12, 8.8, 12, 12.6), ('line', 12, 12.6, 14.6, 14.2),
    ],
    'playtime': [('circle', 12, 12, 9), ('line', 12, 7, 12, 12), ('line', 12, 12, 15.6, 14.2)],
    'calendar': [
        ('rect', 3.5, 5, 17, 15.5, 2), ('line', 3.5, 10, 20.5, 10),
        ('line', 8, 3, 8, 7), ('line', 16, 3, 16, 7),
        ('dot', 8, 14, 1.1), ('dot', 12, 14, 1.1), ('dot', 16, 14, 1.1),
    ],
    'ownership': [
        ('circle', 8, 12, 4.2), ('line', 12.2, 12, 21, 12),
        ('line', 17.5, 12, 17.5, 15.5), ('line', 21, 12, 21, 15),
    ],
}


def _num(value):
    return f'{value:.2f}'.rstrip('0').rstrip('.')


def _shape(prim, *, fill='none', fill_opacity=None, transform=None):
    """SVG element for one primitive (stroke comes from the parent group)."""
    kind = prim[0]
    extra = f' fill="{fill}"' + (f' fill-opacity="{fill_opacity}"' if fill_opacity is not None else '')
    if transform:
        extra += f' transform="{transform}"'
    if kind == 'line':
        _, x1, y1, x2, y2 = prim
        return f'<line x1="{_num(x1)}" y1="{_num(y1)}" x2="{_num(x2)}" y2="{_num(y2)}"/>'
    if kind == 'rect':
        _, x, y, w, h, r = prim
        return f'<rect x="{_num(x)}" y="{_num(y)}" width="{_num(w)}" height="{_num(h)}" rx="{_num(r)}"{extra}/>'
    if kind == 'circle':
        _, cx, cy, r = prim
        return f'<circle cx="{_num(cx)}" cy="{_num(cy)}" r="{_num(r)}"{extra}/>'
    if kind == 'poly':
        _, pts, closed = prim
        tag = 'polygon' if closed else 'polyline'
        points = ' '.join(f'{_num(x)},{_num(y)}' for x, y in pts)
        return f'<{tag} points="{points}"{extra if closed else " fill=" + chr(34) + "none" + chr(34)}/>'
    if kind == 'dot':
        _, cx, cy, r = prim
        return f'<circle cx="{_num(cx)}" cy="{_num(cy)}" r="{_num(r)}" fill="#000" stroke="none"/>'
    raise ValueError(kind)


def _closed(prim):
    return prim[0] in ('rect', 'circle') or (prim[0] == 'poly' and prim[2])


def _svg(body, *, extra_attrs=''):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"{extra_attrs}>'
            f'{body}</svg>\n')


def _stroke_group(glyph, *, width, cap='round', join='round', fill_closed=None, transform=None):
    parts = []
    for prim in glyph:
        if fill_closed is not None and _closed(prim):
            parts.append(_shape(prim, fill='#000', fill_opacity=fill_closed))
        else:
            parts.append(_shape(prim))
    t = f' transform="{transform}"' if transform else ''
    return (f'<g fill="none" stroke="#000" stroke-width="{width}" stroke-linecap="{cap}" '
            f'stroke-linejoin="{join}"{t}>' + ''.join(parts) + '</g>')


# --- one hand per theme --------------------------------------------------------

def render_outline(name, glyph):
    """Oneirodex default: clean 2px rounded outline."""
    return _svg(_stroke_group(glyph, width=2))


def render_sprout(name, glyph):
    """Mosslight: soft strokes, closed shapes washed in, a leaf sprouting off the corner."""
    leaf = ('<path d="M17.6 6.4c.4-2.6 2.4-4.3 5-4.4-.1 2.6-1.8 4.6-4.4 5" fill="#000" fill-opacity="0.85"/>'
            '<path d="M17.4 6.6l2.6-2.6" stroke="#000" stroke-width="0.9" stroke-linecap="round"/>')
    return _svg(_stroke_group(glyph, width=1.9, fill_closed=0.22, transform='translate(-0.6 0.6) scale(0.95)') + leaf)


def render_hairline(name, glyph):
    """Graphite Studio: drafting hairlines, square ends, registration ticks."""
    ticks = ''.join(
        f'<path d="{d}"/>' for d in (
            'M0.6 3.2V0.6h2.6', 'M20.8 0.6h2.6v2.6', 'M23.4 20.8v2.6h-2.6', 'M3.2 23.4H0.6v-2.6',
        )
    )
    return _svg(
        _stroke_group(glyph, width=1.15, cap='square', join='miter', transform='translate(1.2 1.2) scale(0.9)')
        + f'<g fill="none" stroke="#000" stroke-width="0.7">{ticks}</g>'
    )


def render_badge(name, glyph):
    """Signal Room: the glyph cut out of a solid instrument dial with a tick ring."""
    ticks = ''.join(
        '<line x1="{:.2f}" y1="{:.2f}" x2="{:.2f}" y2="{:.2f}"/>'.format(
            12 + 10.4 * math.cos(math.radians(a)), 12 + 10.4 * math.sin(math.radians(a)),
            12 + 11.6 * math.cos(math.radians(a)), 12 + 11.6 * math.sin(math.radians(a)),
        )
        for a in range(0, 360, 30)
    )
    cut = _stroke_group(glyph, width=2.4, transform='translate(4.2 4.2) scale(0.65)').replace('#000', '#fff')
    return _svg(
        '<defs><mask id="m" maskUnits="userSpaceOnUse" x="0" y="0" width="24" height="24">'
        '<rect width="24" height="24" fill="#fff"/>'
        + cut.replace('stroke="#fff"', 'stroke="#000"').replace('fill="#fff"', 'fill="#000"')
        + '</mask></defs>'
        '<circle cx="12" cy="12" r="9.6" fill="#000" mask="url(#m)"/>'
        f'<g stroke="#000" stroke-width="0.9" stroke-linecap="round">{ticks}</g>'
    )


def render_bubble(name, glyph):
    """Tape Deck: chunky rounded strokes, closed shapes half-filled — soft and toy-like."""
    return _svg(_stroke_group(glyph, width=3.1, fill_closed=0.45, transform='translate(1.2 1.2) scale(0.9)'))


def render_orbit(name, glyph):
    """Deep Space Media: a fine glyph with a tilted orbit ring and a moon."""
    ring = ('<ellipse cx="12" cy="12" rx="11.2" ry="4.2" transform="rotate(-24 12 12)" fill="none" '
            'stroke="#000" stroke-width="0.8" stroke-opacity="0.55"/>'
            '<circle cx="21.4" cy="7.4" r="1.25" fill="#000"/>')
    return _svg(ring + _stroke_group(glyph, width=1.5, fill_closed=0.18, transform='translate(2 2) scale(0.833)'))


def render_engraved(name, glyph):
    """Tideglass: engraved double line — a thick stroke with a hairline cut through it."""
    outer = _stroke_group(glyph, width=3.2).replace('stroke="#000"', 'stroke="#fff"')
    inner = _stroke_group(glyph, width=1.05)
    for_mask = outer.replace('fill="#000"', 'fill="#fff"') + inner.replace('fill="#000"', 'fill="#000"')
    dots = ''.join(_shape(p) for p in glyph if p[0] == 'dot')
    return _svg(
        '<defs><mask id="e" maskUnits="userSpaceOnUse" x="0" y="0" width="24" height="24">'
        '<rect width="24" height="24" fill="#000"/>' + for_mask + '</mask></defs>'
        '<rect width="24" height="24" fill="#000" mask="url(#e)"/>' + dots
    )


def render_pixel(name, glyph):
    """Afterglow Arcade: the glyph re-drawn on a 16x16 pixel grid, with a drop pixel shadow."""
    from PIL import Image, ImageDraw

    scale = 8  # supersample 16 -> 128
    grid = 16
    img = Image.new('L', (grid * scale, grid * scale), 0)
    draw = ImageDraw.Draw(img)
    k = grid * scale / 24

    def P(x, y):
        return (x * k, y * k)

    for prim in glyph:
        kind = prim[0]
        width = int(2.2 * k)
        if kind == 'line':
            _, x1, y1, x2, y2 = prim
            draw.line([P(x1, y1), P(x2, y2)], fill=255, width=width)
        elif kind == 'rect':
            _, x, y, w, h, _r = prim
            draw.rectangle([P(x, y), P(x + w, y + h)], outline=255, width=width)
        elif kind == 'circle':
            _, cx, cy, r = prim
            draw.ellipse([P(cx - r, cy - r), P(cx + r, cy + r)], outline=255, width=width)
        elif kind == 'poly':
            _, pts, closed = prim
            pts2 = [P(x, y) for x, y in pts]
            if closed:
                draw.polygon(pts2, outline=255, width=width)
            else:
                draw.line(pts2, fill=255, width=width, joint='curve')
        elif kind == 'dot':
            _, cx, cy, r = prim
            r = max(r, 1.6)
            draw.ellipse([P(cx - r, cy - r), P(cx + r, cy + r)], fill=255)
    small = img.resize((grid, grid), Image.BOX)
    on = {(x, y) for y in range(grid) for x in range(grid) if small.getpixel((x, y)) >= 96}
    unit = 24 / grid
    shadow = ''.join(
        f'<rect x="{_num((x + 1) * unit)}" y="{_num((y + 1) * unit)}" width="{_num(unit)}" height="{_num(unit)}"/>'
        for x, y in sorted(on) if (x + 1, y + 1) not in on
    )
    body = ''.join(
        f'<rect x="{_num(x * unit)}" y="{_num(y * unit)}" width="{_num(unit)}" height="{_num(unit)}"/>'
        for x, y in sorted(on)
    )
    return _svg(f'<g fill="#000" fill-opacity="0.4">{shadow}</g><g fill="#000">{body}</g>',
                extra_attrs=' shape-rendering="crispEdges"')


RENDERERS = {
    'outline': render_outline,
    'sprout': render_sprout,
    'pixel': render_pixel,
    'hairline': render_hairline,
    'badge': render_badge,
    'bubble': render_bubble,
    'orbit': render_orbit,
    'engraved': render_engraved,
}


def render_pack(style: str) -> dict[str, str]:
    renderer = RENDERERS[style]
    return {name: renderer(name, glyph) for name, glyph in GLYPHS.items()}
