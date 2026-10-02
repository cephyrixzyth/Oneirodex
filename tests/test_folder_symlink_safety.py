"""Symlinks inside a scanned game folder are not followed (finding: any member could
download any file the container can read via ``game.bin -> /etc/whatever``).

Covers the walk that builds folder downloads (``zipstream``), the folder ROM
resolve, the cue bundle, DAT hashing, the local cover / screenshot / sidecar
files that ``send_file`` serves, the NFO text stored for every game, and the
firmware import (a collection folder is somebody's share too).
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from uuid import uuid4

import pytest

from oneirodex.utils.rom_archive import (
    ArchiveRomError,
    bundle_playable_rom_zip,
    resolve_playable_rom_path,
)
from oneirodex.utils.rom_hash import (
    hash_archive_inner_primary_dumps,
    hash_fileobj,
    hash_rom_file,
    resolve_hashable_file,
)
from oneirodex.utils.security import is_path_within, is_plain_file_within, open_plain_file_within
from oneirodex.utils.zipstream import async_generate_zipstream_chunks, estimate_zip_size

SECRET = b'TOP-SECRET-CONTENTS-' * 40
GAME = b'REAL-GAME-BYTES-' * 40
SEVEN_Z = shutil.which('7z') or shutil.which('7za')
needs_7z = pytest.mark.skipif(not SEVEN_Z, reason='host 7z not installed')


def _link(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        os.symlink(target, link, target_is_directory=directory)
    except (OSError, NotImplementedError):
        pytest.skip('symlinks are not available here')


@pytest.fixture
def secret(tmp_path):
    """A readable file *outside* every game folder in these tests."""
    path = tmp_path / 'outside' / 'secret.bin'
    path.parent.mkdir()
    path.write_bytes(SECRET)
    return path


@pytest.fixture
def game_dir(tmp_path):
    folder = tmp_path / 'library' / 'Some Game'
    folder.mkdir(parents=True)
    return folder


# --------------------------------------------------------------------------
# path helpers
# --------------------------------------------------------------------------

def test_is_path_within_is_strict_and_resolves_links(tmp_path, secret):
    base = tmp_path / 'base'
    (base / 'sub').mkdir(parents=True)
    (base / 'sub' / 'f.txt').write_text('x')
    assert is_path_within(base, base / 'sub' / 'f.txt')
    assert not is_path_within(base, base), 'a directory is not within itself'
    assert not is_path_within(base, base / 'sub' / '..' / '..' / 'outside' / 'secret.bin')
    _link(base / 'escape', secret.parent, directory=True)
    assert not is_path_within(base, base / 'escape' / 'secret.bin')


def test_is_plain_file_within_rejects_links_even_inside_the_folder(tmp_path):
    base = tmp_path / 'base'
    base.mkdir()
    (base / 'real.bin').write_bytes(b'x')
    _link(base / 'alias.bin', base / 'real.bin')
    assert is_plain_file_within(base, base / 'real.bin')
    assert not is_plain_file_within(base, base / 'alias.bin')
    assert not is_plain_file_within(base, base / 'missing.bin')


# --------------------------------------------------------------------------
# folder download (zipstream)
# --------------------------------------------------------------------------

def _collect(source: Path) -> bytes:
    async def run():
        out = b''
        async for chunk in async_generate_zipstream_chunks(str(source)):
            out += chunk
        return out

    return asyncio.run(run())


def test_folder_download_skips_symlinked_files_and_folders(game_dir, secret):
    (game_dir / 'game.iso').write_bytes(GAME)
    (game_dir / 'docs').mkdir()
    (game_dir / 'docs' / 'readme.txt').write_bytes(b'hello')
    _link(game_dir / 'leak.bin', secret)
    _link(game_dir / 'docs' / 'leak2.txt', secret)
    _link(game_dir / 'leakdir', secret.parent, directory=True)

    blob = _collect(game_dir)

    assert SECRET not in blob, 'the link target must not be streamed into the zip'
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        assert sorted(archive.namelist()) == ['docs/readme.txt', 'game.iso']
        assert archive.read('game.iso') == GAME


def test_folder_download_still_zips_ordinary_content(game_dir):
    (game_dir / 'a.bin').write_bytes(b'A' * 10)
    (game_dir / 'sub').mkdir()
    (game_dir / 'sub' / 'b.bin').write_bytes(b'B' * 10)
    (game_dir / 'oneirodex.json').write_text('{}')
    (game_dir / 'updates').mkdir()
    (game_dir / 'updates' / 'patch.bin').write_bytes(b'P')
    with zipfile.ZipFile(io.BytesIO(_collect(game_dir))) as archive:
        assert sorted(archive.namelist()) == ['a.bin', 'sub/b.bin']


def test_size_estimate_ignores_links(game_dir, secret):
    (game_dir / 'game.iso').write_bytes(b'x' * 1000)
    _link(game_dir / 'leak.bin', secret)
    assert estimate_zip_size(str(game_dir)) == 1000 + 100


def test_a_symlinked_game_folder_root_is_still_downloadable(tmp_path):
    real = tmp_path / 'nas' / 'Game'
    real.mkdir(parents=True)
    (real / 'g.bin').write_bytes(GAME)
    root_link = tmp_path / 'library' / 'Game'
    root_link.parent.mkdir()
    _link(root_link, real, directory=True)
    with zipfile.ZipFile(io.BytesIO(_collect(root_link))) as archive:
        assert archive.namelist() == ['g.bin']


# --------------------------------------------------------------------------
# folder ROM resolve + cue bundle
# --------------------------------------------------------------------------

def test_folder_resolve_does_not_serve_a_linked_rom(game_dir, secret, tmp_path):
    secret_rom = tmp_path / 'outside' / 'private.nes'
    secret_rom.write_bytes(SECRET)
    _link(game_dir / 'game.nes', secret_rom)
    with pytest.raises(ArchiveRomError) as exc:
        resolve_playable_rom_path(str(game_dir), cache_dir=str(tmp_path / 'cache'))
    assert exc.value.code == 'ambiguous_folder'


def test_folder_resolve_prefers_the_real_rom_over_a_link(game_dir, tmp_path):
    secret_rom = tmp_path / 'outside' / 'private.nes'
    secret_rom.parent.mkdir()
    secret_rom.write_bytes(SECRET)
    (game_dir / 'real.nes').write_bytes(GAME)
    _link(game_dir / 'other.nes', secret_rom)
    rom, name = resolve_playable_rom_path(str(game_dir), cache_dir=str(tmp_path / 'cache'))
    assert name == 'real.nes'
    assert Path(rom).read_bytes() == GAME


def test_folder_resolve_does_not_unpack_a_linked_archive(game_dir, tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    private_zip = outside / 'private.zip'
    with zipfile.ZipFile(private_zip, 'w') as archive:
        archive.writestr('private.nes', SECRET)
    _link(game_dir / 'game.zip', private_zip)
    with pytest.raises(ArchiveRomError):
        resolve_playable_rom_path(str(game_dir), cache_dir=str(tmp_path / 'cache'))
    assert not (tmp_path / 'cache' / 'private.nes').exists()


def test_cue_bundle_leaves_linked_companions_out(game_dir, secret, tmp_path):
    cue = game_dir / 'disc.cue'
    cue.write_text('FILE "disc.bin" BINARY\n  TRACK 01 MODE1/2352\n    INDEX 01 00:00:00\n')
    (game_dir / 'disc.bin').write_bytes(GAME)
    _link(game_dir / 'leak.bin', secret)
    zip_path, name = bundle_playable_rom_zip(str(cue), str(tmp_path / 'cache'))
    assert name == 'play.zip'
    with zipfile.ZipFile(zip_path) as archive:
        assert sorted(archive.namelist()) == ['disc.bin', 'disc.cue']
        assert SECRET not in b''.join(archive.read(n) for n in archive.namelist())


def test_cue_bundle_with_only_a_linked_companion_is_not_bundled(game_dir, secret, tmp_path):
    cue = game_dir / 'disc.cue'
    cue.write_text('FILE "disc.bin" BINARY\n')
    _link(game_dir / 'disc.bin', secret)
    rom_path, name = bundle_playable_rom_zip(str(cue), str(tmp_path / 'cache'))
    assert (rom_path, name) == (str(cue), 'disc.cue')


# --------------------------------------------------------------------------
# DAT hashing
# --------------------------------------------------------------------------

def test_folder_hashing_ignores_a_linked_rom(game_dir, secret):
    _link(game_dir / 'game.bin', secret)
    assert resolve_hashable_file(game_dir) is None
    assert hash_rom_file(game_dir) is None


def test_folder_hashing_still_finds_the_one_real_rom(game_dir, secret):
    (game_dir / 'game.nes').write_bytes(GAME)
    _link(game_dir / 'leak.bin', secret)
    assert resolve_hashable_file(game_dir) == game_dir / 'game.nes'
    assert hash_rom_file(game_dir) == hash_fileobj(io.BytesIO(GAME))


@needs_7z
def test_inner_archive_hashing_cannot_be_used_to_move_a_victim(tmp_path, monkeypatch):
    """Scan-time path from the finding: a zip named ``.rar`` reaches host 7z."""
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    victim = scratch / 'victim.nes'          # where ``../victim.nes`` points from od-dat-inner-*
    victim.write_bytes(b'VICTIM-BYTES' * 10)
    monkeypatch.setattr(tempfile, 'tempdir', str(scratch))

    archive = tmp_path / 'lib' / 'game.rar'
    archive.parent.mkdir()
    with zipfile.ZipFile(archive, 'w') as zf:
        zf.writestr('../victim.nes', b'EVIL' * 100)
        zf.writestr('ok/a.nes', GAME)

    digests = hash_archive_inner_primary_dumps(archive)

    assert victim.read_bytes() == b'VICTIM-BYTES' * 10
    assert digests == [hash_fileobj(io.BytesIO(GAME))]
    assert all(d['md5'] != hashlib.md5(b'VICTIM-BYTES' * 10).hexdigest() for d in digests)


# --------------------------------------------------------------------------
# local cover / screenshot / sidecar (send_file)
# --------------------------------------------------------------------------

def test_local_cover_and_screenshots_skip_links(game_dir, secret):
    from oneirodex.utils.local_metadata import get_local_cover_path, get_local_screenshots, has_local_images

    _link(game_dir / 'cover.jpg', secret)
    _link(game_dir / 'screenshot-1.png', secret)
    assert get_local_cover_path(str(game_dir)) is None
    assert get_local_screenshots(str(game_dir)) == []
    assert has_local_images(str(game_dir)) is False

    (game_dir / 'folder.png').write_bytes(b'\x89PNG')
    (game_dir / 'screenshot-2.jpg').write_bytes(b'\xff\xd8')
    assert get_local_cover_path(str(game_dir)) == str(game_dir / 'folder.png')
    assert get_local_screenshots(str(game_dir)) == [str(game_dir / 'screenshot-2.jpg')]


def test_a_symlinked_game_folder_root_still_finds_its_own_cover(tmp_path, secret):
    """Only links *inside* the folder are refused; a link as the folder itself is the operator's."""
    from oneirodex.utils.local_metadata import get_local_cover_path

    (secret.parent / 'cover.jpg').write_bytes(b'\xff\xd8real-cover')
    folder_link = tmp_path / 'library' / 'Linked'
    folder_link.parent.mkdir(parents=True)
    _link(folder_link, secret.parent, directory=True)
    assert get_local_cover_path(str(folder_link)) == str(folder_link / 'cover.jpg')

    plain = tmp_path / 'library' / 'Plain'
    plain.mkdir()
    assert get_local_cover_path(str(plain)) is None


