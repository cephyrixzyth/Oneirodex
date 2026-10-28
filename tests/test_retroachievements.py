"""RetroAchievements (R1/R2): hash rules, hash index, matching, honesty flags.

The provider is never hit: ``_api_get`` is patched to return canned rows. What
is tested is everything on our side of the wire — the system-specific hash
(the reason file_md5 could not be reused), the index refresh/TTL, the match
persisted on the game, ``supports_achievements`` staying false for a matched
set with no achievements, and the routes' opt-in behaviour when unconfigured.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from oneirodex.models import Game, Library, RetroAchievementsIndexEntry, User
from oneirodex.platform import LibraryPlatform
from oneirodex.utils import retroachievements as ra


# --- hash rules ----------------------------------------------------------------


def test_nes_hash_skips_the_ines_header_and_sizes_by_it():
    prg = bytes(range(256)) * 64  # 16 KiB
    chr_ = b'\x7f' * 8192
    header = b'NES\x1a' + bytes([1, 1, 0, 0]) + b'\x00' * 8
    padding = b'\xff' * 100  # trailing junk some dumps carry
    assert ra.ra_hash_bytes(header + prg + chr_ + padding, 'NES') == hashlib.md5(prg + chr_).hexdigest()
    # Headerless dumps hash as-is.
    assert ra.ra_hash_bytes(prg, 'NES') == hashlib.md5(prg).hexdigest()


def test_snes_hash_strips_a_copier_header():
    rom = b'\x11' * (32 * 1024)
    assert ra.ra_hash_bytes(b'\x00' * 512 + rom, 'SNES') == hashlib.md5(rom).hexdigest()
    assert ra.ra_hash_bytes(rom, 'SNES') == hashlib.md5(rom).hexdigest()


def test_lynx_pce_and_7800_headers():
    body = b'\x42' * 4096
    assert ra.ra_hash_bytes(b'LYNX' + b'\x00' * 60 + body, 'LYNX') == hashlib.md5(body).hexdigest()
    pce = b'\x33' * (128 * 1024)
    assert ra.ra_hash_bytes(b'\x00' * 512 + pce, 'PCE') == hashlib.md5(pce).hexdigest()
    a78 = b'\x55' * 16384
    assert ra.ra_hash_bytes(b'\x01ATARI7800' + b'\x00' * 118 + a78, 'ATARI_7800') == hashlib.md5(a78).hexdigest()


def test_n64_normalises_to_big_endian_before_hashing():
    z64 = b'\x80\x37\x12\x40' + bytes(range(4, 64))
    v64 = bytearray(z64)
    v64[0::2], v64[1::2] = z64[1::2], z64[0::2]
    n64 = bytearray(z64)
    n64[0::4], n64[1::4], n64[2::4], n64[3::4] = z64[3::4], z64[2::4], z64[1::4], z64[0::4]
    expected = hashlib.md5(z64).hexdigest()
    assert ra.ra_hash_bytes(z64, 'N64') == expected
    assert ra.ra_hash_bytes(bytes(v64), 'N64') == expected
    assert ra.ra_hash_bytes(bytes(n64), 'N64') == expected


def test_plain_systems_and_unsupported_ones():
    rom = b'\x99' * 1000
    assert ra.ra_hash_bytes(rom, 'GBA') == hashlib.md5(rom).hexdigest()
    assert ra.ra_hash_bytes(rom, 'SEGA_MD') == hashlib.md5(rom).hexdigest()
    # Disc systems are not hashed here rather than hashed wrongly.
    assert ra.ra_hash_bytes(rom, 'PSX') is None
    assert ra.ra_hash_bytes(rom, 'NDS') is None
    assert ra.ra_hash_bytes(b'', 'NES') is None
    assert ra.console_id_for_platform('nes') == 7
    assert ra.console_id_for_platform('PSX') is None


def test_every_supported_platform_is_a_library_platform():
    names = {p.name for p in LibraryPlatform}
    assert set(ra.RA_CONSOLE_IDS) <= names


@pytest.mark.parametrize('extension,extractor_name', [('.7z', 'extract_rom_from_7z'), ('.rar', 'extract_rom_from_rar')])
def test_archive_hash_extraction_uses_rom_memory_limit(tmp_path, monkeypatch, extension, extractor_name):
    """7z/RAR hash reads must share the same cap as raw and ZIP ROMs."""
    from oneirodex.utils import rom_archive

    archive = tmp_path / f'game{extension}'
    archive.write_bytes(b'fixture')
    output = tmp_path / 'game.nes'
    output.write_bytes(b'NESDATA')
    captured = {}

    monkeypatch.setattr(rom_archive, 'path_is_supported_archive', lambda _path: True)
    monkeypatch.setattr(rom_archive, 'list_roms_in_archive', lambda _path: [('game.nes', 0)])
    monkeypatch.setattr(rom_archive, 'choose_rom_member', lambda members, **_kwargs: members[0][0])

    def extract(_archive, _tmp, *, budget, **_kwargs):
        captured['limit'] = budget.limit
        return str(output)

    monkeypatch.setattr(rom_archive, extractor_name, extract)
    assert ra._read_rom_bytes(archive, 'NES') == b'NESDATA'
    assert captured['limit'] == ra.MAX_ROM_BYTES


def test_archive_hash_refuses_oversized_extractor_output(tmp_path, monkeypatch):
    """Do not read a tool's output into memory if it exceeded the declared cap."""
    from pathlib import Path
    from types import SimpleNamespace
    from oneirodex.utils import rom_archive

    archive = tmp_path / 'game.7z'
    archive.write_bytes(b'fixture')
    output = tmp_path / 'game.nes'

    monkeypatch.setattr(rom_archive, 'path_is_supported_archive', lambda _path: True)
    monkeypatch.setattr(rom_archive, 'list_roms_in_archive', lambda _path: [('game.nes', 0)])
    monkeypatch.setattr(rom_archive, 'choose_rom_member', lambda members, **_kwargs: members[0][0])
    monkeypatch.setattr(rom_archive, 'extract_rom_from_7z', lambda *_args, **_kwargs: str(output))

    original_stat = Path.stat

    def stat_with_oversized_output(path, *args, **kwargs):
        if path == output:
            return SimpleNamespace(st_size=ra.MAX_ROM_BYTES + 1)
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'stat', stat_with_oversized_output)
    assert ra._read_rom_bytes(archive, 'NES') is None


