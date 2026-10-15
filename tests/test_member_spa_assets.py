"""SPA shell must load the Vite CSS bundle (Phase 0 chrome rewrite)."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_member_spa_links_member_app_assets_without_jinja():
    shell = (ROOT / 'oneirodex' / 'utils' / 'member_spa.py').read_text(encoding='utf-8')
    assert 'dist_asset_url("member-app/member-app.css")' in shell
    assert "dist_asset_url('member-app/member-app.js')" in shell
    assert 'render_template' not in shell


def test_entrypoint_warns_on_missing_member_app_css():
    sh = (ROOT / 'entrypoint.sh').read_text(encoding='utf-8')
    assert 'member-app.css' in sh
    assert 'od-tokens.css' in sh


def test_default_accent_is_green():
    tokens = (
        ROOT / 'oneirodex' / 'setup' / 'default_theme' / 'css' / 'od-tokens.css'
    ).read_text(encoding='utf-8')
    assert '--od-accent: #2fd67b;' in tokens
    assert '--od-glass-bg:' in tokens
    assert '--od-platform-accent:' in tokens
    assert '--od-tile-gap:' in tokens


def test_member_spa_shell_keeps_shared_delete_actions():
    shell = (ROOT / 'oneirodex' / 'utils' / 'member_spa.py').read_text(encoding='utf-8')
    assert 'popup_menu.js' in shell
    assert 'delete_game_modal.js' in shell
    assert 'delete_full_game' in shell
