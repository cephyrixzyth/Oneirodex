"""
Shared pieces for the docs capture scripts.

`capture_docs_media.py` (stills) and `capture_howto_videos.py` (narrated
clips) drive the same capture instance the same way; this module is where the
things they must agree on live — how to log in, how to get a page into a
photographable state, what "healthy" means, and the app-styled title card and
caption overlay that make a clip read as Oneirodex rather than as a browser.

Everything here talks to a running instance on `CAPTURE_BASE_URL`, normally
the one `scripts/serve_capture.py` brings up.
"""
from __future__ import annotations

import html
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BASE = os.environ.get("CAPTURE_BASE_URL", "http://127.0.0.1:5006").rstrip("/")
USER = os.environ.get("CAPTURE_USER", "admin")
PASSWORD = os.environ.get("CAPTURE_PASS", "CaptureAdmin1!")

# The default theme's tokens (oneirodex/static/library/themes/default/css/
# od-tokens.css). Cards and captions are drawn with these, not a lookalike.
TOKENS = {
    "bg": "#0b0d10",
    "surface": "#141820",
    "surface2": "#1c2230",
    "text": "#f2f4f8",
    "muted": "#c4ccd8",
    "accent": "#2fd67b",
    "accent2": "#86efac",
    "border": "rgba(255,255,255,0.12)",
}

FONT_STACK = (
    "'Segoe UI', system-ui, -apple-system, 'Helvetica Neue', Arial, sans-serif"
)

_MARK_SVG = (ROOT / "docs" / "assets" / "readme" / "oneirodex_mark.svg").read_text(encoding="utf-8")
# Strip the XML prologue-ish bits so the mark can be inlined in HTML.
_MARK_INLINE = re.sub(r"<\?xml[^>]*\?>", "", _MARK_SVG).strip()


# --------------------------------------------------------------------------
# page state
# --------------------------------------------------------------------------

_ERROR_MARKERS = (
    "internal server error",
    "500 internal server",
    "502 bad gateway",
    "503 service unavailable",
    "504 gateway",
    "traceback (most recent call last)",
    "werkzeug debugger",
)


def page_is_healthy(page) -> tuple[bool, str]:
    """True when the page looks like real, styled UI rather than an error.

    Checked before every still and at the end of every clip. A mid-run 500
    once wrote "Internal Server Error" into the README hero and reported
    success; a missing theme tree once shipped a full set of unstyled shots
    because every *word* was present. Both are caught here.
    """
    try:
        body = (page.inner_text("body", timeout=5_000) or "").strip()
    except Exception as exc:  # noqa: BLE001
        return False, f"could not read body ({type(exc).__name__})"

    low = body.lower()
    if re.search(r"\bloading\s+discover\b", low):
        return False, "Discover is still loading"
    for marker in _ERROR_MARKERS:
        if marker in low and len(body) < 600:
            return False, f"error page ({marker!r})"
    if len(body) < 40:
        return False, f"page nearly empty ({len(body)} chars)"

    try:
        themed_rules = page.evaluate(
            """() => [...document.styleSheets]
                 .filter(s => (s.href || '').includes('/library/themes/'))
                 .reduce((n, s) => {
                   try { return n + s.cssRules.length } catch { return n }
                 }, 0)"""
        )
    except Exception:  # noqa: BLE001
        themed_rules = None
    if themed_rules == 0:
        return False, "theme stylesheets loaded but empty — page is unstyled"
    return True, "ok"


def login(page) -> bool:
    """Sign in through the real form. Returns False if we are still on /login.

    Enter in the password field, not a click on the first submit button: the
    login page also carries a hidden "Delete Game" confirm form, and its
    submit button is first in the DOM.
    """
    try:
        page.goto(f"{BASE}/login", wait_until="domcontentloaded", timeout=25_000)
        page.fill("#username", USER)
        page.fill("#password", PASSWORD)
        page.press("#password", "Enter")
        page.wait_for_load_state("domcontentloaded", timeout=25_000)
        page.wait_for_timeout(600)
        return "/login" not in page.url
    except Exception as exc:  # noqa: BLE001
        print(f"    login failed: {type(exc).__name__}: {str(exc)[:120]}")
        return False


def block_streams(context) -> None:
    """Long-lived streams would pin a single-worker uvicorn for the whole run."""
    context.route(
        "**/api/activity/stream*",
        lambda route: route.fulfill(status=204, body="", headers={"content-type": "text/plain"}),
    )
    context.route("**/api/events/**", lambda route: route.fulfill(status=204, body=""))


def close_overlays(page) -> None:
    """Shut the chat slide-out and the friends dock if either is open.

    Both are global — they survive navigation — so any page can be captured
    underneath a panel that a previous step opened. `discover.png` once was a
    blank page behind an open chat panel.
    """
    for sel in (
        'button[aria-label="Close chat"]',
        'button[aria-label="Close friends"]',
        'button[aria-label="Close Friends"]',
        '.od-social-dock button[aria-label*="lose"]',
    ):
        try:
            btn = page.locator(sel).first
            if btn.count() and btn.is_visible():
                btn.click(timeout=3_000)
                page.wait_for_timeout(350)
        except Exception:  # noqa: BLE001
            continue


def settle(page, ms: int = 900) -> None:
    """Wait for the SPA's data, not just its shell.

    `domcontentloaded` is when React mounts; the page's own "Loading…" is what
    tells us its fetch has landed. A page that never shows the placeholder
    just falls through.
    """
    page.wait_for_timeout(ms)
    try:
        loading = page.get_by_text("Loading", exact=False).first
        if loading.count() and loading.is_visible():
            loading.wait_for(state="hidden", timeout=12_000)
            page.wait_for_timeout(400)
    except Exception:  # noqa: BLE001
        pass


