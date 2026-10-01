"""Static guards for client-side injection fixes in the classic (Jinja) JS.

Behaviour is pinned by the node harnesses in ``tests/js/``
(``od_dom_actions.test.mjs``, ``od_bridge_origin.test.mjs``,
``admin_html_injection.test.mjs``). This file covers what those cannot reach
from pytest:

* ``od_dom_actions.js`` runs only the handlers on its allowlist, so a template
  or shipped script that names a new ``data-od-click`` / ``data-od-change``
  handler without listing it would go dead silently. The two lists must match
  what the repo actually uses.
* ``admin_manage_libs.js`` builds its progress line inside a closure the node
  harness cannot load, so the escaping is asserted on the source.
"""

from __future__ import annotations

import re
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / 'oneirodex'
DOM_ACTIONS = PKG / 'static' / 'js' / 'od_dom_actions.js'
LIBS_JS = PKG / 'setup' / 'default_theme' / 'js' / 'admin_manage_libs.js'

# Everything that can carry a data-od-* attribute: Jinja templates, and the
# scripts that build markup at runtime.
SCAN_ROOTS = (
    PKG / 'templates',
    PKG / 'static' / 'js',
    PKG / 'setup' / 'default_theme',
)
SCAN_SUFFIXES = {'.html', '.js'}

NAME = r'[A-Za-z_$][\w$]*'


def _scanned_files():
    for root in SCAN_ROOTS:
        for path in sorted(root.rglob('*')):
            if path.suffix in SCAN_SUFFIXES and path != DOM_ACTIONS:
                yield path


def _used_names(attribute: str) -> dict[str, list[str]]:
    """Handler names spelled as ``data-od-x="name"`` or ``"data-od-x": "name"``."""
    attr_form = re.compile(rf'{attribute}\s*=\s*["\']({NAME})["\']')
    dict_form = re.compile(rf'["\']{attribute}["\']\s*:\s*["\']({NAME})["\']')
    used: dict[str, list[str]] = {}
    for path in _scanned_files():
        text = path.read_text(encoding='utf-8', errors='replace')
        for pattern in (attr_form, dict_form):
            for match in pattern.finditer(text):
                line = text[: match.start()].count('\n') + 1
                used.setdefault(match.group(1), []).append(f'{path.relative_to(PKG).as_posix()}:{line}')
    return used


def _allowlist(variable: str) -> set[str]:
    text = DOM_ACTIONS.read_text(encoding='utf-8')
    match = re.search(rf'var {variable} = allowlist\(\[(.*?)\]\);', text, re.S)
    assert match, f'{variable} allowlist not found in od_dom_actions.js'
    return set(re.findall(r"'([^']+)'", match.group(1)))


def test_click_allowlist_matches_the_handlers_in_use():
    used = _used_names('data-od-click')
    used.pop('reload', None)  # built in, not a global
    allowed = _allowlist('CLICK_ACTIONS')
    missing = {name: where for name, where in used.items() if name not in allowed}
    assert missing == {}, (
        'data-od-click handler not on the od_dom_actions.js CLICK_ACTIONS allowlist '
        '(it would silently do nothing):\n  '
        + '\n  '.join(f'{name}  ({", ".join(where)})' for name, where in sorted(missing.items()))
    )
    stale = sorted(allowed - set(used))
    assert stale == [], f'CLICK_ACTIONS lists handlers nothing uses: {stale}'


def test_change_allowlist_matches_the_handlers_in_use():
    used = _used_names('data-od-change')
    allowed = _allowlist('CHANGE_ACTIONS')
    missing = {name: where for name, where in used.items() if name not in allowed}
    assert missing == {}, (
        'data-od-change handler not on the od_dom_actions.js CHANGE_ACTIONS allowlist '
        '(it would silently do nothing):\n  '
        + '\n  '.join(f'{name}  ({", ".join(where)})' for name, where in sorted(missing.items()))
    )
    stale = sorted(allowed - set(used))
    assert stale == [], f'CHANGE_ACTIONS lists handlers nothing uses: {stale}'


def test_handler_names_are_never_computed():
    """A name built from a variable cannot be allowlisted, and is the injection."""
    dynamic = re.compile(r'data-od-(?:click|change)\s*=\s*["\'][^"\']*(?:\{\{|\{%|\$\{)')
    hits = []
    for path in _scanned_files():
        text = path.read_text(encoding='utf-8', errors='replace')
        for match in dynamic.finditer(text):
            line = text[: match.start()].count('\n') + 1
            hits.append(f'{path.relative_to(PKG).as_posix()}:{line}')
    assert hits == [], 'data-od-click / data-od-change name is computed:\n  ' + '\n  '.join(hits)


def test_dom_actions_does_not_call_arbitrary_globals():
    text = DOM_ACTIONS.read_text(encoding='utf-8')
    # The only window[...] lookup sits behind the allowlist check.
    lookups = re.findall(r'window\[[^\]]+\]', text)
    assert lookups == ['window[name]']
    body = text.split('function namedFn', 1)[1].split('}', 1)[0]
    assert 'allowed[name] !== true' in body
    # data-od-open never reaches window.open unparsed.
    assert "window.open(url, '_blank', 'noopener,noreferrer')" in text
    assert 'window.open(url);' not in text


def test_library_progress_text_escapes_game_and_message():
    """current_game is a game name taken from disk or metadata."""
    text = LIBS_JS.read_text(encoding='utf-8')
    lines = [line.strip() for line in text.splitlines() if 'progressText.innerHTML' in line]
    assert len(lines) == 2, lines
    for line in lines:
        assert 'escapeHtml(data.current_game)' in line, line
        assert 'escapeHtml(data.message' in line, line