# --- fixtures -------------------------------------------------------------------


def _library(db_session, platform=LibraryPlatform.NES):
    library = Library(name=f'{platform.name} {uuid4().hex[:8]}', platform=platform, display_order=1)
    db_session.add(library)
    db_session.commit()
    return library


def _game(db_session, library, path):
    game = Game(uuid=str(uuid4()), name=f'RA probe {uuid4().hex[:6]}', library_uuid=library.uuid, full_disk_path=str(path))
    db_session.add(game)
    db_session.commit()
    return game


def _user(db_session, role='user'):
    tag = uuid4().hex[:8]
    user = User(name=f'ra-{role}-{tag}', email=f'ra-{role}-{tag}@example.com', password_hash='unused', role=role, user_id=str(uuid4()), state=True)
    user.set_password('password123')
    db_session.add(user)
    db_session.commit()
    return user


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv('RETROACHIEVEMENTS_USERNAME', 'household')
    monkeypatch.setenv('RETROACHIEVEMENTS_API_KEY', 'not-a-real-key')
    ra.clear_progress_cache()
    yield
    ra.clear_progress_cache()


# --- index + match --------------------------------------------------------------


def test_match_platform_refreshes_index_and_persists_the_match(db_session, tmp_path, configured, monkeypatch):
    library = _library(db_session)
    rom_a = tmp_path / 'a.nes'
    rom_b = tmp_path / 'b.nes'
    rom_a.write_bytes(b'NES\x1a' + bytes([1, 0, 0, 0]) + b'\x00' * 8 + b'\xaa' * 16384)
    rom_b.write_bytes(b'\xbb' * 16384)
    hit = _game(db_session, library, rom_a)
    miss = _game(db_session, library, rom_b)
    a_hash = hashlib.md5(b'\xaa' * 16384).hexdigest()

    calls = []

    def fake_api(endpoint, params):
        calls.append((endpoint, params))
        assert endpoint == 'API_GetGameList.php'
        assert params == {'i': 7, 'h': 1, 'f': 1}
        return [
            {'ID': 1001, 'Title': 'Probe A', 'ImageIcon': '/Images/1.png', 'NumAchievements': 42, 'Points': 300, 'Hashes': [a_hash.upper(), 'ffff' * 8]},
            {'ID': 1002, 'Title': 'Empty set', 'NumAchievements': 0, 'Points': 0, 'Hashes': ['eeee' * 8]},
        ]

    monkeypatch.setattr(ra, '_api_get', fake_api)

    summary = ra.match_platform('NES')
    assert summary['indexed_hashes'] == 3
    assert summary['considered'] == 2
    assert summary['hashed'] == 2
    assert summary['matched'] == 1

    db_session.refresh(hit)
    db_session.refresh(miss)
    assert hit.ra_hash == a_hash
    assert hit.ra_game_id == 1001
    assert hit.ra_achievements == 42
    assert ra.supports_achievements(hit) is True
    assert ra.achievement_fields(hit)['ra_url'] == 'https://retroachievements.org/game/1001'
    assert miss.ra_hash == hashlib.md5(b'\xbb' * 16384).hexdigest()
    assert miss.ra_game_id is None
    assert ra.supports_achievements(miss) is False

    # Second run inside the TTL: no provider call, hashes reused.
    calls.clear()
    again = ra.match_platform('NES')
    assert calls == []
    assert again['hashed'] == 0 and again['matched'] == 1

    # Past the TTL the index is fetched again.
    db_session.query(RetroAchievementsIndexEntry).update({
        RetroAchievementsIndexEntry.fetched_at: datetime.now(timezone.utc) - timedelta(days=2),
    })
    db_session.commit()
    ra.match_platform('NES')
    assert len(calls) == 1


