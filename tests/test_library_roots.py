"""Extra scan locations (ONEIRODEX_LIBRARY_ROOTS).

Covers the parser, the resolved picker list, the path allowlist that every
path-sensitive route funnels through, and the relative-path join that auto and
manual scan share.
"""

import os

import pytest

from oneirodex.utils.library_roots import (
    library_root_paths,
    library_roots,
    parse_library_roots,
    resolve_library_root,
    resolve_scan_path,
    root_availability,
)
from oneirodex.utils.security import get_allowed_base_directories
from oneirodex.utils.status import LIBRARY_ROOT_KEY_PREFIX, get_config_values

BASE_KEY = 'BASE_FOLDER_WINDOWS' if os.name == 'nt' else 'BASE_FOLDER_POSIX'


class _FakeApp:
    """Minimal stand-in — these helpers only ever read app.config."""

    def __init__(self, **config):
        self.config = config


def _app(roots_env=None, games='/games', base='/storage'):
    return _FakeApp(**{
        'DATA_FOLDER_GAMES': games,
        BASE_KEY: base,
        'LIBRARY_ROOTS': parse_library_roots(roots_env),
    })


def _norm(path):
    return os.path.normpath(path)


class TestParseLibraryRoots:
    def test_empty_input_is_no_roots(self):
        assert parse_library_roots(None) == []
        assert parse_library_roots('') == []
        assert parse_library_roots('   |  ') == []

    def test_labelled_and_unlabelled_entries(self):
        roots = parse_library_roots('NAS ROMs=/mnt/nas/roms|/mnt/archive')
        assert roots == [
            {'label': 'NAS ROMs', 'path': _norm('/mnt/nas/roms')},
            {'label': 'archive', 'path': _norm('/mnt/archive')},
        ]

    def test_windows_drive_letter_is_not_mistaken_for_a_label(self):
        drive = 'D:' + chr(92) + 'Games'
        assert parse_library_roots(drive) == [{'label': 'Games', 'path': _norm(drive)}]

    def test_label_with_no_path_is_dropped(self):
        assert parse_library_roots('Label=|/mnt/real') == [
            {'label': 'real', 'path': _norm('/mnt/real')},
        ]

    def test_repeated_paths_collapse(self):
        assert parse_library_roots('/mnt/a|/mnt/a') == [
            {'label': 'a', 'path': _norm('/mnt/a')},
        ]

    def test_entry_count_is_bounded(self):
        raw = '|'.join(f'/mnt/root{index}' for index in range(80))
        assert len(parse_library_roots(raw)) == 32


class TestLibraryRoots:
    def test_builtin_locations_come_first_and_dedupe(self):
        roots = library_roots(_app(games='/storage', base='/storage'))
        assert [root['path'] for root in roots] == [_norm('/storage')]

    def test_declared_roots_follow_the_builtins(self):
        roots = library_roots(_app('NAS=/mnt/nas/roms'))
        assert [root['label'] for root in roots] == ['Games', 'Server', 'NAS']
        assert [root['id'] for root in roots] == ['games', 'server', 'nas']

    def test_base_folder_stays_the_default_location(self):
        roots = library_roots(_app('NAS=/mnt/nas/roms'))
        default = [root for root in roots if root['default']]
        assert [root['label'] for root in default] == ['Server']

    def test_colliding_labels_get_distinct_ids(self):
        roots = library_roots(_app('Games=/mnt/one|Games=/mnt/two'))
        assert [root['id'] for root in roots if root['source'] == 'ONEIRODEX_LIBRARY_ROOTS'] == [
            'games-2', 'games-3',
        ]

    def test_resolve_by_id_and_the_unknown_case(self):
        app = _app('NAS=/mnt/nas/roms')
        assert resolve_library_root('nas', app)['path'] == _norm('/mnt/nas/roms')
        assert resolve_library_root('', app)['label'] == 'Server'
        assert resolve_library_root('gone', app) is None

    def test_availability_probe_reports_a_missing_mount(self, tmp_path):
        live = root_availability({'path': str(tmp_path)})
        assert (live['exists'], live['read']) == (True, True)

        dead = root_availability({'path': str(tmp_path / 'never-mounted')})
        assert (dead['exists'], dead['read'], dead['write']) == (False, False, False)


