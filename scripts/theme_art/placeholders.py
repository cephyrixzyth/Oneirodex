"""Branded fallback art per theme: the 2:3 "no cover" card and the 16:9 library hero.

Replaces the retired GameTheca rasters. Each theme gets its own motif behind the
Oneirodex wordmark, drawn in that theme's palette and display face.
"""
from __future__ import annotations

import math
import random

THEME_ART = {
    'default': dict(name='Oneirodex', bg=('#0f2a22', '#140b2e'), accent='#3ddc84', accent2='#7a5cff', text='#eafff3',
                    muted='#9fcdb6', font="'Segoe UI Semibold','Segoe UI',sans-serif", motif='aurora'),
    'greenhouse': dict(name='Mosslight', bg=('#16301f', '#081109'), accent='#75e6a4', accent2='#c98b4a', text='#effcf4',
                       muted='#9fcdb0', font="'Segoe UI Semibold','Segoe UI',sans-serif", motif='leaves'),
    'afterglow': dict(name='Afterglow Arcade', bg=('#2a0b24', '#0d0412'), accent='#ff5b9b', accent2='#65eaff', text='#fff0f6',
                      muted='#f6a7c9', font="'Arial Black','Segoe UI',sans-serif", motif='marquee'),
    'monochrome': dict(name='Graphite Studio', bg=('#1d2024', '#0e1013'), accent='#d9e0e8', accent2='#8c97a3', text='#f3f6f9',
                       muted='#a7b1bc', font="'Segoe UI','Helvetica Neue',sans-serif", motif='blueprint'),
    'signal': dict(name='Signal Room', bg=('#2a1a07', '#0d0802'), accent='#f1b85b', accent2='#c9711f', text='#fff3df',
                   muted='#e0b87a', font="'Trebuchet MS','Segoe UI',sans-serif", motif='radar'),
    'tape-deck': dict(name='Tape Deck', bg=('#2b1d45', '#140c24'), accent='#c4a3ff', accent2='#ff9a52', text='#f6efff',
                      muted='#cdb7f2', font="'Arial Rounded MT Bold','Segoe UI',sans-serif", motif='reels'),
    'deep-space': dict(name='Deep Space Media', bg=('#0b1c33', '#02050b'), accent='#6ac7ff', accent2='#b7e4ff', text='#eef8ff',
                       muted='#a5cdea', font="'Segoe UI Semibold','Segoe UI',sans-serif", motif='orbit'),
    'tideglass': dict(name='Tideglass Observatory', bg=('#0b3140', '#03121a'), accent='#81e1d2', accent2='#efc586', text='#effcfa',
                      muted='#a8d8d0', font="Georgia,'Times New Roman',serif", motif='tide'),
}

# The Oneirodex mark: a crescent dream-moon over a controller face — one glyph,
# reused at every size, coloured per theme.
def _mark(cx, cy, size, accent, accent2):
    s = size / 64
    uid = f'm{abs(hash((cx, cy, size))) % 100000}'
    return (
        f'<g transform="translate({cx - 32 * s:.1f} {cy - 32 * s:.1f}) scale({s:.4f})">'
        f'<defs><mask id="{uid}" maskUnits="userSpaceOnUse" x="0" y="0" width="64" height="64">'
        f'<rect width="64" height="64" fill="#fff"/><circle cx="38" cy="12" r="13" fill="#000"/></mask></defs>'
        f'<circle cx="31" cy="19" r="15" fill="{accent2}" mask="url(#{uid})"/>'
        f'<circle cx="47" cy="8" r="1.6" fill="{accent2}"/><circle cx="53" cy="17" r="1.1" fill="{accent2}"/>'
        f'<rect x="8" y="32" width="48" height="24" rx="12" fill="none" stroke="{accent}" stroke-width="4"/>'
        f'<rect x="17" y="42" width="9" height="3" rx="1.5" fill="{accent}"/><rect x="20" y="39" width="3" height="9" rx="1.5" fill="{accent}"/>'
        f'<circle cx="40" cy="41" r="2.4" fill="{accent}"/><circle cx="46" cy="47" r="2.4" fill="{accent}"/></g>'
    )