def test_sidecar_metadata_that_is_a_link_is_ignored_and_never_written_through(game_dir, tmp_path):
    from oneirodex.utils.local_metadata import has_local_metadata, read_local_metadata, write_local_metadata

    victim = tmp_path / 'outside' / 'precious.json'
    victim.parent.mkdir()
    victim.write_text(json.dumps({'igdb_id': 7, 'keep': 'me'}))
    _link(game_dir / 'oneirodex.json', victim)

    assert has_local_metadata(str(game_dir)) is False
    assert read_local_metadata(str(game_dir)) is None
    assert write_local_metadata(str(game_dir), 123, game_title='X') is False
    assert json.loads(victim.read_text()) == {'igdb_id': 7, 'keep': 'me'}, 'the link target was not overwritten'


def test_sidecar_metadata_round_trips_for_a_plain_file(game_dir):
    from oneirodex.utils.local_metadata import read_local_metadata, write_local_metadata

    assert write_local_metadata(str(game_dir), 4242, game_title='Game') is True
    assert read_local_metadata(str(game_dir))['igdb_id'] == 4242


def _make_game(db_session, folder: Path):
    from oneirodex.models import Game, Library
    from oneirodex.platform import LibraryPlatform

    library = Library(name=f'Lib {uuid4().hex[:8]}', platform=LibraryPlatform.PCWIN, display_order=1)
    db_session.add(library)
    db_session.flush()
    game = Game(
        uuid=str(uuid4()),
        name=f'Cover probe {uuid4().hex[:6]}',
        library_uuid=library.uuid,
        full_disk_path=str(folder),
    )
    db_session.add(game)
    db_session.commit()
    return game


