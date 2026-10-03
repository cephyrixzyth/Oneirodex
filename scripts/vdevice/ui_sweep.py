#!/usr/bin/env python3
"""Layer 4: walk every member and admin route in a real (headless) browser.

Needs a running instance (``python scripts/serve_capture.py``) and Playwright.
For each route, at a desktop and a phone viewport, it records: HTTP status,
console errors, uncaught page errors, same-origin requests that returned 5xx,
a blank page (almost no visible text), and horizontal page overflow. Admin
routes are discovered by crawling links from the admin dashboard, so a new
page is swept without editing this file.

    python scripts/vdevice/ui_sweep.py
    python scripts/vdevice/ui_sweep.py --out /tmp/sweep --viewports desktop
    python scripts/vdevice/ui_sweep.py --member          # also sweep as the second member

Exit status is 1 when any route has a finding, so it can gate a job.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))

from capture_common import BASE, block_streams, login  # noqa: E402

CHROMIUM = os.environ.get('PLAYWRIGHT_CHROMIUM_EXECUTABLE', '/opt/pw-browsers/chromium')

MEMBER_ROUTES = [
    '/', '/discover', '/library', '/systems', '/systems/catalog', '/systems/completion',
    '/collections', '/favorites', '/wishlist', '/news', '/calendar', '/trailers', '/activity',
    '/chat', '/downloads', '/updates', '/playtime', '/notifications', '/ownership',
    '/tokens', '/acquire', '/ways-to-play', '/big-picture', '/vr', '/help', '/report', '/social-companion',
]
VIEWPORTS = {
    'desktop': {'width': 1440, 'height': 900},
    'phone': {'width': 390, 'height': 844},
    'phone-landscape': {'width': 844, 'height': 390},
    'tablet': {'width': 820, 'height': 1180},
    'tv': {'width': 1920, 'height': 1080},
    'quest': {'width': 1832, 'height': 1920},
}
DEFAULT_VIEWPORTS = 'desktop,phone'
#: Pages that render a loading message until their data arrives. Still showing
#: it after this long is a stuck page, which a text-length check cannot see.
LOADING_WAIT_MS = 12_000
#: Noise that is environmental in a sandbox (no outbound network), not an app bug.
IGNORED_CONSOLE = ('net::ERR_', 'Failed to load resource: net::', 'favicon', 'ERR_BLOCKED', 'ERR_PROXY')


def out(text: str = '') -> None:
    sys.stdout.write(text + '\n')


def discover_admin_routes(page) -> list[str]:
    page.goto(f'{BASE}/admin/dashboard', wait_until='domcontentloaded', timeout=30_000)
    page.wait_for_timeout(1200)
    hrefs = page.eval_on_selector_all('a[href^="/admin"]', 'els => els.map(e => e.getAttribute("href"))')
    routes = {h.split('#')[0].split('?')[0] for h in hrefs if h}
    # One level deeper: section pages link to their own sub-pages.
    for first in sorted(routes):
        try:
            page.goto(f'{BASE}{first}', wait_until='domcontentloaded', timeout=30_000)
            page.wait_for_timeout(600)
            more = page.eval_on_selector_all('a[href^="/admin"]', 'els => els.map(e => e.getAttribute("href"))')
        except Exception:  # noqa: BLE001
            continue
        routes |= {h.split('#')[0].split('?')[0] for h in more if h}
    skip = ('/logout', '/delete', '/reset', '/download', '/export', '/backup', '/restart')
    return sorted(r for r in routes if not any(s in r for s in skip))


def sweep_route(context, route: str, shots: Path | None, tag: str) -> dict:
    page = context.new_page()
    findings: list[str] = []
    server_errors: list[str] = []
    client_errors: list[str] = []
    console: list[str] = []
    page_errors: list[str] = []
    page.on('console', lambda m: console.append(m.text) if m.type == 'error' else None)
    page.on('pageerror', lambda e: page_errors.append(str(e)[:200]))
    page.on(
        'response',
        lambda r: server_errors.append(f'{r.status} {r.url.replace(BASE, "")}')
        if r.status >= 500 and r.url.startswith(BASE)
        else None,
    )
    page.on(
        'response',
        lambda r: client_errors.append(f'{r.status} {r.url.replace(BASE, "")}')
        if 400 <= r.status < 500 and r.url.startswith(BASE) and r.request.resource_type in ('xhr', 'fetch')
        else None,
    )
    status = None
    try:
        resp = page.goto(f'{BASE}{route}', wait_until='domcontentloaded', timeout=30_000)
        status = resp.status if resp else None
        page.wait_for_timeout(1500)
        try:
            page.wait_for_function(
                "() => !/\\bLoading\\b[^\\n]{0,40}(\u2026|\\.{2,3})/.test(document.body.innerText)", timeout=LOADING_WAIT_MS,
            )
        except Exception:  # noqa: BLE001
            findings.append('still showing a loading message after %ds' % (LOADING_WAIT_MS // 1000))
        metrics = page.evaluate(
            '() => ({text: (document.body.innerText || "").trim().length,'
            ' overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth})'
        )
    except Exception as exc:  # noqa: BLE001
        findings.append(f'navigation failed: {type(exc).__name__}: {str(exc)[:100]}')
        metrics = {'text': 0, 'overflow': 0}
    if status is not None and status >= 400:
        findings.append(f'HTTP {status}')
    if server_errors:
        findings.append('5xx: ' + '; '.join(sorted(set(server_errors))[:3]))
    if client_errors:
        findings.append('4xx API: ' + '; '.join(sorted(set(client_errors))[:3]))
    # A bare "Failed to load resource" is already explained by the URL above.
    real_console = [
        c for c in console
        if not any(i in c for i in IGNORED_CONSOLE) and not c.startswith('Failed to load resource')
    ]
    if real_console:
        findings.append('console: ' + ' | '.join(real_console[:2])[:200])
    if page_errors:
        findings.append('pageerror: ' + page_errors[0])
    if metrics['text'] < 20:
        findings.append(f"blank page ({metrics['text']} chars of text)")
    if metrics['overflow'] > 2:
        findings.append(f"horizontal overflow {metrics['overflow']}px")
    if shots is not None:
        shots.mkdir(parents=True, exist_ok=True)
        name = (route.strip('/').replace('/', '_') or 'home') + f'.{tag}.png'
        try:
            page.screenshot(path=str(shots / name))
        except Exception:  # noqa: BLE001
            pass
    page.close()
    return {'route': route, 'viewport': tag, 'status': status, 'findings': findings}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--out', type=Path, default=ROOT / 'data' / 'vdevice-sweep')
    parser.add_argument('--viewports', default=DEFAULT_VIEWPORTS, help='comma list of: ' + ', '.join(VIEWPORTS))
    parser.add_argument('--no-screenshots', action='store_true')
    parser.add_argument('--limit', type=int, default=0, help='sweep only the first N routes (debugging)')
    args = parser.parse_args(argv)

    from playwright.sync_api import sync_playwright

    results: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=CHROMIUM)
        for tag in [v for v in args.viewports.split(',') if v in VIEWPORTS]:
            context = browser.new_context(viewport=VIEWPORTS[tag], ignore_https_errors=True)
            block_streams(context)
            page = context.new_page()
            if not login(page):
                out('login failed; is the capture server up (scripts/serve_capture.py)?')
                return 2
            routes = MEMBER_ROUTES + discover_admin_routes(page)
            page.close()
            if args.limit:
                routes = routes[: args.limit]
            for route in routes:
                result = sweep_route(context, route, None if args.no_screenshots else args.out / tag, tag)
                results.append(result)
                mark = 'FAIL' if result['findings'] else 'ok  '
                out(f"{mark} {tag:7} {route}" + (f"  -> {'; '.join(result['findings'])}" if result['findings'] else ''))
            context.close()
        browser.close()

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / 'report.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    bad = [r for r in results if r['findings']]
    out(f'\n{len(results)} route/viewport checks, {len(bad)} with findings -> {args.out / "report.json"}')
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main())