class TestAllowedBaseDirectories:
    def test_declared_roots_join_the_allowlist(self):
        app = _app('NAS=/mnt/nas/roms|Archive=/mnt/archive')
        bases = get_allowed_base_directories(app)
        assert _norm('/mnt/nas/roms') in bases
        assert _norm('/mnt/archive') in bases

    def test_builtin_bases_are_unchanged_without_the_env_var(self):
        app = _app(None)
        assert get_allowed_base_directories(app) == ['/games', '/storage']

    def test_allowlist_has_no_duplicates(self):
        app = _app('Same=/games')
        assert len(get_allowed_base_directories(app)) == 2

    def test_root_paths_only_covers_declared_roots(self):
        app = _app('NAS=/mnt/nas/roms')
        assert library_root_paths(app) == [_norm('/mnt/nas/roms')]


class TestResolveScanPath:
    def test_empty_path_means_the_root_itself(self):
        path, error = resolve_scan_path('', 'nas', _app('NAS=/mnt/nas/roms'))
        assert (path, error) == (_norm('/mnt/nas/roms'), None)

    def test_relative_path_joins_the_selected_root(self):
        path, error = resolve_scan_path('snes/', 'nas', _app('NAS=/mnt/nas/roms'))
        assert error is None
        assert path == os.path.join(_norm('/mnt/nas/roms'), 'snes/')

    def test_no_root_id_falls_back_to_the_base_folder(self):
        path, error = resolve_scan_path('snes', None, _app('NAS=/mnt/nas/roms'))
        assert error is None
        assert path == os.path.join(_norm('/storage'), 'snes')

    def test_absolute_path_survives_the_join(self):
        absolute = _norm('/mnt/other/games')
        path, error = resolve_scan_path(absolute, None, _app())
        assert (path, error) == (absolute, None)

    def test_unknown_root_is_an_error_not_a_silent_fallback(self):
        path, error = resolve_scan_path('snes', 'gone', _app('NAS=/mnt/nas/roms'))
        assert path is None
        assert 'no longer configured' in error

    def test_no_locations_at_all_reports_a_configuration_error(self):
        path, error = resolve_scan_path('snes', None, _FakeApp())
        assert path is None
        assert error


@pytest.mark.parametrize('raw', ['/mnt/games' + chr(0), '/' + 'x' * 5000])
def test_hostile_entries_are_dropped(raw):
    assert parse_library_roots(raw) == []


class TestOpsPathRows:
    """Ops path health must report every declared root, including duplicates."""

    def test_roots_with_the_same_label_both_appear(self):
        # `Archive=/mnt/a|Archive=/mnt/b` is a plausible typo, and keying the
        # health rows by label alone silently dropped one of them — from the
        # one view whose job is to report a root that stopped being mounted.
        values = get_config_values({'LIBRARY_ROOTS': [
            {'label': 'Archive', 'path': _norm('/mnt/a')},
            {'label': 'Archive', 'path': _norm('/mnt/b')},
        ]})
        rows = {k: v for k, v in values.items() if k.startswith(LIBRARY_ROOT_KEY_PREFIX)}
        assert len(rows) == 2
        assert {row['path'] for row in rows.values()} == {_norm('/mnt/a'), _norm('/mnt/b')}

    def test_a_single_root_keeps_a_clean_label(self):
        values = get_config_values({'LIBRARY_ROOTS': [
            {'label': 'Archive', 'path': _norm('/mnt/a')},
        ]})
        assert f'{LIBRARY_ROOT_KEY_PREFIX}Archive' in values