def _make_admin(db_session):
    from oneirodex.models import User

    uid = str(uuid4())
    user = User(name=f'adm_{uid[:8]}', email=f'adm_{uid[:8]}@example.com', role='admin', user_id=uid, state=True)
    user.set_password('password123')
    db_session.add(user)
    db_session.commit()
    return user


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.get_id())
        sess['_fresh'] = True


def test_local_image_route_serves_a_real_cover_but_not_a_linked_one(client, app, db_session, tmp_path, monkeypatch, secret):
    library_root = tmp_path / 'library'
    folder = library_root / 'Cover Game'
    folder.mkdir(parents=True)
    monkeypatch.setitem(app.config, 'DATA_FOLDER_GAMES', str(library_root))
    game = _make_game(db_session, folder)
    _login(client, _make_admin(db_session))

    (folder / 'cover.jpg').write_bytes(b'\xff\xd8REAL-COVER')
    ok = client.get(f'/game/{game.uuid}/local_image/cover')
    assert ok.status_code == 200
    assert ok.data == b'\xff\xd8REAL-COVER'

    (folder / 'cover.jpg').unlink()
    _link(folder / 'cover.jpg', secret)
    blocked = client.get(f'/game/{game.uuid}/local_image/cover')
    assert blocked.status_code == 404
    assert SECRET not in blocked.data

    _link(folder / 'screenshot-1.png', secret)
    blocked_shot = client.get(f'/game/{game.uuid}/local_image/screenshot?index=0')
    assert blocked_shot.status_code == 404
    assert SECRET not in blocked_shot.data


