#!/usr/bin/env python3
"""A virtual game controller driving Big Picture.

Chromium has no pad attached, so an init script replaces ``navigator.getGamepads``
with a state object the test controls. Checks the real Big Picture page: d-pad /
stick moves focus tile to tile (and back), and the confirm button opens the
focused game's details page.

    python scripts/vdevice/gamepad.py          # needs scripts/serve_capture.py running
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))

from capture_common import BASE, block_streams, login  # noqa: E402

CHROMIUM = os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE', '/opt/pw-browsers/chromium')

FAKE_PAD = """
(() => {
  const buttons = Array.from({length: 17}, () => ({pressed: false, touched: false, value: 0}));
  const pad = {id: 'Virtual Pad (STANDARD GAMEPAD)', index: 0, connected: true, mapping: 'standard',
               axes: [0, 0, 0, 0], buttons, timestamp: 0};
  window.__pad = {
    press(i) { buttons[i].pressed = true; buttons[i].value = 1; },
    release(i) { buttons[i].pressed = false; buttons[i].value = 0; },
    stick(x) { pad.axes[0] = x; },
  };
  navigator.getGamepads = () => [pad, null, null, null];
})();
"""
DPAD_LEFT, DPAD_RIGHT, CONFIRM = 14, 15, 0


def out(text: str = '') -> None:
    sys.stdout.write(text + '\n')


def main() -> int:
    from playwright.sync_api import sync_playwright

    failures: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=CHROMIUM)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        context.add_init_script(FAKE_PAD)
        block_streams(context)
        page = context.new_page()
        if not login(page):
            out('login failed; is the capture server up?')
            return 2
        page.goto(f'{BASE}/big-picture', wait_until='domcontentloaded')
        try:
            page.wait_for_function("() => document.querySelectorAll('[data-od-bp-tile], .od-bp-tile, a[href*=\"game_details\"]').length > 2", timeout=40_000)
        except Exception:  # noqa: BLE001
            out('Big Picture did not show at least 3 tiles (is the library seeded?)')
            return 2
        page.wait_for_timeout(800)

        def focused() -> str:
            return page.evaluate("() => (document.activeElement && (document.activeElement.getAttribute('href') || document.activeElement.textContent || '').trim().slice(0, 80)) || ''")

        def tap(button: int) -> None:
            page.evaluate(f'window.__pad.press({button})')
            page.wait_for_timeout(250)
            page.evaluate(f'window.__pad.release({button})')
            page.wait_for_timeout(450)

        first = focused()
        tap(DPAD_RIGHT)
        second = focused()
        tap(DPAD_RIGHT)
        third = focused()
        tap(DPAD_LEFT)
        back = focused()
        out(f'focus: {first!r} -> {second!r} -> {third!r} -> (left) {back!r}')
        if len({first, second, third}) != 3:
            failures.append('d-pad right did not move focus tile to tile')
        if back != second:
            failures.append('d-pad left did not move focus back')

        page.evaluate('window.__pad.stick(1)')
        page.wait_for_timeout(500)
        page.evaluate('window.__pad.stick(0)')
        stick = focused()
        if stick == back:
            failures.append('right stick did not move focus')

        # Confirm is ignored while the last navigation is recent (a deliberate
        # guard against a stray A press), so let it settle first.
        page.wait_for_timeout(900)
        tap(CONFIRM)
        try:
            page.wait_for_url('**/game_details/**', timeout=8_000)
        except Exception:  # noqa: BLE001
            failures.append(f'confirm did not open game details (on {page.url})')
        browser.close()

    for failure in failures:
        out('FAIL ' + failure)
    out('virtual gamepad: ' + ('ok' if not failures else f'{len(failures)} failure(s)'))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