def _motif(kind, w, h, a, a2, seed):
    rnd = random.Random(seed)
    if kind == 'aurora':
        bands = []
        for i, col in enumerate((a, a2, a)):
            y = h * (0.18 + 0.14 * i)
            pts = ' '.join(f'{x:.0f},{y + math.sin(x / w * math.pi * 2 + i) * h * 0.06:.0f}' for x in range(0, w + 1, max(1, w // 24)))
            bands.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-opacity="{0.22 - i * 0.04:.2f}" '
                         f'stroke-width="{h * 0.07:.0f}" stroke-linecap="round" filter="url(#blur)"/>')
        return ''.join(bands)
    if kind == 'leaves':
        out = []
        for _ in range(26):
            x, y = rnd.uniform(0, w), rnd.uniform(0, h)
            r = rnd.uniform(0.02, 0.06) * w
            ang = rnd.uniform(0, 360)
            out.append(f'<ellipse cx="{x:.0f}" cy="{y:.0f}" rx="{r:.0f}" ry="{r * 0.42:.0f}" transform="rotate({ang:.0f} {x:.0f} {y:.0f})" '
                       f'fill="{a if rnd.random() > 0.3 else a2}" fill-opacity="{rnd.uniform(0.06, 0.16):.2f}"/>')
        return ''.join(out)
    if kind == 'marquee':
        step = max(w, h) / 40
        grid = ''.join(f'<line x1="{x:.0f}" y1="0" x2="{x:.0f}" y2="{h}"/>' for x in [i * step for i in range(int(w / step) + 1)])
        grid += ''.join(f'<line x1="0" y1="{y:.0f}" x2="{w}" y2="{y:.0f}"/>' for y in [i * step for i in range(int(h / step) + 1)])
        bulbs = ''.join(
            f'<rect x="{x:.0f}" y="{y:.0f}" width="{step * 0.6:.0f}" height="{step * 0.6:.0f}" fill="{a if i % 2 else a2}" fill-opacity="0.85"/>'
            for i, (x, y) in enumerate([(step * (k + 0.2), step * 0.6) for k in range(int(w / step))] + [(step * (k + 0.2), h - step * 1.2) for k in range(int(w / step))])
        )
        return f'<g stroke="{a}" stroke-opacity="0.07" stroke-width="1">{grid}</g>{bulbs}'
    if kind == 'blueprint':
        step = max(w, h) / 30
        grid = ''.join(f'<line x1="{i * step:.0f}" y1="0" x2="{i * step:.0f}" y2="{h}"/>' for i in range(int(w / step) + 1))
        grid += ''.join(f'<line x1="0" y1="{i * step:.0f}" x2="{w}" y2="{i * step:.0f}"/>' for i in range(int(h / step) + 1))
        m = step
        marks = (f'<path d="M{m} {m * 2}V{m}H{m * 2}M{w - m * 2} {m}H{w - m}V{m * 2}M{w - m} {h - m * 2}V{h - m}H{w - m * 2}'
                 f'M{m * 2} {h - m}H{m}V{h - m * 2}" fill="none" stroke="{a}" stroke-width="2" stroke-opacity="0.6"/>')
        return f'<g stroke="{a}" stroke-opacity="0.06" stroke-width="1">{grid}</g>{marks}'
    if kind == 'radar':
        cx, cy, r = w * 0.5, h * 0.5, max(w, h) * 0.55
        rings = ''.join(f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="{r * k / 5:.0f}" fill="none" stroke="{a}" stroke-opacity="0.09"/>' for k in range(1, 6))
        sweep = (f'<path d="M{cx:.0f} {cy:.0f}L{cx + r:.0f} {cy:.0f}A{r:.0f} {r:.0f} 0 0 0 {cx + r * math.cos(math.radians(-38)):.0f} {cy + r * math.sin(math.radians(-38)):.0f}z" '
                 f'fill="{a}" fill-opacity="0.07"/>')
        blips = ''.join(f'<circle cx="{rnd.uniform(0, w):.0f}" cy="{rnd.uniform(0, h):.0f}" r="{w * 0.006:.1f}" fill="{a}" fill-opacity="0.5"/>' for _ in range(8))
        return rings + sweep + blips
    if kind == 'reels':
        out = []
        for cx, cy in ((w * 0.28, h * 0.22), (w * 0.72, h * 0.22)):
            r = min(w, h) * 0.17
            out.append(f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="{r:.0f}" fill="none" stroke="{a2}" stroke-opacity="0.18" stroke-width="{r * 0.18:.0f}"/>')
            out.extend(
                f'<rect x="{cx - r * 0.08:.0f}" y="{cy - r * 0.62:.0f}" width="{r * 0.16:.0f}" height="{r * 0.4:.0f}" rx="{r * 0.06:.0f}" '
                f'fill="{a}" fill-opacity="0.18" transform="rotate({k * 60} {cx:.0f} {cy:.0f})"/>' for k in range(6)
            )
        blobs = ''.join(f'<circle cx="{rnd.uniform(0, w):.0f}" cy="{rnd.uniform(h * 0.5, h):.0f}" r="{rnd.uniform(0.03, 0.09) * w:.0f}" '
                        f'fill="{a if rnd.random() > 0.5 else a2}" fill-opacity="0.08"/>' for _ in range(7))
        return ''.join(out) + blobs
    if kind == 'orbit':
        stars = ''.join(f'<circle cx="{rnd.uniform(0, w):.0f}" cy="{rnd.uniform(0, h):.0f}" r="{rnd.uniform(0.4, 1.6) * w / 600:.1f}" fill="#ffffff" fill-opacity="{rnd.uniform(0.3, 0.9):.2f}"/>' for _ in range(90))
        pr = min(w, h) * 0.22
        px, py = w * 0.78, h * 0.2
        planet = (f'<circle cx="{px:.0f}" cy="{py:.0f}" r="{pr:.0f}" fill="{a}" fill-opacity="0.16"/>'
                  f'<ellipse cx="{px:.0f}" cy="{py:.0f}" rx="{pr * 1.7:.0f}" ry="{pr * 0.4:.0f}" transform="rotate(-18 {px:.0f} {py:.0f})" fill="none" stroke="{a2}" stroke-opacity="0.3" stroke-width="{pr * 0.06:.0f}"/>')
        return stars + planet
    if kind == 'tide':
        waves = []
        for i in range(7):
            y = h * (0.55 + i * 0.07)
            pts = ' '.join(f'{x:.0f},{y + math.sin(x / w * math.pi * 6 + i) * h * 0.012:.0f}' for x in range(0, w + 1, max(1, w // 40)))
            waves.append(f'<polyline points="{pts}" fill="none" stroke="{a}" stroke-opacity="{0.05 + i * 0.015:.3f}" stroke-width="{max(2, h * 0.004):.0f}"/>')
        port = min(w, h) * 0.16
        portholes = ''.join(
            f'<circle cx="{cx:.0f}" cy="{h * 0.2:.0f}" r="{port:.0f}" fill="none" stroke="{a2}" stroke-opacity="0.25" stroke-width="{port * 0.12:.0f}"/>'
            for cx in (w * 0.18, w * 0.82)
        )
        return ''.join(waves) + portholes
    raise ValueError(kind)


def _canvas(theme, w, h, title, subtitle, seed):
    t = THEME_ART[theme]
    a, a2 = t['accent'], t['accent2']
    big = min(w, h)
    if title is None:
        # Title-less background: the server sets each game's own title on it.
        mark = _mark(w / 2, h * 0.28, big * 0.26, a, a2)
    else:
        mark = _mark(w / 2, h * 0.42 if h > w else h * 0.38, big * (0.34 if h > w else 0.2), a, a2)
    title_size = big * (0.1 if h > w else 0.075)
    sub_size = big * (0.042 if h > w else 0.03)
    ty = h * 0.62 if h > w else h * 0.6
    frame_pad = big * 0.05
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">'
        f'<defs><radialGradient id="bg" cx="40%" cy="30%" r="85%"><stop offset="0" stop-color="{t["bg"][0]}"/>'
        f'<stop offset="1" stop-color="{t["bg"][1]}"/></radialGradient>'
        f'<filter id="blur" x="-20%" y="-50%" width="140%" height="200%"><feGaussianBlur stdDeviation="{big * 0.03:.0f}"/></filter></defs>'
        f'<rect width="{w}" height="{h}" fill="url(#bg)"/>'
        f'{_motif(t["motif"], w, h, a, a2, seed)}'
        f'<rect x="{frame_pad:.0f}" y="{frame_pad:.0f}" width="{w - 2 * frame_pad:.0f}" height="{h - 2 * frame_pad:.0f}" rx="{big * 0.03:.0f}" '
        f'fill="none" stroke="{a}" stroke-opacity="0.28" stroke-width="{max(2, big * 0.004):.0f}"/>'
        f'{mark}'
        + ('' if title is None else (
            f'<text x="{w / 2:.0f}" y="{ty:.0f}" text-anchor="middle" font-family="{t["font"]}" font-size="{title_size:.0f}" '
            f'font-weight="700" fill="{t["text"]}" letter-spacing="{title_size * 0.02:.1f}">{title}</text>'
            f'<text x="{w / 2:.0f}" y="{ty + title_size * 0.95:.0f}" text-anchor="middle" font-family="{t["font"]}" '
            f'font-size="{sub_size:.0f}" fill="{t["muted"]}">{subtitle}</text>'
        ))
        + '</svg>\n'
    )


def render_cover(theme: str) -> str:
    return _canvas(theme, 600, 900, 'Oneirodex', 'No cover art', seed=theme + 'cover')


def render_cover_blank(theme: str) -> str:
    """The theme's cover with no text, for per-game title placeholders."""
    return _canvas(theme, 600, 900, None, None, seed=theme + 'cover')


# Per-theme lettering for those titles: bundled OFL faces where the theme has a
# display voice (oneirodex/setup/fonts), the system sans otherwise.
PLACEHOLDER_TITLE_FONT = {
    'afterglow': 'PressStart2P-Regular.ttf',
    'deep-space': 'Orbitron-Variable.ttf',
    'signal': 'ShareTechMono-Regular.ttf',
    'tape-deck': 'VT323-Regular.ttf',
}


def render_hero(theme: str) -> str:
    return _canvas(theme, 1920, 1080, 'Oneirodex', THEME_ART[theme]['name'], seed=theme + 'hero')


def render_app_icon(theme: str = 'default', size: int = 512) -> str:
    t = THEME_ART[theme]
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" width="{size}" height="{size}">'
        f'<defs><radialGradient id="bg" cx="35%" cy="30%" r="85%"><stop offset="0" stop-color="{t["bg"][0]}"/>'
        f'<stop offset="1" stop-color="{t["bg"][1]}"/></radialGradient></defs>'
        f'<rect width="{size}" height="{size}" rx="{size * 0.22:.0f}" fill="url(#bg)"/>'
        f'{_mark(size / 2, size / 2, size * 0.72, t["accent"], t["accent2"])}</svg>\n'
    )