def goto(page, path: str, *, timeout: int = 25_000, settle_ms: int = 900) -> bool:
    try:
        page.goto(f"{BASE}{path}", wait_until="domcontentloaded", timeout=timeout)
        settle(page, settle_ms)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"    nav failed {path}: {type(exc).__name__}")
        return False


# --------------------------------------------------------------------------
# app-styled chrome for clips
# --------------------------------------------------------------------------

def title_card_html(kicker: str, title: str, subtitle: str = "", *, number: str = "") -> str:
    """A full-page card in the app's own tokens — intro and outro of a clip."""
    t = TOKENS
    num = f'<div class="num">{html.escape(number)}</div>' if number else ""
    sub = f'<p class="sub">{html.escape(subtitle)}</p>' if subtitle else ""
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>
  html,body{{margin:0;height:100%;background:{t['bg']};color:{t['text']};font-family:{FONT_STACK};}}
  body{{display:grid;place-items:center;overflow:hidden;position:relative;}}
  .glow{{position:absolute;inset:auto;width:70vw;height:70vw;left:50%;top:50%;transform:translate(-50%,-50%);
        background:radial-gradient(closest-side, rgba(47,214,123,0.16), rgba(47,214,123,0) 70%);pointer-events:none;}}
  .grid{{position:absolute;inset:0;background-image:linear-gradient({t['border']} 1px, transparent 1px),
        linear-gradient(90deg, {t['border']} 1px, transparent 1px);background-size:64px 64px;opacity:.35;
        mask-image:radial-gradient(circle at 50% 50%, #000 20%, transparent 75%);-webkit-mask-image:radial-gradient(circle at 50% 50%, #000 20%, transparent 75%);}}
  .card{{position:relative;display:flex;flex-direction:column;align-items:center;gap:18px;text-align:center;max-width:70vw;}}
  .mark{{width:112px;height:112px;filter:drop-shadow(0 12px 40px rgba(47,214,123,0.35));}}
  .kicker{{color:{t['accent']};letter-spacing:.22em;text-transform:uppercase;font-weight:700;font-size:15px;}}
  h1{{margin:0;font-size:56px;line-height:1.05;font-weight:800;letter-spacing:-0.01em;}}
  .sub{{margin:0;color:{t['muted']};font-size:22px;line-height:1.4;max-width:46ch;}}
  .num{{position:absolute;right:48px;bottom:40px;color:{t['muted']};font-size:16px;letter-spacing:.14em;opacity:.8;}}
  .bar{{position:absolute;left:0;right:0;bottom:0;height:6px;background:linear-gradient(90deg,#12a4a0,{t['accent']},#4ef2a1);}}
</style></head>
<body>
  <div class="grid"></div><div class="glow"></div>
  <div class="card">
    <div class="mark">{_MARK_INLINE}</div>
    <div class="kicker">{html.escape(kicker)}</div>
    <h1>{html.escape(title)}</h1>
    {sub}
  </div>
  {num}
  <div class="bar"></div>
</body></html>"""


# Lower-third caption, injected once per page and updated per step. Lives in
# the page so every player shows it — no subtitle track support required —
# and so it is drawn in the same tokens as the UI behind it.
CAPTION_INIT_JS = """
(() => {
  if (window.__odCaption) return;
  const T = %s;
  function ensure() {
    let el = document.getElementById('od-howto-caption');
    if (el) return el;
    el = document.createElement('div');
    el.id = 'od-howto-caption';
    el.setAttribute('aria-hidden', 'true');
    Object.assign(el.style, {
      position: 'fixed', left: '50%%', bottom: '28px', transform: 'translateX(-50%%)',
      maxWidth: '72vw', padding: '12px 20px', borderRadius: '12px',
      background: 'rgba(11,13,16,0.86)', color: T.text, border: '1px solid ' + T.border,
      boxShadow: '0 12px 40px rgba(0,0,0,0.45), inset 0 0 0 1px rgba(47,214,123,0.12)',
      font: '600 19px/1.35 ' + T.font, textAlign: 'center', letterSpacing: '0.005em',
      zIndex: '2147483646', pointerEvents: 'none', opacity: '0',
      transition: 'opacity 220ms ease', backdropFilter: 'blur(8px)',
    });
    const bar = document.createElement('span');
    Object.assign(bar.style, {
      position: 'absolute', left: '14px', right: '14px', bottom: '-1px', height: '2px',
      borderRadius: '2px', background: 'linear-gradient(90deg,#12a4a0,' + T.accent + ',#4ef2a1)',
    });
    el.appendChild(document.createElement('span'));
    el.appendChild(bar);
    (document.body || document.documentElement).appendChild(el);
    return el;
  }
  window.__odCaption = (text) => {
    const el = ensure();
    el.firstChild.textContent = text || '';
    el.style.opacity = text ? '1' : '0';
  };
  // Re-attach after the SPA replaces <body> children.
  new MutationObserver(() => {
    const el = document.getElementById('od-howto-caption');
    if (!el && window.__odCaptionLast) { ensure().firstChild.textContent = window.__odCaptionLast; }
  }).observe(document.documentElement, { childList: true, subtree: false });
})();
""" % (
    '{"text":"%s","border":"%s","accent":"%s","font":"%s"}'
    % (TOKENS["text"], TOKENS["border"], TOKENS["accent"], FONT_STACK.replace('"', '\\"'))
)


def install_caption(context) -> None:
    context.add_init_script(CAPTION_INIT_JS)


def caption(page, text: str) -> None:
    try:
        page.evaluate(
            "(t) => { window.__odCaptionLast = t; if (window.__odCaption) window.__odCaption(t); }",
            text,
        )
    except Exception:  # noqa: BLE001
        pass
