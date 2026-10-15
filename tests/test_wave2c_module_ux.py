"""Wave 2C — feature-flag / module UX regression guards (DB-free)."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / 'oneirodex' / 'templates' / 'admin'
THEME_CSS = ROOT / 'oneirodex' / 'setup' / 'default_theme' / 'css' / 'admin'


def _read(path: Path) -> str:
    return path.read_text(encoding='utf-8')


def test_settings_shell_renders_module_status_badges():
    """Wave 7 moved the hub body to React; the badges live there now.

    They went missing in that move — the Jinja block was emptied and nothing
    rendered `module_status`. Asserting on
    the SPA source is what keeps the badges from silently disappearing again,
    the same way test_storage_page_surfaces_env_gates does for Storage.
    """
    shell = _read(ROOT / 'oneirodex' / 'utils' / 'admin_spa.py')
    assert 'render_admin_spa' in shell

    spa = _read(ROOT / 'frontend' / 'admin-app' / 'src' / 'pages' / 'SettingsPage.tsx')
    assert '/api/settings/module-status' in spa
    assert 'settings-shell-badge' in spa
    assert 'settings-shell-badge--' in spa

    nav = _read(ROOT / 'frontend' / 'admin-app' / 'src' / 'components' / 'navConfig.ts')
    for key in ("statusKey: 'arr'", "statusKey: 'ai'", "statusKey: 'storage'"):
        assert key in nav

    api = _read(ROOT / 'oneirodex' / 'routes_apis' / 'settings.py')
    assert 'settings_hub_module_status' in api


def test_settings_shell_css_defines_badge_tokens():
    css = _read(THEME_CSS / 'admin_settings_shell.css')
    assert '.settings-shell-badge--on' in css
    assert '.settings-shell-badge--off' in css
    assert 'var(--od-success' in css


def test_settings_shell_uses_module_status_api():
    src = _read(ROOT / 'oneirodex' / 'routes_admin_ext' / 'settings.py')
    api = _read(ROOT / 'oneirodex' / 'routes_apis' / 'settings.py')
    assert 'settings_hub_module_status' in api
    assert "render_admin_spa(title='All settings · Oneirodex Admin')" in src


def test_arr_module_toggle_endpoint_exists():
    src = _read(ROOT / 'oneirodex' / 'routes_arr.py')
    assert "/api/arr/module" in src
    assert 'def arr_module_flag' in src
    assert 'ensure_global_settings' in src


def test_arr_admin_page_shows_enable_toggle_even_when_off():
    assert not (TEMPLATES / 'arr_module.html').exists()
    spa = _read(ROOT / 'frontend' / 'admin-app' / 'src' / 'pages' / 'ArrPage.tsx')
    assert "getJson('/api/arr/module')" in spa
    assert "putJson('/api/arr/module'" in spa


def test_ai_config_endpoint_and_save_ui():
    api = _read(ROOT / 'oneirodex' / 'routes_apis' / 'ai_assist.py')
    assert "/ai/config" in api
    assert 'save_ai_config' in api
    util = _read(ROOT / 'oneirodex' / 'utils' / 'ai_assist.py')
    assert 'def get_ai_config' in util
    assert 'def save_ai_config' in util
    assert not (TEMPLATES / 'ai_assist.html').exists()
    spa = _read(ROOT / 'frontend' / 'admin-app' / 'src' / 'pages' / 'AiAssistPage.tsx')
    assert "getJson('/api/ai/config')" in spa
    assert "putJson('/api/ai/config'" in spa
    route = _read(ROOT / 'oneirodex' / 'routes_admin_ext' / 'settings.py')
    assert "render_admin_spa(title='AI assist - Oneirodex Admin')" in route


def test_storage_page_surfaces_env_gates():
    # Env gates live in React + GET /api/storage/status; the wrapper is retired.
    assert not (TEMPLATES / 'storage.html').exists()
    spa = _read(ROOT / 'frontend' / 'admin-app' / 'src' / 'pages' / 'StoragePage.tsx')
    assert '/api/storage/status' in spa
    assert '/api/storage/hardlink/preview' in spa
    assert 'allow_apply' in spa
    src = _read(ROOT / 'oneirodex' / 'routes_admin_ext' / 'settings.py')
    assert "render_admin_spa(title='Storage / hardlinks · Oneirodex Admin')" in src


def test_module_status_helper_covers_hub_keys():
    src = _read(ROOT / 'oneirodex' / 'utils' / 'module_status.py')
    assert "def settings_hub_module_status" in src
    for key in ("'arr'", "'ai'", "'storage'"):
        assert key in src
    # Safety flags remain env-only — no DB toggle helpers for apply/pipeline/VR
    assert 'enable_hardlink' not in src.lower() or 'ENABLE_HARDLINK_HELPERS' in src
    assert 'ALLOW_HARDLINK_APPLY' in src
