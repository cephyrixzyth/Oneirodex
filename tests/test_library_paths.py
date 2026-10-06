"""Runtime files can move out of the install folder (DESK-04 / ADR 0011).

``ONEIRODEX_LIBRARY_DIR`` sends everything the server writes to a data folder;
URLs stay ``/static/library/…``. No database needed.
"""
import re

import pytest
from flask import Flask

from oneirodex.utils import library_paths
from oneirodex.utils.library_paths import LIBRARY_DIR_ENV, PACKAGE_ROOT, image_save_dir, library_dir, static_write_dir
from oneirodex.utils.static_files import resolve_served_static, serve_relocated_static


@pytest.fixture
def moved(tmp_path, monkeypatch):
    lib = tmp_path / 'data' / 'library'
    monkeypatch.setenv(LIBRARY_DIR_ENV, str(lib))
    return lib


@pytest.fixture
def unmoved(monkeypatch):
    monkeypatch.delenv(LIBRARY_DIR_ENV, raising=False)


def test_default_is_the_package_library(tmp_path, unmoved):
    assert library_dir(tmp_path) == str(tmp_path / 'static' / 'library')
    assert library_dir() == str(PACKAGE_ROOT / 'static' / 'library')
    assert static_write_dir('newstyle', package_root=tmp_path) == tmp_path / 'static' / 'newstyle'


def test_image_save_path_is_nested_in_the_configured_library_volume(tmp_path):
    configured_library = tmp_path / 'mounted-library'

    assert image_save_dir(configured_library) == str(configured_library / 'images')


def test_the_env_moves_everything_even_when_a_package_root_is_named(tmp_path, moved):
    assert library_dir(tmp_path) == str(moved)
    assert library_dir() == str(moved)
    assert static_write_dir('newstyle', package_root=tmp_path) == moved / 'static-overrides' / 'newstyle'


def test_blank_env_counts_as_unset(tmp_path, monkeypatch):
    monkeypatch.setenv(LIBRARY_DIR_ENV, '  ')
    assert library_paths.relocated_library_dir() is None
    assert library_dir(tmp_path) == str(tmp_path / 'static' / 'library')


def _shipped(tmp_path):
    static = tmp_path / 'install' / 'static'
    (static / 'newstyle').mkdir(parents=True)
    (static / 'newstyle' / 'default_cover.jpg').write_text('shipped')
    (static / 'library' / 'themes').mkdir(parents=True)
    (static / 'library' / 'themes' / 'stale.css').write_text('install copy')
    return static


def test_served_files_follow_the_moved_library(tmp_path, moved):
    static = _shipped(tmp_path)
    (moved / 'themes').mkdir(parents=True)
    (moved / 'themes' / 'a.css').write_text('a{}')

    assert resolve_served_static(static, '/static/library/themes/a.css') == (moved / 'themes' / 'a.css').resolve()
    # The install copy of library/ is never served once it has moved.
    assert not resolve_served_static(static, '/static/library/themes/stale.css').is_file()
    for bad in ('/static/library/../newstyle/default_cover.jpg', '/static/library/themes/../../x'):
        assert resolve_served_static(static, bad) is None
    # Other spellings of the same folder must not reach the install copy either.
    for spelling in ('/static//library/themes/stale.css', '/static/./library/themes/stale.css',
                     '/static/LIBRARY/themes/stale.css'):
        served = resolve_served_static(static, spelling)
        assert served is None or str(served).startswith(str(moved.resolve())), spelling


def test_an_override_wins_over_the_shipped_file_and_only_when_present(tmp_path, moved):
    static = _shipped(tmp_path)
    shipped = (static / 'newstyle' / 'default_cover.jpg').resolve()
    assert resolve_served_static(static, '/static/newstyle/default_cover.jpg') == shipped

    override = moved / 'static-overrides' / 'newstyle' / 'default_cover.jpg'
    override.parent.mkdir(parents=True)
    override.write_text('baked')
    assert resolve_served_static(static, '/static/newstyle/default_cover.jpg') == override.resolve()
    assert resolve_served_static(static, '/static/newstyle/../../etc/passwd') is None


def test_nothing_changes_without_the_env(tmp_path, unmoved):
    static = _shipped(tmp_path)
    assert resolve_served_static(static, '/static/library/themes/stale.css') == (
        static / 'library' / 'themes' / 'stale.css').resolve()


def test_flask_static_view_serves_the_moved_library(tmp_path, moved):
    static = _shipped(tmp_path)
    (moved / 'images').mkdir(parents=True)
    (moved / 'images' / 'cover.jpg').write_bytes(b'jpg')
    app = Flask(__name__, static_folder=str(static))
    serve_relocated_static(app)
    client = app.test_client()

    def get(url):
        response = client.get(url)
        try:
            return response.status_code, response.data
        finally:
            response.close()

    assert get('/static/library/images/cover.jpg') == (200, b'jpg')
    assert get('/static/newstyle/default_cover.jpg') == (200, b'shipped')
    assert get('/static/library/themes/stale.css')[0] == 404
    assert get('/static/library/../newstyle/default_cover.jpg')[0] == 404


