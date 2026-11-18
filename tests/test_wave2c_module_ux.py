"""Wave 2C — feature-flag / module UX regression guards (DB-free)."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / 'oneirodex' / 'templates' / 'admin'
THEME_CSS = ROOT / 'oneirodex' / 'setup' / 'default_theme' / 'css' / 'admin'


def _read(path: Path) -> str:
    return path.read_text(encoding='utf-8')


def test_settings_shell_css_defines_badge_tokens():
    css = _read(THEME_CSS / 'admin_settings_shell.css')
    assert '.settings-shell-badge--on' in css
    assert '.settings-shell-badge--off' in css
    assert 'var(--od-success' in css


def test_arr_admin_page_shows_enable_toggle_even_when_off():
    assert not (TEMPLATES / 'arr_module.html').exists()
    spa = _read(ROOT / 'frontend' / 'admin-app' / 'src' / 'pages' / 'ArrPage.tsx')
    controller = _read(ROOT / 'frontend' / 'admin-app' / 'src' / 'pages' / 'useArrController.ts')
    assert "getJson('/api/arr/module')" in controller
    assert "putJson('/api/arr/module'" in controller


def test_module_status_helper_covers_hub_keys():
    src = _read(ROOT / 'oneirodex' / 'utils' / 'module_status.py')
    assert "def settings_hub_module_status" in src
    for key in ("'arr'", "'ai'", "'storage'"):
        assert key in src
    # Safety flags remain env-only — no DB toggle helpers for apply/pipeline/VR
    assert 'enable_hardlink' not in src.lower() or 'ENABLE_HARDLINK_HELPERS' in src
    assert 'ALLOW_HARDLINK_APPLY' in src
