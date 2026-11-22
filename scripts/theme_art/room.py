"""The default Oneirodex theme's own room: a dream room at night.

An aurora sky with the logo's crescent moon through a tall arched window, a
shelf of game cases and a desk with a CRT and a controller in silhouette. The
other themes have painted rooms; this one is drawn, in the same 16:9 format.
"""
from __future__ import annotations

import math
import random

W, H = 1920, 1080


def render_default_room() -> str:
    rnd = random.Random(20261121)
    stars = ''.join(
        f'<circle cx="{rnd.uniform(420, 1500):.0f}" cy="{rnd.uniform(90, 600):.0f}" r="{rnd.uniform(0.8, 2.4):.1f}" '
        f'fill="#ffffff" fill-opacity="{rnd.uniform(0.35, 0.95):.2f}"/>'
        for _ in range(140)
    )

    def band(y, amp, col, op, width, phase):
        pts = ' '.join(
            f'{x},{y + math.sin(x / 260 + phase) * amp + math.sin(x / 90 + phase * 2) * amp * 0.25:.0f}'
            for x in range(380, 1561, 20)
        )
        return (f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-opacity="{op}" '
                f'stroke-width="{width}" stroke-linecap="round" filter="url(#soft)"/>')

    aurora = (band(250, 60, '#3ddc84', 0.55, 90, 0.2) + band(330, 50, '#7a5cff', 0.45, 80, 1.4)
              + band(200, 40, '#36c9e8', 0.35, 60, 2.6) + band(390, 30, '#3ddc84', 0.25, 50, 3.3))
    # Shelf of game cases (left) with a few lit spines.
    cases = []
    x = 60
    for i in range(26):
        w = rnd.choice((18, 20, 22, 26))
        h = rnd.choice((150, 160, 170))
        lit = rnd.random() < 0.22
        col = rnd.choice(('#3ddc84', '#7a5cff', '#36c9e8', '#ff6fae')) if lit else '#0d1420'
        cases.append(f'<rect x="{x}" y="{560 - h}" width="{w}" height="{h}" rx="2" fill="{col}" fill-opacity="{0.55 if lit else 1}"/>')
        x += w + 3
        if x > 330:
            break
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">
<defs>
  <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#0b0f2e"/><stop offset="0.55" stop-color="#13244a"/><stop offset="1" stop-color="#0f3a3a"/>
  </linearGradient>
  <linearGradient id="wall" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#0d1124"/><stop offset="1" stop-color="#070912"/>
  </linearGradient>
  <radialGradient id="moonglow" cx="0.5" cy="0.5" r="0.5">
    <stop offset="0" stop-color="#b9a6ff" stop-opacity="0.55"/><stop offset="1" stop-color="#b9a6ff" stop-opacity="0"/>
  </radialGradient>
  <radialGradient id="screen" cx="0.5" cy="0.5" r="0.6">
    <stop offset="0" stop-color="#7cf3b6"/><stop offset="1" stop-color="#1b6b4a"/>
  </radialGradient>
  <linearGradient id="lamp" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#ffcf8a" stop-opacity="0.28"/><stop offset="1" stop-color="#ffcf8a" stop-opacity="0"/>
  </linearGradient>
  <filter id="soft" filterUnits="userSpaceOnUse" x="0" y="-200" width="1920" height="1200"><feGaussianBlur stdDeviation="22"/></filter>
  <mask id="crescent"><rect width="{W}" height="{H}" fill="#fff"/><circle cx="1215" cy="210" r="88" fill="#000"/></mask>
  <clipPath id="window"><path d="M400 900V330a560 300 0 0 1 1120 0v570z"/></clipPath>
</defs>
<rect width="{W}" height="{H}" fill="url(#wall)"/>
<g clip-path="url(#window)">
  <rect x="380" y="0" width="1160" height="900" fill="url(#sky)"/>
  {aurora}
  {stars}
  <circle cx="1170" cy="250" r="230" fill="url(#moonglow)"/>
  <circle cx="1160" cy="250" r="105" fill="#c8bbff" mask="url(#crescent)"/>
  <path d="M380 760c180-60 330-40 470-90s300-30 420-10 220-40 290-20v260H380z" fill="#0b2128"/>
  <path d="M380 820c210-30 390-10 560-40s320 0 600-30v150H380z" fill="#081619"/>
</g>
<path d="M400 900V330a560 300 0 0 1 1120 0v570" fill="none" stroke="#1d2540" stroke-width="26"/>
<line x1="960" y1="40" x2="960" y2="900" stroke="#1d2540" stroke-width="14"/>
<line x1="400" y1="560" x2="1520" y2="560" stroke="#1d2540" stroke-width="12"/>
<rect x="40" y="560" width="320" height="16" fill="#1a2238"/>
{''.join(cases)}
<rect x="40" y="320" width="320" height="16" fill="#1a2238"/>
<path d="M1700 110L1560 900h280z" fill="url(#lamp)"/>
<line x1="1700" y1="0" x2="1700" y2="44" stroke="#2a2f45" stroke-width="4"/>
<path d="M1660 44h80l30 66h-140z" fill="#2a2f45"/><ellipse cx="1700" cy="112" rx="64" ry="6" fill="#ffcf8a" fill-opacity="0.7"/>
<rect x="0" y="900" width="{W}" height="180" fill="#05070d"/>
<rect x="1180" y="880" width="640" height="26" rx="6" fill="#141a2c"/>
<rect x="1300" y="700" width="300" height="190" rx="22" fill="#10162a"/>
<rect x="1326" y="722" width="248" height="146" rx="14" fill="url(#screen)" fill-opacity="0.85"/>
<g fill="none" stroke="#0b3b29" stroke-width="3" stroke-opacity="0.5">
  <line x1="1330" y1="760" x2="1570" y2="760"/><line x1="1330" y1="800" x2="1570" y2="800"/><line x1="1330" y1="840" x2="1570" y2="840"/>
</g>
<rect x="1240" y="852" width="120" height="34" rx="17" fill="none" stroke="#3ddc84" stroke-width="5" stroke-opacity="0.8"/>
<circle cx="1270" cy="869" r="5" fill="#3ddc84" fill-opacity="0.8"/><circle cx="1330" cy="866" r="4" fill="#3ddc84" fill-opacity="0.8"/>
<rect x="120" y="760" width="520" height="140" rx="10" fill="#0c1120"/>
<rect x="150" y="730" width="140" height="40" rx="6" fill="#151c33"/>
<rect x="320" y="736" width="40" height="34" rx="4" fill="#7a5cff" fill-opacity="0.35"/>
</svg>
'''
