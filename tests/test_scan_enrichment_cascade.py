"""The scan path must use every source, not just Steam.

The cascade existed before this and was wired into *manual* identify only. A
scanned title went through ``enrich_game_with_steam`` and stopped there, which
is fine for a PC library and useless for every console one: Steam does not
carry a SNES ROM, so those rows landed blank and stayed blank.

These tests pin the wiring rather than the walk — ``test_metadata_cascade.py``
covers the walk itself. Nothing here touches the network or the database.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from oneirodex.utils import game_core
from oneirodex.utils.services import game_enrich

pytestmark = pytest.mark.integration  # A3.1: kept out of the fast `-m "not integration"` core -- scan metadata enrichment cascade.


class FakeLibrary:
    def __init__(self, platform):
        self.platform = platform


class FakePlatform:
    """Mimics the LibraryPlatform enum's ``.name`` access."""

    def __init__(self, name):
        self.name = name


class FakeGame:
    def __init__(self, *, platform='PCWIN', summary='', genres=None, developer_id=None):
        self.name = 'Chrono Trigger'
        self.summary = summary
        self.genres = list(genres or [])
        self.developer_id = developer_id
        self.player_perspectives = []
        self.library = FakeLibrary(FakePlatform(platform)) if platform else None


@pytest.fixture
def no_db(monkeypatch):
    """begin_nested() needs a session; the cascade itself is mocked out."""
    import contextlib

    class FakeSession:
        def begin_nested(self):
            return contextlib.nullcontext()

    monkeypatch.setattr(game_core.db, 'session', FakeSession())


class TestConsolePlatformsSkipSteam:
    def test_a_console_rom_never_calls_steam(self, no_db):
        """Four platform families' worth of scans used to spend a round trip
        each asking a PC store about a cartridge."""
        with patch.object(game_enrich, 'enrich_game_with_steam') as steam, \
             patch('oneirodex.utils.metadata_cascade.hydrate_game_from_cascade') as cascade:
            cascade.return_value = {'applied': {}, 'trace': {'queried': ['thegamesdb']}}
            game_core.enrich_game_all_sources(FakeGame(platform='SNES'))

        steam.assert_not_called()
        cascade.assert_called_once()
        assert cascade.call_args.kwargs['library_platform'] == 'SNES'

    def test_a_pc_game_still_gets_the_steam_pass(self, no_db):
        """That pass fetches more than the cascade does — VR perspectives and
        game modes — so it is not redundant with it."""
        with patch.object(game_enrich, 'enrich_game_with_steam') as steam, \
             patch('oneirodex.utils.metadata_cascade.hydrate_game_from_cascade') as cascade:
            cascade.return_value = {'applied': {}, 'trace': {}}
            game_core.enrich_game_all_sources(FakeGame(platform='PCWIN'))

        steam.assert_called_once()

    def test_an_unknown_platform_still_asks_steam(self, no_db):
        """Absent platform is not evidence the title is a console one."""
        with patch.object(game_enrich, 'enrich_game_with_steam') as steam, \
             patch('oneirodex.utils.metadata_cascade.hydrate_game_from_cascade') as cascade:
            cascade.return_value = {'applied': {}, 'trace': {}}
            game_core.enrich_game_all_sources(FakeGame(platform=None))

        steam.assert_called_once()