# --------------------------------------------------------------------------
# open_plain_file_within: the check runs on the descriptor, not the path
# --------------------------------------------------------------------------

def test_open_plain_file_within_reads_a_plain_file(game_dir):
    (game_dir / 'a.bin').write_bytes(GAME)
    with open_plain_file_within(game_dir, game_dir / 'a.bin') as handle:
        assert handle.read() == GAME


def test_open_plain_file_within_refuses_links_however_they_point(game_dir, secret):
    (game_dir / 'real.bin').write_bytes(GAME)
    _link(game_dir / 'out.bin', secret)
    _link(game_dir / 'in.bin', game_dir / 'real.bin')
    _link(game_dir / 'dir', secret.parent, directory=True)
    for name in ('out.bin', 'in.bin', 'dir/secret.bin', 'missing.bin'):
        with pytest.raises(OSError):
            open_plain_file_within(game_dir, game_dir / name)


def test_open_plain_file_within_refuses_a_path_outside_the_folder(game_dir, secret):
    with pytest.raises(OSError):
        open_plain_file_within(game_dir, secret)


def test_open_plain_file_within_trusts_the_descriptor_over_the_path(game_dir, secret, monkeypatch):
    """A parent folder swapped for a link at open time and back before the
    checks leaves a path that looks fine and a descriptor that is not: where the
    kernel can say what the descriptor is, that answer decides."""
    from oneirodex.utils import security

    (game_dir / 'a.bin').write_bytes(GAME)
    monkeypatch.setattr(security, '_opened_path', lambda fd: str(secret))
    with pytest.raises(OSError):
        open_plain_file_within(game_dir, game_dir / 'a.bin')


@pytest.mark.skipif(not os.path.isdir('/proc/self/fd'), reason='needs /proc/self/fd')
def test_opened_path_names_the_real_file(game_dir):
    from oneirodex.utils.security import _opened_path

    (game_dir / 'a.bin').write_bytes(GAME)
    fd = os.open(game_dir / 'a.bin', os.O_RDONLY)
    try:
        assert _opened_path(fd) == os.path.realpath(game_dir / 'a.bin')
    finally:
        os.close(fd)


@pytest.mark.skipif(not hasattr(os, 'mkfifo'), reason='needs POSIX FIFOs')
def test_open_plain_file_within_does_not_hang_on_a_fifo(game_dir):
    import signal

    os.mkfifo(game_dir / 'pipe.nfo')
    signal.alarm(5)  # a blocking open would never return
    try:
        with pytest.raises(OSError):
            open_plain_file_within(game_dir, game_dir / 'pipe.nfo')
    finally:
        signal.alarm(0)


