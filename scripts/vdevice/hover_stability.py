#!/usr/bin/env python3
"""Does the top bar stay put while the pointer crosses tiles?

Regression check for the "top nav blips in and out" bug: the shell used to flip
the scroll pane above the bar via `:has(.game-card:hover)`, so every tile gap
toggled it. Moves a real mouse across the first row of tiles on a page and
samples, at each step, which element sits at the bar's centre and the scroll
pane's z-index. Stable means one answer for the whole sweep.

    python scripts/vdevice/hover_stability.py /discover
    python scripts/vdevice/hover_stability.py /library --css oneirodex/setup/default_theme/css/od-shell.css \
        --css oneirodex/setup/default_theme/css/od-era.css

``--css`` serves that file in place of the theme file of the same name (repeat
it for several), to test stylesheets before they are copied into the served theme.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))

from capture_common import BASE, block_streams, login  # noqa: E402

CHROMIUM = os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE', '/opt/pw-browsers/chromium')

SAMPLE_JS = """() => {
  const bar = document.querySelector('.od-topbar');
  if (!bar) return {bar: false};
  const r = bar.getBoundingClientRect();
  const el = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  const main = document.querySelector('.od-shell__main');
  return {
    bar: true,
    onTop: !!el && bar.contains(el),
    mainZ: main ? getComputedStyle(main).zIndex : null,
    mainBg: main ? getComputedStyle(main).backgroundColor : null,
  };
}"""


def out(text: str = '') -> None:
    sys.stdout.write(text + '\n')


def _serve(body: str):
    def handler(route, _request=None):
        route.fulfill(status=200, body=body, headers={'content-type': 'text/css'})

    return handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('route', nargs='?', default='/discover')
    parser.add_argument('--css', type=Path, action='append', default=[], help='serve this file in place of the theme file of the same name (repeatable)')
    args = parser.parse_args(argv)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=CHROMIUM)
        context = browser.new_context(viewport={'width': 1440, 'height': 900})
        block_streams(context)
        for css in args.css:
            context.route(f'**/{css.name}*', _serve(css.read_text(encoding='utf-8')))
        page = context.new_page()
        if not login(page):
            out('login failed; is the capture server up?')
            return 2
        page.goto(f'{BASE}{args.route}', wait_until='domcontentloaded')
        page.wait_for_function("() => document.querySelectorAll('.game-card').length > 0", timeout=40_000)
        page.wait_for_timeout(800)
        boxes = page.eval_on_selector_all(
            '.game-card',
            '(els) => els.slice(0, 6).map((e) => { const r = e.getBoundingClientRect();'
            ' return {x: r.left, y: r.top, w: r.width, h: r.height}; })',
        )
        samples = []
        for box in boxes:
            # Walk through the tile and out into the gap after it.
            for dx in (0.2, 0.5, 0.8, 1.05):
                page.mouse.move(box['x'] + box['w'] * dx, box['y'] + box['h'] * 0.5, steps=3)
                page.wait_for_timeout(120)
                samples.append(page.evaluate(SAMPLE_JS))
        browser.close()

    if not samples or not samples[0].get('bar'):
        out('no top bar found')
        return 2
    answers = {(s['onTop'], s['mainZ'], s['mainBg']) for s in samples}
    out(f'{len(samples)} samples, {len(answers)} distinct state(s): {sorted(answers, key=str)}')
    stable = len(answers) == 1 and all(s['onTop'] for s in samples)
    out('STABLE' if stable else 'UNSTABLE: the bar or the scroll pane changed while hovering')
    return 0 if stable else 1


if __name__ == '__main__':
    raise SystemExit(main())