def test_writers_resolve_into_the_moved_library(tmp_path, moved):
    from oneirodex.utils import anticheat_compat, save_paths
    from oneirodex.utils.cover_art_studio import generated_root, newstyle_root, stock_root
    from oneirodex.utils.icon_themes import icon_themes_root
    from oneirodex.utils.system_marks import marks_root
    from oneirodex.utils.theme_freshness import theme_freshness

    assert icon_themes_root(tmp_path) == moved / 'icon-themes'
    assert generated_root(tmp_path) == moved / 'generated'
    assert stock_root(tmp_path) == moved / 'stock'
    assert newstyle_root(tmp_path) == moved / 'static-overrides' / 'newstyle'
    assert marks_root(tmp_path) == moved / 'system-marks'
    assert save_paths.cache_dir() == str(moved / 'save_paths')
    assert anticheat_compat.cache_path() == str(moved / 'anticheat' / 'games.json')

    source = tmp_path / 'setup' / 'default_theme'
    source.mkdir(parents=True)
    (source / 'theme.json').write_text('{}')
    (moved / 'themes' / 'default').mkdir(parents=True)
    (moved / 'themes' / 'default' / 'theme.json').write_text('{}')
    assert theme_freshness(tmp_path)['stale'] is False, 'the deployed theme is read from the moved library'


def test_webretro_cores_are_found_in_the_shipped_or_fetched_folder(tmp_path, moved, monkeypatch):
    from oneirodex.utils import webretro_core_install, webretro_cores

    shipped = tmp_path / 'install'
    monkeypatch.setattr(webretro_cores, '_PACKAGE_ROOT', shipped)
    fetched = webretro_cores.default_cores_dir()
    assert fetched == moved / 'static-overrides' / 'vendor' / 'webretro' / 'cores'
    assert webretro_cores.core_dirs() == [fetched, webretro_cores.shipped_cores_dir()]

    monkeypatch.setattr(webretro_core_install, 'default_core_ids', lambda: frozenset({'a', 'b'}))
    size = webretro_core_install.MIN_CORE_BYTES
    for folder, core in ((webretro_cores.shipped_cores_dir(), 'a'), (fetched, 'b')):
        folder.mkdir(parents=True, exist_ok=True)
        for suffix in webretro_core_install.CORE_SUFFIXES:
            (folder / f'{core}{suffix}').write_bytes(b'x' * size)
    assert webretro_core_install.missing_cores() == frozenset()
    assert webretro_cores.discover_webretro_cores() == frozenset({'a', 'b'})
    assert webretro_cores.wasm_present_on_disk('a') and webretro_cores.wasm_present_on_disk('b')


# Ratchet: a new writer that builds <package>/static/library by hand would put
# a standalone install's files back inside its read-only install folder. Matched
# across line breaks: asgi.py once spelled it over four lines.
_HAND_BUILT = [
    re.compile(r"""['"]static['"]\s*(?:,|/)\s*['"]library['"]"""),
    re.compile(r"""join\([^)]*['"]static/library"""),
]


def test_no_module_builds_the_library_path_by_hand():
    root = PACKAGE_ROOT
    sources = [p for p in root.rglob('*.py') if '__pycache__' not in p.parts and p.name != 'library_paths.py']
    offenders = []
    for path in sources + [root.parent / 'asgi.py']:
        text = path.read_text(encoding='utf-8')
        for pattern in _HAND_BUILT:
            for match in pattern.finditer(text):
                offenders.append(f'{path.relative_to(root.parent)}:{text.count(chr(10), 0, match.start()) + 1}')
    assert not offenders, 'use oneirodex.utils.library_paths.library_dir(): ' + ', '.join(offenders)


def test_shipped_library_art_is_copied_into_a_moved_library_without_overwriting(tmp_path, moved, monkeypatch):
    install = tmp_path / 'install'
    shipped = install / 'static' / 'library'
    for rel in ('system-marks/aurora/nes.webp', 'stock/pack/manifest.json', 'images/dev-only.jpg'):
        (shipped / rel).parent.mkdir(parents=True, exist_ok=True)
        (shipped / rel).write_text('shipped ' + rel)
    (moved / 'system-marks' / 'aurora').mkdir(parents=True)
    (moved / 'system-marks' / 'aurora' / 'nes.webp').write_text('regenerated by the admin')
    monkeypatch.setattr(library_paths, 'PACKAGE_ROOT', install)

    assert library_paths.seed_shipped_library() == 1
    assert (moved / 'stock' / 'pack' / 'manifest.json').read_text() == 'shipped stock/pack/manifest.json'
    assert (moved / 'system-marks' / 'aurora' / 'nes.webp').read_text() == 'regenerated by the admin'
    assert not (moved / 'images' / 'dev-only.jpg').exists(), "a checkout's own runtime files stay behind"
    assert library_paths.seed_shipped_library() == 0


def test_nothing_is_seeded_when_the_library_has_not_moved(unmoved):
    assert library_paths.seed_shipped_library() == 0
