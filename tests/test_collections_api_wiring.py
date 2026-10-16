"""DB-free wiring guards for collections delete/remove/counts/picker."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
API = ROOT / 'oneirodex' / 'routes_apis' / 'collections.py'
SPA_API = ROOT / 'frontend' / 'member-app' / 'src' / 'api' / 'collections.ts'
DETAIL = ROOT / 'frontend' / 'member-app' / 'src' / 'pages' / 'CollectionDetailPage.tsx'
LIST = ROOT / 'frontend' / 'member-app' / 'src' / 'pages' / 'CollectionsPage.tsx'


def test_collections_api_exposes_delete_and_counts():
    src = API.read_text(encoding='utf-8')
    assert "methods=['DELETE']" in src
    assert "methods=['PATCH']" in src
    assert 'def delete_collection' in src
    assert 'def update_collection' in src
    assert 'def remove_collection_item' in src
    assert 'def reorder_collection_items' in src
    assert "methods=['PUT']" in src
    assert '/items/order' in src
    assert 'item_count' in src
    assert 'can_edit' in src
    assert 'user_can_access_game' in src
    assert 'System collections cannot be deleted' in src
    assert 'System collections cannot be edited' in src
    assert '_filtered_collection_payload' in src


def test_spa_collections_client_covers_new_actions():
    src = SPA_API.read_text(encoding='utf-8')
    assert 'export async function deleteCollection' in src
    assert 'export async function updateCollection' in src
    assert 'export async function reorderCollectionItems' in src
    assert 'export async function removeCollectionItem' in src
    assert 'export async function searchGames' in src
    assert '/api/search' in src
    assert '/items/order' in src


def test_spa_detail_uses_search_picker_not_raw_uuid_paste():
    detail = DETAIL.read_text(encoding='utf-8')
    assert 'searchGames' in detail
    assert 'Search games' in detail
    assert 'Paste a game ID' not in detail
    assert 'removeCollectionItem' in detail
    assert 'deleteCollection' in detail
    assert 'updateCollection' in detail
    assert 'reorderCollectionItems' in detail
    assert 'Save changes' in detail


def test_spa_list_shows_item_counts_and_delete():
    listing = LIST.read_text(encoding='utf-8')
    assert 'item_count' in listing
    assert 'deleteCollection' in listing
    assert 'can_edit' in listing


def test_newsletter_ckeditor_targets_content_field():
    page = (ROOT / 'frontend' / 'admin-app' / 'src' / 'pages' / 'NewsletterPage.tsx').read_text(
        encoding='utf-8',
    )
    assert 'Message' in page and '<textarea' in page


def test_statistics_scripts_use_theme_asset():
    page = (ROOT / 'frontend' / 'admin-app' / 'src' / 'pages' / 'StatisticsPage.tsx').read_text(
        encoding='utf-8',
    )
    assert "getJson('/api/admin/statistics')" in page
    assert 'js/admin-statistics.js' not in page


def test_statistics_charts_sit_in_a_bounded_grid():
    """W27-D3: Bootstrap columns + unbounded Chart.js grew a dual-axis scroll."""
    css = (ROOT / 'frontend' / 'admin-app' / 'src' / 'pages' / 'StatisticsPage.css').read_text(
        encoding='utf-8',
    )
    assert 'repeat(auto-fit, minmax(min(100%, 26rem), 1fr))' in css
    chart_rule = re.search(r'\.od-stats-chart\s*\{([^}]*)\}', css)
    assert chart_rule and re.search(r'\bmin-width\s*:\s*0\s*;', chart_rule.group(1))


def test_orphaned_manage_downloads_css_is_gone():
    path = (
        ROOT / 'oneirodex' / 'setup' / 'default_theme' / 'css' / 'admin'
        / 'admin_manage_downloads.css'
    )
    assert not path.exists()


def test_init_manager_has_no_emoji_and_uses_safe_print():
    src = (ROOT / 'oneirodex' / 'init_manager.py').read_text(encoding='utf-8')
    assert 'def _safe_print' in src
    assert '_safe_print(' in src
    for glyph in ('🚀', '✅', '❌', '⚠️'):
        assert glyph not in src
