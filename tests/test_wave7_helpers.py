"""Wave 7 unit tests — wanted queue, cheats helpers, play gates (no DB)."""

from types import SimpleNamespace

from oneirodex.platform import WEBRETR_INSTALLED_CORES, core_is_browser_playable
from oneirodex.utils import wanted_updates as wu
from oneirodex.utils.play_url import WEBRETRO_PLATFORMS, browse_play_fields


def test_webretro_platforms_include_sega_cd_and_pcdos_gated():
    assert 'SEGA_CD' in WEBRETRO_PLATFORMS
    assert 'PCDOS' in WEBRETRO_PLATFORMS  # gated by ENABLE_PCDOS_BROWSER + WASM
    assert core_is_browser_playable('nestopia')
    assert not core_is_browser_playable('dosbox_pure')
    assert 'parallel_n64' in WEBRETR_INSTALLED_CORES


def test_browse_play_fields_requires_bundled_core(monkeypatch):
    game = SimpleNamespace(uuid='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', library=None)

    def fake_resolve(_platform):
        return {'emulators': ['nestopia'], 'preferred': 'nestopia'}

    monkeypatch.setattr(
        'oneirodex.utils.emulator_profiles.resolve_emulators_for_platform',
        fake_resolve,
    )
    # No platform → not playable
    assert browse_play_fields(game)['can_play_in_browser'] is False


def test_browse_play_url_includes_platform(monkeypatch):
    library = SimpleNamespace(platform=SimpleNamespace(name='NES'))
    game = SimpleNamespace(uuid='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', library=library)

    monkeypatch.setattr(
        'oneirodex.utils.emulator_profiles.resolve_emulators_for_platform',
        lambda _p: {'emulators': ['nestopia'], 'preferred': 'nestopia'},
    )
    fields = browse_play_fields(game)
    assert fields['can_play_in_browser'] is True
    assert 'platform=NES' in fields['play_url']
    assert fields['library_platform'] == 'NES'
    assert fields['play_mode'] == 'browser'


def test_wanted_queue_add_and_fulfill(tmp_path, monkeypatch):
    monkeypatch.setattr(wu, '_library_root', lambda: str(tmp_path))
    item = wu.add_wanted(1, game_uuid='game-1', kind='update', label='Patch')
    assert item['status'] == 'wanted'
    assert len(wu.list_wanted(1)) == 1
    assert wu.mark_fulfilled(1, 'game-1', kind='update') == 1
    assert wu.list_wanted(1)[0]['status'] == 'available'


def test_wanted_queue_uses_explicit_app_upload_root(tmp_path):
    app = SimpleNamespace(config={'UPLOAD_FOLDER': str(tmp_path)})
    item = wu.add_wanted(2, game_uuid='game-2', app=app)

    assert wu.list_wanted(2, app=app) == [item]
    assert (tmp_path / 'wanted_updates' / 'user_2.json').is_file()