# --------------------------------------------------------------------------
# NFO text (Game.nfo_content is shown to every member)
# --------------------------------------------------------------------------

def test_nfo_that_is_a_link_is_never_read(game_dir, secret):
    from oneirodex.utils.helpers.fs import read_first_nfo_content

    _link(game_dir / 'info.nfo', secret)
    assert read_first_nfo_content(str(game_dir)) is None


def test_a_real_nfo_wins_over_a_linked_one_whatever_the_order(game_dir, secret):
    from oneirodex.utils.helpers.fs import read_first_nfo_content

    _link(game_dir / 'a_leak.nfo', secret)
    (game_dir / 'b_real.nfo').write_text('REAL NFO', encoding='utf-8')
    _link(game_dir / 'c_leak.nfo', secret)
    assert read_first_nfo_content(str(game_dir)) == 'REAL NFO'


def test_only_links_inside_the_folder_are_refused_not_the_folder_itself(tmp_path, secret):
    """The folder being a link is the operator's choice; a link *to a file* inside it is not."""
    from oneirodex.utils.helpers.fs import read_first_nfo_content

    (secret.parent / 'x.nfo').write_bytes(b'REAL-NFO-VIA-LINKED-FOLDER')
    game = tmp_path / 'library' / 'G'
    game.mkdir(parents=True)
    _link(game / 'nfos', secret.parent, directory=True)
    assert read_first_nfo_content(str(game / 'nfos')) == 'REAL-NFO-VIA-LINKED-FOLDER'

    folder = tmp_path / 'library' / 'H'
    folder.mkdir()
    _link(folder / 'x.nfo', secret.parent / 'x.nfo')
    assert read_first_nfo_content(str(folder)) is None


def test_nfo_reader_used_by_the_add_game_form_ignores_a_linked_file(app, tmp_path, monkeypatch, secret):
    """The finding's path: info.nfo -> a readable file, then add/edit stores it."""
    from oneirodex.routes_games_ext.add import read_first_nfo_content as add_reader

    library_root = tmp_path / 'library'
    folder = library_root / 'Linked Nfo'
    folder.mkdir(parents=True)
    monkeypatch.setitem(app.config, 'DATA_FOLDER_GAMES', str(library_root))
    _link(folder / 'info.nfo', secret)
    with app.app_context():
        assert add_reader(str(folder)) is None
    (folder / 'real.nfo').write_text('hello', encoding='utf-8')
    with app.app_context():
        assert add_reader(str(folder)) == 'hello'


# --------------------------------------------------------------------------
# folder download: the file is vetted when the download reaches it
# --------------------------------------------------------------------------

def test_a_file_swapped_for_a_link_after_the_walk_is_not_streamed(game_dir, secret, monkeypatch):
    """TOCTOU: the walk saw a plain ``big.bin``; it becomes a link before its turn."""
    from oneirodex.utils import zipstream as zs

    (game_dir / 'big.bin').write_bytes(GAME)
    (game_dir / 'ok.bin').write_bytes(b'ok-bytes')
    real_walk = zs._iter_folder_files

    def walk_then_swap(source, excluded, **kwargs):
        found = list(real_walk(source, excluded, **kwargs))   # the whole walk happens first
        (game_dir / 'big.bin').unlink()
        _link(game_dir / 'big.bin', secret)
        return iter(found)

    monkeypatch.setattr(zs, '_iter_folder_files', walk_then_swap)
    monkeypatch.setattr(zs, 'log_system_event', lambda *_a, **_k: None)  # the error path logs to the DB

    received = []

    async def run():
        async for chunk in zs.async_generate_zipstream_chunks(str(game_dir)):
            received.append(chunk)

    with pytest.raises(OSError):
        asyncio.run(run())
    assert SECRET not in b''.join(received), 'the link target must not be streamed'