def test_a_matched_set_without_achievements_promises_nothing(db_session, tmp_path, configured, monkeypatch):
    """R2: `supports_achievements` gates on the count, not on the match."""
    library = _library(db_session, LibraryPlatform.GBA)
    rom = tmp_path / 'x.gba'
    rom.write_bytes(b'\xcc' * 4096)
    game = _game(db_session, library, rom)
    digest = hashlib.md5(b'\xcc' * 4096).hexdigest()
    monkeypatch.setattr(ra, '_api_get', lambda endpoint, params: [
        {'ID': 77, 'Title': 'No set yet', 'NumAchievements': 0, 'Points': 0, 'Hashes': [digest]},
    ])
    ra.match_platform('GBA')
    db_session.refresh(game)
    assert game.ra_game_id == 77
    assert game.ra_achievements == 0
    fields = ra.achievement_fields(game)
    assert fields == {'supports_achievements': False, 'ra_game_id': None, 'ra_achievements': 0, 'ra_url': None}


def test_unconfigured_is_honest_no_data(db_session, monkeypatch):
    monkeypatch.delenv('RETROACHIEVEMENTS_USERNAME', raising=False)
    monkeypatch.delenv('RETROACHIEVEMENTS_API_KEY', raising=False)
    assert ra.configured() is False
    with pytest.raises(RuntimeError):
        ra.match_platform('NES')
    with pytest.raises(ValueError):
        ra.match_platform('PSX')
    status = ra.status_summary()
    assert status['configured'] is False
    assert status['consoles'] == []
    assert 'NES' in status['supported_platforms']
    assert ra.fetch_member_progress('someone', 1) is None


# --- routes ---------------------------------------------------------------------


def test_match_route_is_admin_only(client, db_session, configured_install):
    member = _user(db_session)
    _login(client, member)
    denied = client.post('/api/retroachievements/match', json={'platform': 'NES'})
    assert denied.status_code in (302, 403)
    assert client.get('/api/retroachievements/status').status_code in (302, 403)


def test_match_route_refuses_when_unconfigured(client, db_session, configured_install, monkeypatch):
    monkeypatch.delenv('RETROACHIEVEMENTS_USERNAME', raising=False)
    monkeypatch.delenv('RETROACHIEVEMENTS_API_KEY', raising=False)
    admin = _user(db_session, role='admin')
    _login(client, admin)
    refused = client.post('/api/retroachievements/match', json={'platform': 'NES'})
    assert refused.status_code == 403, refused.get_json()
    assert 'not configured' in refused.get_json()['error']

    status = client.get('/api/retroachievements/status').get_json()
    assert status['configured'] is False


def test_match_route_runs_and_bad_platform_lists_supported(client, db_session, configured_install, configured, monkeypatch):
    admin = _user(db_session, role='admin')
    _login(client, admin)
    monkeypatch.setattr(ra, '_api_get', lambda endpoint, params: [])
    ok = client.post('/api/retroachievements/match', json={'platform': 'nes'})
    assert ok.status_code == 200, ok.get_json()
    assert ok.get_json()['platform'] == 'NES'
    bad = client.post('/api/retroachievements/match', json={'platform': 'PSX'})
    assert bad.status_code == 400
    assert 'NES' in bad.get_json()['supported']
    # extra keys are refused by the body model
    assert client.post('/api/retroachievements/match', json={'platform': 'NES', 'x': 1}).status_code == 422