class TestCascadeRunsOnlyWhenNeeded:
    def test_a_complete_game_does_not_trigger_a_single_request(self, no_db):
        complete = FakeGame(summary='A blurb.', genres=['RPG'], developer_id=4)
        with patch.object(game_enrich, 'enrich_game_with_steam') as steam, \
             patch('oneirodex.utils.metadata_cascade.hydrate_game_from_cascade') as cascade:
            steam.return_value = {'applied': True}
            result = game_core.enrich_game_all_sources(complete)

        cascade.assert_not_called()
        assert result['cascade'] is None

    @pytest.mark.parametrize('thin', [
        {'summary': '', 'genres': ['RPG'], 'developer_id': 4},
        {'summary': 'Blurb', 'genres': [], 'developer_id': 4},
        {'summary': 'Blurb', 'genres': ['RPG'], 'developer_id': None},
    ])
    def test_any_missing_core_field_triggers_the_walk(self, thin, no_db):
        with patch.object(game_enrich, 'enrich_game_with_steam'), \
             patch('oneirodex.utils.metadata_cascade.hydrate_game_from_cascade') as cascade:
            cascade.return_value = {'applied': {}, 'trace': {'queried': ['gog']}}
            game_core.enrich_game_all_sources(FakeGame(**thin))

        cascade.assert_called_once()

    def test_whitespace_only_summary_counts_as_missing(self, no_db):
        with patch.object(game_enrich, 'enrich_game_with_steam'), \
             patch('oneirodex.utils.metadata_cascade.hydrate_game_from_cascade') as cascade:
            cascade.return_value = {'applied': {}, 'trace': {}}
            game_core.enrich_game_all_sources(
                FakeGame(summary='   ', genres=['RPG'], developer_id=4)
            )

        cascade.assert_called_once()


class TestSteamIsNotAskedTwice:
    def test_the_cascade_is_told_to_skip_steam(self, no_db):
        """The Steam pass above already answered; a second call is a wasted
        round trip on every PC title in a scan."""
        with patch.object(game_enrich, 'enrich_game_with_steam'), \
             patch('oneirodex.utils.metadata_cascade.hydrate_game_from_cascade') as cascade:
            cascade.return_value = {'applied': {}, 'trace': {}}
            game_core.enrich_game_all_sources(FakeGame(platform='PCWIN'))

        assert cascade.call_args.kwargs['skip'] == ('steam',)


class TestAMetadataMissNeverBreaksTheImport:
    def test_a_failing_cascade_is_swallowed(self, no_db, caplog):
        with caplog.at_level('INFO', logger='oneirodex.utils.services.game_enrich'):
            with patch.object(game_enrich, 'enrich_game_with_steam') as steam, \
                 patch('oneirodex.utils.metadata_cascade.hydrate_game_from_cascade') as cascade:
                steam.return_value = {'applied': True}
                cascade.side_effect = RuntimeError('mobygames exploded')
                result = game_core.enrich_game_all_sources(FakeGame())

        assert result['cascade'] is None
        assert any('mobygames exploded' in record.message for record in caplog.records)

    def test_the_steam_result_is_still_returned_intact(self, no_db):
        """Callers read is_vr and steam_app_id off this dict; adding a cascade
        must not change its shape."""
        with patch.object(game_enrich, 'enrich_game_with_steam') as steam, \
             patch('oneirodex.utils.metadata_cascade.hydrate_game_from_cascade') as cascade:
            steam.return_value = {'applied': True, 'is_vr': True, 'steam_app_id': 42}
            cascade.return_value = {'applied': {}, 'trace': {'contributed': ['gog']}}
            result = game_core.enrich_game_all_sources(FakeGame())

        assert result['is_vr'] is True
        assert result['steam_app_id'] == 42
        assert result['cascade'] == {'contributed': ['gog']}


def test_every_scan_call_site_uses_the_full_cascade():
    """The three create/identify paths are the whole point of this change; a
    future edit that reinstates the Steam-only call would be silent otherwise."""
    import inspect

    from oneirodex.utils.services import scan_identify

    # The implementation moved out of game_core during the A2.3 split.
    identify_source = inspect.getsource(scan_identify)
    enrichment_source = inspect.getsource(game_enrich)
    assert identify_source.count('enrich_game_all_sources(') == 2
    assert 'enrich_game_all_sources(game, lookup_name=game.name)' in enrichment_source
    # Only the full-cascade wrapper should call the Steam-only helper.
    wrapper = inspect.getsource(game_enrich.enrich_game_all_sources)
    assert 'enrich_game_with_steam(' in wrapper
