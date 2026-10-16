"""Ratchet retired Jinja templates and unsafe inline handlers in shipped JS."""

from __future__ import annotations

import ast
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / 'oneirodex'
TEMPLATE_ROOT = Path(__file__).resolve().parents[1] / 'oneirodex' / 'templates'
STATIC_JS = Path(__file__).resolve().parents[1] / 'oneirodex' / 'static' / 'js'
THEME_JS = (
    Path(__file__).resolve().parents[1]
    / 'oneirodex' / 'setup' / 'default_theme' / 'js'
)
JINJA_RE = ('{{', '{%')
INLINE_HANDLER_IN_JS_RE = ('onclick=', 'onchange=', 'onsubmit=')


def test_jinja_template_tree_is_retired():
    files = sorted(path.relative_to(TEMPLATE_ROOT).as_posix()
                   for path in TEMPLATE_ROOT.rglob('*') if path.is_file())
    assert files == [], 'Retired Jinja template tree has files: ' + ', '.join(files)


def test_application_python_has_no_jinja_imports_or_render_calls():
    render_names = {'render_template', 'render_template_string', 'stream_template'}
    hits = []
    for path in sorted(PKG.rglob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(alias.name == 'jinja2' or alias.name.startswith('jinja2.') for alias in node.names):
                    hits.append(f'{path.relative_to(PKG)}:{node.lineno} import')
            elif isinstance(node, ast.ImportFrom):
                if node.module == 'jinja2' or (node.module or '').startswith('jinja2.'):
                    hits.append(f'{path.relative_to(PKG)}:{node.lineno} import')
            elif isinstance(node, ast.Call):
                function = node.func
                if isinstance(function, ast.Name) and function.id in render_names:
                    hits.append(f'{path.relative_to(PKG)}:{node.lineno} render')
                elif isinstance(function, ast.Attribute) and function.attr in render_names:
                    hits.append(f'{path.relative_to(PKG)}:{node.lineno} render')
    assert hits == [], 'Jinja imports/render calls remain: ' + ', '.join(hits)


def test_extracted_static_js_has_no_jinja():
    """A mechanical extract that left `{% if %}` in a .js file is a SyntaxError."""
    hits = []
    for path in sorted(STATIC_JS.glob('od_*.js')):
        text = path.read_text(encoding='utf-8')
        if any(token in text for token in JINJA_RE):
            hits.append(path.name)
    assert hits == [], 'Jinja leftover in static JS: ' + ', '.join(hits)


def test_shipped_js_does_not_inject_inline_handlers():
    """innerHTML + onclick= recreates the handler CSP just dropped."""
    hits = []
    paths = list(STATIC_JS.glob('od_*.js'))
    if THEME_JS.is_dir():
        paths.extend(THEME_JS.glob('*.js'))
    for path in sorted(paths):
        if path.name == 'od_dom_actions.js':
            continue
        text = path.read_text(encoding='utf-8')
        if any(token in text.lower() for token in INLINE_HANDLER_IN_JS_RE):
            hits.append(path.name)
    assert hits == [], (
        'JS still injects onclick=/onchange=/onsubmit= — switch to data-od-*:\n  '
        + '\n  '.join(hits)
    )