def test_game_achievements_route_reports_set_and_member_progress(client, db_session, configured_install, configured, monkeypatch):
    from oneirodex.models import UserPreference

    library = _library(db_session)
    game = _game(db_session, library, '/nonexistent/a.nes')
    game.ra_game_id = 1001
    game.ra_achievements = 3
    db_session.commit()
    member = _user(db_session)
    _login(client, member)

    # No username yet: the set is shown, no personal column.
    body = client.get(f'/api/games/{game.uuid}/achievements').get_json()
    assert body['supports_achievements'] is True
    assert body['ra_achievements'] == 3
    assert body['unlocks_here'] is False
    assert body['me'] is None

    saved = client.put('/api/me/retroachievements', json={'ra_username': 'Player_1'})
    assert saved.status_code == 200, saved.get_json()
    assert client.put('/api/me/retroachievements', json={'ra_username': 'bad name!'}).status_code == 400
    prefs = db_session.execute(db_session.query(UserPreference).filter_by(user_id=member.id).statement).scalars().first()
    assert prefs.ra_username == 'Player_1'

    monkeypatch.setattr(ra, '_api_get', lambda endpoint, params: {
        'NumAchievements': 3, 'NumAwardedToUser': 1, 'NumAwardedToUserHardcore': 0,
        'UserCompletion': '33.33%', 'UserCompletionHardcore': '0.00%',
        'Achievements': {
            '2': {'ID': 2, 'Title': 'Second', 'Description': 'B', 'Points': 5, 'BadgeName': '00002', 'DateEarned': None, 'DisplayOrder': 2},
            '1': {'ID': 1, 'Title': 'First', 'Description': 'A', 'Points': 1, 'BadgeName': '00001', 'DateEarned': '2026-09-01 10:00:00', 'DisplayOrder': 1},
        },
    })
    body = client.get(f'/api/games/{game.uuid}/achievements').get_json()
    assert body['me']['username'] == 'Player_1'
    assert body['me']['earned'] == 1
    assert [a['title'] for a in body['me']['achievements']] == ['First', 'Second']
    assert body['me']['achievements'][0]['earned'] is True
    assert body['me']['achievements'][0]['badge_url'] == 'https://media.retroachievements.org/Badge/00001.png'

    # Clearing the username removes the personal column again.
    client.put('/api/me/retroachievements', json={'ra_username': ''})
    assert client.get(f'/api/games/{game.uuid}/achievements').get_json()['me'] is None


def test_browse_and_plugins_carry_the_flag(client, db_session, configured_install, configured):
    library = _library(db_session)
    game = _game(db_session, library, '/nonexistent/b.nes')
    game.ra_game_id = 5
    game.ra_achievements = 12
    db_session.commit()
    member = _user(db_session)
    _login(client, member)
    rows = client.get(f'/browse_games?library_uuid={library.uuid}&per_page=50').get_json()['games']
    row = next(r for r in rows if r['uuid'] == game.uuid)
    assert row['supports_achievements'] is True
    assert row['ra_url'] == 'https://retroachievements.org/game/5'

    from oneirodex.utils.plugins import get_plugin

    assert get_plugin('achievements.retroachievements')['status'] == 'configured'


def test_a_truncated_n64_dump_does_not_abort_the_whole_match():
    """The byteswaps are whole-word; a short tail must not raise.

    `match_platform` walks every game on the platform in one loop, so a
    ValueError out of the hasher took the entire run down with it — one corrupt
    dump and nothing on that system gets matched.
    """
    # v64 magic, odd length: the 16-bit swap has no partner for the last byte.
    odd = b'\x37\x80\x40\x12' + bytes(range(61))
    assert len(ra.ra_hash_bytes(odd, 'N64')) == 32
    # n64 magic, length not a multiple of 4: same problem, wider word.
    not_word_aligned = b'\x40\x12\x37\x80' + bytes(range(62))
    assert len(ra.ra_hash_bytes(not_word_aligned, 'N64')) == 32


def test_the_n64_guard_did_not_break_normal_dumps():
    """Well-formed images in all three byte orders still agree."""
    z64 = b'\x80\x37\x12\x40' + bytes(range(4, 64))
    v64 = bytearray(z64)
    v64[0::2], v64[1::2] = z64[1::2], z64[0::2]
    n64 = bytearray(z64)
    n64[0::4], n64[1::4], n64[2::4], n64[3::4] = z64[3::4], z64[2::4], z64[1::4], z64[0::4]
    expected = ra.ra_hash_bytes(z64, 'N64')
    assert ra.ra_hash_bytes(bytes(v64), 'N64') == expected
    assert ra.ra_hash_bytes(bytes(n64), 'N64') == expected


def test_a_nes_trainer_is_skipped_like_rcheevos_does():
    """Flags6 bit 2 puts a 512-byte trainer between the header and PRG.

    Hashing from offset 16 regardless swallowed the trainer as the first 512
    bytes of PRG and truncated 512 bytes off the real end — a digest that is
    neither the trainer-inclusive nor the trainer-exclusive one, so every
    trainer ROM in a library matched nothing and looked simply unsupported.
    """
    prg = b'\xaa' * 16384
    chr_ = b'\x55' * 8192
    expected = hashlib.md5(prg + chr_).hexdigest()

    with_trainer = b'NES\x1a' + bytes([1, 1, 0x04, 0]) + b'\x00' * 8 + b'\xcc' * 512 + prg + chr_
    without = b'NES\x1a' + bytes([1, 1, 0x00, 0]) + b'\x00' * 8 + prg + chr_

    assert ra.ra_hash_bytes(with_trainer, 'NES') == expected
    assert ra.ra_hash_bytes(without, 'NES') == expected