def test_folder_download_keeps_unix_modes(game_dir):
    """Members are streamed from our own iterator; they must keep what ``write`` recorded."""
    if os.name == 'nt':
        pytest.skip('POSIX modes')
    exe = game_dir / 'run.sh'
    exe.write_bytes(b'#!/bin/sh\n')
    exe.chmod(0o755)
    plain = game_dir / 'data.bin'
    plain.write_bytes(GAME)
    plain.chmod(0o640)
    with zipfile.ZipFile(io.BytesIO(_collect(game_dir))) as archive:
        modes = {info.filename: (info.external_attr >> 16) & 0o777 for info in archive.infolist()}
        assert modes == {'run.sh': 0o755, 'data.bin': 0o640}
        assert archive.read('data.bin') == GAME


# --------------------------------------------------------------------------
# firmware import
# --------------------------------------------------------------------------

def test_firmware_scan_skips_linked_files(tmp_path, secret):
    from oneirodex.utils.bios_install import scan_for_firmware

    pack = tmp_path / 'pack'
    (pack / 'psx').mkdir(parents=True)
    _link(pack / 'psx' / 'scph5501.bin', secret)
    _link(pack / 'saturn_bios.bin', pack / 'psx' / 'scph5501.bin')
    _link(pack / 'linked_dir', secret.parent, directory=True)
    (secret.parent / 'scph5500.bin').write_bytes(SECRET)
    (pack / 'psx' / 'scph5500.bin').write_bytes(GAME)
    assert scan_for_firmware(str(pack)) == {'scph5500.bin': [str(pack / 'psx' / 'scph5500.bin')]}


def test_firmware_copy_refuses_a_file_swapped_for_a_link_after_the_scan(tmp_path, secret):
    from oneirodex.utils.bios_install import _copy_firmware

    pack = tmp_path / 'pack'
    pack.mkdir()
    _link(pack / 'scph5501.bin', secret)
    dest = tmp_path / 'volume' / 'scph5501.bin'
    dest.parent.mkdir()
    with pytest.raises(OSError):
        _copy_firmware(str(pack), str(pack / 'scph5501.bin'), str(dest))
    assert not dest.exists(), 'nothing is created when the source is refused'


def test_firmware_boot_import_and_apply_never_copy_a_linked_file(app, tmp_path, secret):
    from oneirodex.utils.bios_install import apply_firmware_import, import_bios_from

    pack = tmp_path / 'pack'
    pack.mkdir()
    _link(pack / 'scph5501.bin', secret)
    (pack / 'saturn_bios.bin').write_bytes(GAME)
    volume = tmp_path / 'volume'
    volume2 = tmp_path / 'volume2'
    with app.app_context():
        assert import_bios_from(str(pack), str(volume)) == 1
        result = apply_firmware_import(str(pack), str(volume2))
    assert sorted(p.name for p in volume.iterdir()) == ['saturn_bios.bin']
    assert result['copied'] == ['saturn_bios.bin']
    assert not (volume2 / 'scph5501.bin').exists()
    for copy in (volume / 'saturn_bios.bin', volume2 / 'saturn_bios.bin'):
        assert copy.read_bytes() == GAME


def test_firmware_apply_reports_a_swapped_file_instead_of_copying_it(app, tmp_path, secret, monkeypatch):
    from oneirodex.utils import bios_install

    pack = tmp_path / 'pack'
    pack.mkdir()
    _link(pack / 'scph5501.bin', secret)  # what the file became after the scan
    monkeypatch.setattr(
        bios_install, 'scan_for_firmware',
        lambda *_a, **_k: {'scph5501.bin': [str(pack / 'scph5501.bin')]},
    )
    volume = tmp_path / 'volume'
    with app.app_context():
        result = bios_install.apply_firmware_import(str(pack), str(volume))
    assert result['copied'] == []
    assert 'scph5501.bin' in result['unresolved']
    assert not (volume / 'scph5501.bin').exists()


def test_import_bios_script_skips_and_refuses_links(tmp_path, secret):
    import importlib.util

    script = Path(__file__).resolve().parents[1] / 'scripts' / 'import_bios.py'
    spec = importlib.util.spec_from_file_location('import_bios_script_under_test', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    pack = tmp_path / 'pack'
    pack.mkdir()
    _link(pack / 'scph5501.bin', secret)
    (pack / 'scph5500.bin').write_bytes(GAME)
    found = module.scan(str(pack), module.wanted_names())
    assert found == {'scph5500.bin': [str(pack / 'scph5500.bin')]}
    with pytest.raises(OSError):
        module._copy(str(pack), str(pack / 'scph5501.bin'), str(tmp_path / 'out.bin'))
    assert not (tmp_path / 'out.bin').exists()
