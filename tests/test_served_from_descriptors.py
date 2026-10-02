"""Members are served from the descriptor that was vetted, not from a path that was checked.

A game folder is a share somebody else can write to. Checking a path and then
opening it (with a log row, an extraction or a long zip walk in between) lets
that somebody swap the file, or the folder, for a link to something the server
can read. These tests make the swap happen inside the window and expect the
response to carry what was vetted, or nothing.
"""

from __future__ import annotations

import asyncio
import http.client
import io
import os
import socket
import sys
import threading
import time
import types
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

import asgi as asgi_mod
from oneirodex.utils import security
from oneirodex.utils import zipstream as zs
from oneirodex.utils.rom_archive import ArchiveRomError, bundle_playable_rom_zip
from oneirodex.utils.security import is_path_within, is_plain_file_within, open_plain_file_within

SECRET = b'TOP-SECRET-CONTENTS-' * 40
GAME = b'REAL-GAME-BYTES-' * 40


def _link(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        os.symlink(target, link, target_is_directory=directory)
    except (OSError, NotImplementedError):
        pytest.skip('symlinks are not available here')


def _swap_for_link(path: Path, target: Path) -> None:
    path.unlink()
    _link(path, target)


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


def _quiet(*_args, **_kwargs):
    return True


# --------------------------------------------------------------------------
# a folder resolved once is compared as given
# --------------------------------------------------------------------------

def test_a_resolved_base_does_not_follow_a_folder_swapped_for_a_link(game_dir, secret):
    (game_dir / 'a.bin').write_bytes(GAME)
    real_base = os.path.realpath(game_dir)
    game_dir.rename(game_dir.with_name('Some Game.moved'))
    _link(game_dir, secret.parent, directory=True)
    escaped = game_dir / 'secret.bin'

    # Resolving the base again follows the link, so its target becomes "the folder".
    assert is_path_within(game_dir, escaped)
    assert is_plain_file_within(game_dir, escaped)

    # A base resolved before the swap stays where it was.
    assert not is_path_within(real_base, escaped, base_is_resolved=True)
    assert not is_plain_file_within(real_base, escaped, base_is_resolved=True)
    with pytest.raises(OSError):
        open_plain_file_within(real_base, escaped, base_is_resolved=True)


def test_a_resolved_base_still_serves_files_in_it(game_dir):
    (game_dir / 'a.bin').write_bytes(GAME)
    real_base = os.path.realpath(game_dir)
    assert is_path_within(real_base, game_dir / 'a.bin', base_is_resolved=True)
    assert is_plain_file_within(real_base, game_dir / 'a.bin', base_is_resolved=True)
    with open_plain_file_within(real_base, game_dir / 'a.bin', base_is_resolved=True) as handle:
        assert handle.read() == GAME
    assert not is_path_within(real_base, real_base, base_is_resolved=True), 'a folder is not within itself'


def test_the_folder_download_walks_against_the_root_it_was_given(game_dir, secret):
    """The generator takes a pre-resolved root as the boundary and never resolves it again."""
    (game_dir / 'a.bin').write_bytes(GAME)
    real_root = os.path.realpath(game_dir)
    game_dir.rename(game_dir.with_name('Some Game.moved'))
    (secret.parent / 'other.bin').write_bytes(SECRET)
    _link(game_dir, secret.parent, directory=True)

    blob = _collect(game_dir, source_is_resolved=True)

    assert SECRET not in blob
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        assert archive.namelist() == [], 'nothing under the swapped-in folder passes the old root'
    assert real_root != os.path.realpath(game_dir)


# --------------------------------------------------------------------------
# without /proc: the OS is asked about the descriptor on macOS and Windows
# --------------------------------------------------------------------------

@pytest.mark.parametrize('has_constant', [True, False])
def test_macos_asks_the_descriptor_for_its_path(game_dir, monkeypatch, has_constant):
    (game_dir / 'a.bin').write_bytes(GAME)
    expected = os.path.realpath(game_dir / 'a.bin')
    calls = []

    def fake_fcntl(fd, command, buffer):
        calls.append((command, len(buffer)))
        path = os.fsencode(expected)
        return path + b'\0' * (len(buffer) - len(path))

    fake = types.SimpleNamespace(fcntl=fake_fcntl)
    if has_constant:
        fake.F_GETPATH = 50
    monkeypatch.setitem(sys.modules, 'fcntl', fake)
    monkeypatch.setattr(security, 'sys', types.SimpleNamespace(platform='darwin'))
    monkeypatch.setattr(security, '_path_from_proc', lambda fd: None)  # macOS has no /proc

    fd = os.open(game_dir / 'a.bin', os.O_RDONLY)
    try:
        assert security._opened_path(fd) == expected
    finally:
        os.close(fd)
    assert calls == [(50, 1024)]


def test_a_macos_descriptor_that_points_outside_is_refused(game_dir, secret, monkeypatch):
    (game_dir / 'a.bin').write_bytes(GAME)
    outside = os.fsencode(os.path.realpath(secret))
    fake = types.SimpleNamespace(
        F_GETPATH=50,
        fcntl=lambda fd, command, buffer: outside + b'\0' * (len(buffer) - len(outside)),
    )
    monkeypatch.setitem(sys.modules, 'fcntl', fake)
    monkeypatch.setattr(security, 'sys', types.SimpleNamespace(platform='darwin'))
    monkeypatch.setattr(security, '_path_from_proc', lambda fd: None)

    with pytest.raises(OSError):
        open_plain_file_within(game_dir, game_dir / 'a.bin')


def test_the_descriptor_lookups_are_inert_off_their_own_platform(game_dir):
    (game_dir / 'a.bin').write_bytes(GAME)
    fd = os.open(game_dir / 'a.bin', os.O_RDONLY)
    try:
        if sys.platform != 'darwin':
            assert security._path_from_f_getpath(fd) is None
        if os.name != 'nt':
            assert security._path_from_handle(fd) is None
    finally:
        os.close(fd)


def test_lookups_are_tried_in_order_and_none_is_the_last_answer(monkeypatch):
    monkeypatch.setattr(security, '_path_from_proc', lambda fd: None)
    monkeypatch.setattr(security, '_path_from_f_getpath', lambda fd: None)
    monkeypatch.setattr(security, '_path_from_handle', lambda fd: None)
    assert security._opened_path(3) is None
    monkeypatch.setattr(security, '_path_from_handle', lambda fd: 'handle-answer')
    assert security._opened_path(3) == 'handle-answer'
    monkeypatch.setattr(security, '_path_from_f_getpath', lambda fd: 'getpath-answer')
    assert security._opened_path(3) == 'getpath-answer'
    monkeypatch.setattr(security, '_path_from_proc', lambda fd: 'proc-answer')
    assert security._opened_path(3) == 'proc-answer'


@pytest.mark.parametrize('raw, expected', [
    (r'\\?\C:\games\Some Game\a.bin', r'C:\games\Some Game\a.bin'),
    (r'\\?\UNC\nas\share\games\a.bin', r'\\nas\share\games\a.bin'),
    (r'C:\games\a.bin', r'C:\games\a.bin'),
])
def test_windows_final_path_names_lose_their_nt_prefix(raw, expected):
    assert security._strip_nt_prefix(raw) == expected


@pytest.mark.skipif(os.name != 'nt', reason='GetFinalPathNameByHandleW is Windows-only')
def test_windows_asks_the_handle_for_a_canonical_path(game_dir):
    (game_dir / 'a.bin').write_bytes(GAME)
    fd = os.open(game_dir / 'a.bin', os.O_RDONLY | os.O_BINARY)
    try:
        located = security._opened_path(fd)
    finally:
        os.close(fd)
    assert located and not located.startswith('\\\\?\\')
    assert os.path.normcase(located) == os.path.normcase(os.path.realpath(game_dir / 'a.bin'))


def test_macos_compares_paths_the_way_its_volume_does(monkeypatch):
    """F_GETPATH reports the spelling on disk; the library root may have been typed differently."""
    base = '/Users/me/games/Caf\u00e9'
    on_disk = '/Users/me/Games/Cafe\u0301/a.bin'  # other case, decomposed accent
    assert not security._is_below(base, on_disk), 'elsewhere paths are compared exactly'

    monkeypatch.setattr(security, 'sys', types.SimpleNamespace(platform='darwin'))
    assert security._is_below(base, on_disk)
    assert not security._is_below(base, '/Users/me/Games/Other/a.bin')
    assert not security._is_below(base, '/users/me/GAMES/CAF\u00c9'), 'a folder is not within itself'


@pytest.mark.skipif(os.name != 'nt', reason='the \\\\?\\ prefix only exists on Windows')
def test_windows_compares_paths_without_the_nt_prefix():
    assert security._is_below('\\\\?\\C:\\lib\\Some Game', 'C:\\lib\\Some Game\\a.bin')
    assert security._is_below('C:\\lib\\Some Game', '\\\\?\\C:\\lib\\Some Game\\a.bin')
    assert not security._is_below('C:\\lib\\Some Game', '\\\\?\\C:\\lib\\Other\\a.bin')


def test_without_any_descriptor_path_a_parent_swapped_back_after_the_open_is_refused(tmp_path, secret, monkeypatch):
    """The last-resort check (no /proc, F_GETPATH or handle lookup) used to pass a
    parent link that was put back after ``os.stat`` and before ``realpath``."""
    base = tmp_path / 'library' / 'G'
    sub = base / 'sub'
    sub.mkdir(parents=True)
    (sub / 'secret.bin').write_bytes(b'decoy-inside')  # a real file of the same name inside
    real_sub = base / 'sub.real'
    sub.rename(real_sub)
    _link(sub, secret.parent, directory=True)  # at open time ``sub`` leads outside

    monkeypatch.setattr(security, '_opened_path', lambda fd: None)
    real_stat = os.stat
    swapped = []

    def stat_then_swap_back(path, *args, **kwargs):
        result = real_stat(path, *args, **kwargs)
        if str(path).endswith('sub/secret.bin') and not swapped:
            swapped.append(True)
            sub.unlink()
            real_sub.rename(sub)
        return result

    monkeypatch.setattr(os, 'stat', stat_then_swap_back)
    with pytest.raises(OSError):
        open_plain_file_within(base, sub / 'secret.bin')


# --------------------------------------------------------------------------
# zip dates
# --------------------------------------------------------------------------

def _collect(source, **kwargs) -> bytes:
    async def run():
        out = b''
        async for chunk in zs.async_generate_zipstream_chunks(str(source), **kwargs):
            out += chunk
        return out

    return asyncio.run(run())


@pytest.mark.parametrize('mtime, expected', [
    (0, (1980, 1, 1, 0, 0, 0)),
    (-86400, (1980, 1, 1, 0, 0, 0)),
    (-1e18, (1980, 1, 1, 0, 0, 0)),
    (1e18, (2107, 12, 31, 23, 59, 59)),
    (4_600_000_000, (2107, 12, 31, 23, 59, 59)),
])
def test_zip_date_time_is_clamped_to_what_the_format_holds(mtime, expected):
    assert zs.zip_date_time(mtime) == expected


def test_zip_date_time_keeps_an_ordinary_mtime():
    assert zs.zip_date_time(1_600_000_000) == time.localtime(1_600_000_000)[0:6]


def test_a_file_dated_before_1980_does_not_fail_the_folder_download(game_dir):
    (game_dir / 'old.bin').write_bytes(GAME)
    os.utime(game_dir / 'old.bin', (0, 0))
    (game_dir / 'new.bin').write_bytes(b'new')

    blob = _collect(game_dir)

    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        assert sorted(archive.namelist()) == ['new.bin', 'old.bin']
        assert archive.getinfo('old.bin').date_time == (1980, 1, 1, 0, 0, 0)
        assert archive.read('old.bin') == GAME
        assert archive.testzip() is None


def test_a_single_file_source_is_zipped_from_the_vetted_handle(tmp_path):
    single = tmp_path / 'library' / 'Game.nes'
    single.parent.mkdir()
    single.write_bytes(GAME)
    os.utime(single, (0, 0))

    with zipfile.ZipFile(io.BytesIO(_collect(single))) as archive:
        assert archive.namelist() == ['Game.nes']
        assert archive.read('Game.nes') == GAME
        assert archive.getinfo('Game.nes').date_time == (1980, 1, 1, 0, 0, 0)


# --------------------------------------------------------------------------
# folder download through the ASGI handler
# --------------------------------------------------------------------------

class _Wire:
    """What the ASGI handler sent."""

    def __init__(self):
        self.messages = []

    async def send(self, message):
        self.messages.append(message)

    @property
    def starts(self):
        return [m for m in self.messages if m['type'] == 'http.response.start']

    @property
    def body(self):
        return b''.join(m.get('body', b'') for m in self.messages if m['type'] == 'http.response.body')

    @property
    def finished(self):
        return any(m['type'] == 'http.response.body' and not m.get('more_body') for m in self.messages)

    def header(self, name):
        for key, value in self.starts[0]['headers']:
            if key == name:
                return value
        return None


def _lazy_app(monkeypatch, *bases):
    lazy = asgi_mod.LazyASGIApp()
    lazy._flask_app = types.SimpleNamespace(config={})
    lazy._ensure_flask = AsyncMock()
    monkeypatch.setattr(asgi_mod, 'get_allowed_base_directories', lambda _app: [str(b) for b in bases])
    return lazy


def _folder_download(game):
    return types.SimpleNamespace(file_location=str(game), game=None)


def test_a_game_folder_swapped_for_a_link_after_the_path_check_is_not_streamed(tmp_path, secret, monkeypatch):
    library = tmp_path / 'library'
    game = library / 'G'
    game.mkdir(parents=True)
    (game / 'a.bin').write_bytes(GAME)
    lazy = _lazy_app(monkeypatch, library)
    monkeypatch.setattr(zs, 'log_system_event', _quiet)
    real_check = asgi_mod.is_safe_path

    def check_then_swap(path, bases):
        verdict = real_check(path, bases)
        game.rename(library / 'G.moved')
        _link(game, secret.parent, directory=True)  # the whole folder now leads outside
        return verdict

    monkeypatch.setattr(asgi_mod, 'is_safe_path', check_then_swap)
    wire = _Wire()

    asyncio.run(lazy._handle_streaming_download(wire.send, _folder_download(game), str(game)))

    assert SECRET not in wire.body
    with zipfile.ZipFile(io.BytesIO(wire.body)) as archive:
        assert 'secret.bin' not in archive.namelist()


def _two_member_game(library: Path, secret: Path, monkeypatch) -> Path:
    """A folder whose second member becomes a link once the walk is over."""
    game = library / 'G'
    game.mkdir(parents=True)
    (game / 'a_first.bin').write_bytes(os.urandom(200 * 1024))
    (game / 'b_big.bin').write_bytes(GAME)
    real_walk = zs._iter_folder_files

    def walk_then_swap(source, excluded, **kwargs):
        found = sorted(real_walk(source, excluded, **kwargs))
        _swap_for_link(game / 'b_big.bin', secret)
        return iter(found)

    monkeypatch.setattr(zs, '_iter_folder_files', walk_then_swap)
    return game


def test_a_member_failing_mid_download_aborts_instead_of_finishing_a_corrupt_zip(tmp_path, secret, monkeypatch):
    library = tmp_path / 'library'
    game = _two_member_game(library, secret, monkeypatch)
    lazy = _lazy_app(monkeypatch, library)
    logged = []
    monkeypatch.setattr(zs, 'log_system_event', _quiet)
    monkeypatch.setattr(asgi_mod, 'log_system_event', lambda text, **_kw: logged.append(text) or True)
    wire = _Wire()

    with pytest.raises(OSError):
        asyncio.run(lazy._handle_streaming_download(wire.send, _folder_download(game), str(game)))

    assert len(wire.starts) == 1 and wire.starts[0]['status'] == 200, 'no second response is attempted'
    assert not wire.finished, 'the body is never terminated, so the client sees an incomplete transfer'
    assert wire.body.startswith(b'PK'), 'part of the archive had already gone out'
    assert SECRET not in wire.body
    assert any('aborted mid-stream' in text for text in logged)


def test_the_download_route_does_not_finish_a_response_that_already_started(tmp_path, secret, monkeypatch):
    library = tmp_path / 'library'
    game = _two_member_game(library, secret, monkeypatch)
    lazy = _lazy_app(monkeypatch, library)
    monkeypatch.setattr(zs, 'log_system_event', _quiet)
    monkeypatch.setattr(asgi_mod, 'log_system_event', _quiet)

    async def zip_download(_scope, _receive, send, _path):
        await lazy._handle_streaming_download(send, _folder_download(game), str(game))

    monkeypatch.setattr(lazy, '_handle_zip_download', zip_download)
    wire = _Wire()

    with pytest.raises(OSError):
        asyncio.run(lazy._handle_download({'path': '/download_zip/1', 'method': 'GET'}, None, wire.send))

    assert len(wire.starts) == 1
    assert not wire.finished


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def test_a_real_server_shows_the_failed_download_as_incomplete(tmp_path, secret, monkeypatch):
    uvicorn = pytest.importorskip('uvicorn')
    library = tmp_path / 'library'
    game = _two_member_game(library, secret, monkeypatch)
    lazy = _lazy_app(monkeypatch, library)
    monkeypatch.setattr(zs, 'log_system_event', _quiet)
    monkeypatch.setattr(asgi_mod, 'log_system_event', _quiet)

    async def zip_download(_scope, _receive, send, _path):
        await lazy._handle_streaming_download(send, _folder_download(game), str(game))

    monkeypatch.setattr(lazy, '_handle_zip_download', zip_download)

    async def app(scope, receive, send):
        await lazy._handle_download(scope, receive, send)

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='critical', lifespan='off'))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=15)
    try:
        connection.request('GET', '/download_zip/1')
        response = connection.getresponse()
        assert response.status == 200
        with pytest.raises(http.client.IncompleteRead):
            response.read()
    finally:
        connection.close()
        server.should_exit = True
        thread.join(10)


# --------------------------------------------------------------------------
# WebRetro ROM endpoint and single-file download, served from a descriptor
# --------------------------------------------------------------------------

def _make_game(db_session, path: Path):
    from oneirodex.models import Game, Library
    from oneirodex.platform import LibraryPlatform

    library = Library(name=f'Lib {uuid4().hex[:8]}', platform=LibraryPlatform.PCWIN, display_order=1)
    db_session.add(library)
    db_session.flush()
    game = Game(
        uuid=str(uuid4()),
        name=f'Served probe {uuid4().hex[:6]}',
        library_uuid=library.uuid,
        full_disk_path=str(path),
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


@pytest.fixture
def served(app, db_session, tmp_path, monkeypatch):
    """A library root, a member and an ASGI app wired to them."""
    root = tmp_path / 'library'
    root.mkdir()
    monkeypatch.setitem(app.config, 'DATA_FOLDER_GAMES', str(root))
    monkeypatch.setenv('ONEIRODEX_LIBRARY_DIR', str(tmp_path / 'runtime'))
    user = _make_admin(db_session)
    lazy = asgi_mod.LazyASGIApp()
    lazy._flask_app = app
    lazy._ensure_flask = AsyncMock()
    lazy._get_user_id = AsyncMock(return_value=user.id)
    monkeypatch.setattr(asgi_mod, 'log_system_event', _quiet)
    return types.SimpleNamespace(root=root, user=user, lazy=lazy, db=db_session, tmp=tmp_path)


def _get_rom(served, game) -> _Wire:
    wire = _Wire()
    path = f'/api/downloadrom/{game.uuid}'
    asyncio.run(served.lazy._handle_rom_download({'path': path}, None, wire.send, path))
    return wire


def _status(wire: _Wire) -> int:
    return wire.starts[0]['status']


def test_rom_endpoint_serves_a_folder_rom_with_its_size_and_name(served):
    folder = served.root / 'Rom Game'
    folder.mkdir()
    (folder / 'game.nes').write_bytes(GAME)
    game = _make_game(served.db, folder)

    wire = _get_rom(served, game)

    assert _status(wire) == 200
    assert wire.body == GAME
    assert wire.header(b'content-length') == str(len(GAME)).encode()
    assert b'game.nes' in wire.header(b'content-disposition')
    assert wire.finished


def test_rom_endpoint_serves_what_was_vetted_when_the_file_is_swapped_while_logging(served, secret, monkeypatch):
    folder = served.root / 'Rom Game'
    folder.mkdir()
    (folder / 'game.nes').write_bytes(GAME)
    game = _make_game(served.db, folder)

    def log_then_swap(text, **_kw):
        if text.startswith('ROM file downloaded'):
            _swap_for_link(folder / 'game.nes', secret)  # the window the old code left open
        return True

    monkeypatch.setattr(asgi_mod, 'log_system_event', log_then_swap)
    wire = _get_rom(served, game)

    assert _status(wire) == 200
    assert SECRET not in wire.body
    assert wire.body == GAME, 'the descriptor opened before the swap is what is streamed'


def test_rom_endpoint_refuses_a_file_swapped_between_resolve_and_open(served, secret, monkeypatch):
    folder = served.root / 'Rom Game'
    folder.mkdir()
    (folder / 'game.nes').write_bytes(GAME)
    game = _make_game(served.db, folder)
    real_resolve = asgi_mod.resolve_playable_rom_path

    def resolve_then_swap(*args, **kwargs):
        resolved = real_resolve(*args, **kwargs)
        _swap_for_link(folder / 'game.nes', secret)
        return resolved

    monkeypatch.setattr(asgi_mod, 'resolve_playable_rom_path', resolve_then_swap)
    wire = _get_rom(served, game)

    assert _status(wire) == 403
    assert SECRET not in wire.body


def test_rom_endpoint_refuses_a_game_folder_swapped_after_the_path_check(served, secret, monkeypatch):
    folder = served.root / 'Rom Game'
    folder.mkdir()
    (folder / 'game.nes').write_bytes(GAME)
    game = _make_game(served.db, folder)
    elsewhere = served.tmp / 'elsewhere'
    elsewhere.mkdir()
    (elsewhere / 'game.nes').write_bytes(SECRET)  # a ROM the folder never held
    real_check = asgi_mod.is_safe_path

    def check_then_swap(path, bases):
        verdict = real_check(path, bases)
        folder.rename(served.root / 'Rom Game.moved')
        _link(folder, elsewhere, directory=True)
        return verdict

    monkeypatch.setattr(asgi_mod, 'is_safe_path', check_then_swap)
    wire = _get_rom(served, game)

    assert _status(wire) == 403
    assert SECRET not in wire.body


def test_rom_endpoint_still_serves_a_game_that_is_a_link_to_a_file_in_the_library(served):
    store = served.root / 'store'
    store.mkdir()
    (store / 'abc123.bin').write_bytes(GAME)
    linked = served.root / 'Linked Game.nes'
    _link(linked, store / 'abc123.bin')
    game = _make_game(served.db, linked)

    wire = _get_rom(served, game)

    assert _status(wire) == 200
    assert wire.body == GAME
    assert b'Linked_Game.nes' in wire.header(b'content-disposition'), 'the extension picks the core, so the link name stays'


def test_rom_endpoint_serves_a_cue_bundle_from_the_cache(served):
    folder = served.root / 'Disc Game'
    folder.mkdir()
    (folder / 'disc.cue').write_text('FILE "disc.bin" BINARY\n  TRACK 01 MODE2/2352\n', encoding='utf-8')
    (folder / 'disc.bin').write_bytes(GAME)
    game = _make_game(served.db, folder)

    wire = _get_rom(served, game)

    assert _status(wire) == 200
    assert b'play.zip' in wire.header(b'content-disposition')
    with zipfile.ZipFile(io.BytesIO(wire.body)) as archive:
        assert sorted(archive.namelist()) == ['disc.bin', 'disc.cue']
        assert archive.read('disc.bin') == GAME


def _get_zip(served, request_id, wire=None) -> _Wire:
    wire = wire or _Wire()
    path = f'/download_zip/{request_id}'
    asyncio.run(served.lazy._handle_zip_download({'path': path}, None, wire.send, path))
    return wire


def _download_request(served, game, file_path: Path):
    from oneirodex.models import DownloadRequest

    row = DownloadRequest(
        user_id=served.user.id,
        game_uuid=game.uuid,
        status='available',
        zip_file_path=str(file_path),
        download_size=1.0,
    )
    served.db.add(row)
    served.db.commit()
    return row


def test_single_file_download_serves_the_file_with_its_size(served):
    package = served.root / 'game.7z'
    package.write_bytes(GAME)
    game = _make_game(served.db, package)

    wire = _get_zip(served, _download_request(served, game, package).id)

    assert _status(wire) == 200
    assert wire.body == GAME
    assert wire.header(b'content-length') == str(len(GAME)).encode()
    assert b'game.7z' in wire.header(b'content-disposition')


def test_single_file_download_serves_what_was_vetted_when_the_file_is_swapped_while_logging(served, secret, monkeypatch):
    package = served.root / 'game.7z'
    package.write_bytes(GAME)
    game = _make_game(served.db, package)
    request_id = _download_request(served, game, package).id

    def log_then_swap(text, **_kw):
        if text.startswith('Async file download'):
            _swap_for_link(package, secret)
        return True

    monkeypatch.setattr(asgi_mod, 'log_system_event', log_then_swap)
    wire = _get_zip(served, request_id)

    assert _status(wire) == 200
    assert SECRET not in wire.body
    assert wire.body == GAME


def test_single_file_download_that_is_swapped_before_it_is_opened_is_not_served(served, secret, monkeypatch):
    package = served.root / 'game.7z'
    package.write_bytes(GAME)
    game = _make_game(served.db, package)
    request_id = _download_request(served, game, package).id
    real_check = asgi_mod.is_safe_path

    def check_then_swap(path, bases):
        verdict = real_check(path, bases)
        _swap_for_link(package, secret)
        return verdict

    monkeypatch.setattr(asgi_mod, 'is_safe_path', check_then_swap)
    wire = _get_zip(served, request_id)

    assert _status(wire) in (403, 404)
    assert SECRET not in wire.body


def test_a_locked_or_unreadable_download_is_unavailable_not_a_security_event(served, monkeypatch):
    """A Windows sharing violation or EACCES is not a link or an escape: it was
    logged as a security violation with a 403."""
    import errno

    package = served.root / 'game.7z'
    package.write_bytes(GAME)
    game = _make_game(served.db, package)
    request_id = _download_request(served, game, package).id
    events = []
    monkeypatch.setattr(asgi_mod, 'log_system_event', lambda msg, **kw: events.append((msg, kw)))

    def locked(*args, **kwargs):
        raise PermissionError(errno.EACCES, 'Permission denied')

    monkeypatch.setattr(asgi_mod, 'open_plain_file_within', locked)
    assert _status(_get_zip(served, request_id)) == 503
    assert not any(kw.get('event_type') == 'security' for _, kw in events)


def test_the_helpers_own_refusals_are_still_security_events():
    import errno

    assert asgi_mod._is_link_or_escape_refusal(OSError(errno.ELOOP, 'path no longer names the file that was opened'))
    assert asgi_mod._is_link_or_escape_refusal(OSError(errno.EINVAL, 'not a regular file'))
    assert asgi_mod._is_link_or_escape_refusal(OSError(errno.EACCES, 'file is outside its folder'))
    assert not asgi_mod._is_link_or_escape_refusal(PermissionError(errno.EACCES, 'Permission denied'))
    assert not asgi_mod._is_link_or_escape_refusal(OSError(errno.EIO, 'Input/output error'))


def test_a_client_closing_a_download_is_not_logged_as_an_error(served, monkeypatch):
    package = served.root / 'game.7z'
    package.write_bytes(b'x' * (5 * 1024 * 1024))
    game = _make_game(served.db, package)
    request_id = _download_request(served, game, package).id
    events = []
    monkeypatch.setattr(asgi_mod, 'log_system_event', lambda msg, **kw: events.append((msg, kw)))

    class GoneWire(_Wire):
        async def send(self, message):
            if message['type'] == 'http.response.body' and self.messages:
                raise ConnectionResetError('client went away')
            await super().send(message)

    with pytest.raises(ConnectionResetError):
        _get_zip(served, request_id, wire=GoneWire())
    levels = [kw.get('event_level') for msg, kw in events if 'ended early' in msg]
    assert levels == ['information']
    assert not any(kw.get('event_level') == 'error' for _, kw in events)


def test_single_file_download_of_a_missing_file_is_a_404(served):
    package = served.root / 'gone.7z'
    game = _make_game(served.db, package)

    assert _status(_get_zip(served, _download_request(served, game, package).id)) == 404


def test_a_file_that_shrinks_mid_download_aborts_instead_of_ending_short_and_clean(served):
    package = served.root / 'game.7z'
    package.write_bytes(b'x' * (5 * 1024 * 1024))  # several body messages
    game = _make_game(served.db, package)
    request_id = _download_request(served, game, package).id

    class ShrinkingWire(_Wire):
        shrunk = False

        async def send(self, message):
            await super().send(message)
            if message['type'] == 'http.response.body' and message.get('more_body') and not self.shrunk:
                self.shrunk = True
                os.truncate(package, 0)  # the announced length can no longer be met

    wire = ShrinkingWire()
    path = f'/download_zip/{request_id}'

    with pytest.raises(OSError):
        asyncio.run(served.lazy._handle_zip_download({'path': path}, None, wire.send, path))

    assert len(wire.starts) == 1, 'no second response is attempted'
    assert not wire.finished, 'a body shorter than its content-length is never ended as if it were whole'


# --------------------------------------------------------------------------
# cue bundle
# --------------------------------------------------------------------------

def _cue_folder(folder: Path) -> Path:
    folder.mkdir(parents=True)
    cue = folder / 'game.cue'
    cue.write_text('FILE "track01.bin" BINARY\n  TRACK 01 MODE2/2352\n', encoding='utf-8')
    (folder / 'track01.bin').write_bytes(GAME)
    return cue


def test_a_companion_swapped_for_a_link_after_listing_is_not_bundled(tmp_path, secret, monkeypatch):
    from oneirodex.utils import rom_archive_zip as bundler

    cue = _cue_folder(tmp_path / 'library' / 'Disc')
    real_check = bundler.is_plain_file_within

    def check_then_swap(base, candidate, **kwargs):
        verdict = real_check(base, candidate, **kwargs)
        if verdict and str(candidate).endswith('track01.bin'):
            _swap_for_link(Path(candidate), secret)
        return verdict

    monkeypatch.setattr(bundler, 'is_plain_file_within', check_then_swap)
    cache = tmp_path / 'cache'

    with pytest.raises(ArchiveRomError):
        bundle_playable_rom_zip(str(cue), str(cache))

    assert not (cache / 'play.zip').exists()
    assert not list(cache.glob('play.zip*')), 'no half-built bundle is left behind'


def test_a_cue_bundle_resolves_the_disc_folder_once(tmp_path, secret):
    cue = _cue_folder(tmp_path / 'library' / 'Disc')
    real_root = os.path.realpath(cue.parent)
    (secret.parent / 'game.cue').write_text('FILE "track01.bin" BINARY\n', encoding='utf-8')
    (secret.parent / 'track01.bin').write_bytes(SECRET)
    cue.parent.rename(cue.parent.with_name('Disc.moved'))
    _link(cue.parent, secret.parent, directory=True)  # the folder now leads outside
    cache = tmp_path / 'cache'

    rom_path, name = bundle_playable_rom_zip(str(cue), str(cache), root=real_root)

    assert (rom_path, name) == (str(cue), 'game.cue'), 'nothing under the swapped-in folder is bundled'
    assert not (cache / 'play.zip').exists()


def test_a_cue_bundle_clamps_a_pre_1980_companion_date(tmp_path):
    cue = _cue_folder(tmp_path / 'library' / 'Disc')
    os.utime(cue.parent / 'track01.bin', (0, 0))

    zip_path, name = bundle_playable_rom_zip(str(cue), str(tmp_path / 'cache'))

    assert name == 'play.zip'
    with zipfile.ZipFile(zip_path) as archive:
        assert archive.getinfo('track01.bin').date_time == (1980, 1, 1, 0, 0, 0)
        assert archive.read('track01.bin') == GAME
        assert archive.read('game.cue') == b'FILE "track01.bin" BINARY\n  TRACK 01 MODE2/2352\n'
        assert archive.testzip() is None


# --------------------------------------------------------------------------
# local cover / screenshot route
# --------------------------------------------------------------------------

def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.get_id())
        sess['_fresh'] = True


@pytest.fixture
def cover_game(client, app, db_session, tmp_path, monkeypatch):
    library_root = tmp_path / 'library'
    folder = library_root / 'Cover Game'
    folder.mkdir(parents=True)
    monkeypatch.setitem(app.config, 'DATA_FOLDER_GAMES', str(library_root))
    (folder / 'cover.jpg').write_bytes(b'\xff\xd8REAL-COVER')
    game = _make_game(db_session, folder)
    _login(client, _make_admin(db_session))
    return types.SimpleNamespace(folder=folder, game=game, library_root=library_root)


def test_local_cover_is_served_with_its_size_and_validators(client, cover_game):
    response = client.get(f'/game/{cover_game.game.uuid}/local_image/cover')
    data = response.data
    response.close()

    assert response.status_code == 200
    assert data == b'\xff\xd8REAL-COVER'
    assert response.headers['Content-Type'].startswith('image/jpeg')
    assert response.headers['Content-Length'] == str(len(b'\xff\xd8REAL-COVER'))
    assert response.headers['ETag'] and response.headers['Last-Modified']
    again = client.get(
        f'/game/{cover_game.game.uuid}/local_image/cover',
        headers={'If-None-Match': response.headers['ETag']},
    )
    again.close()
    assert again.status_code == 304


def test_local_cover_honours_a_range_request(client, cover_game):
    """send_file only serves ranges from a file object when told its size."""
    response = client.get(f'/game/{cover_game.game.uuid}/local_image/cover', headers={'Range': 'bytes=2-5'})
    data = response.data
    response.close()
    assert response.status_code == 206
    assert data == b'REAL'
    assert response.headers['Content-Range'] == f'bytes 2-5/{len(b"""\xff\xd8REAL-COVER""")}'


def test_local_cover_serves_what_was_vetted_when_the_file_is_swapped_while_logging(client, cover_game, secret, monkeypatch):
    from oneirodex.routes_games_ext import details

    real_log = details.log_system_event

    def log_then_swap(text, *args, **kwargs):
        if text.startswith('Serving local'):
            _swap_for_link(cover_game.folder / 'cover.jpg', secret)  # after the old is_plain_file_within check
        return real_log(text, *args, **kwargs)

    monkeypatch.setattr(details, 'log_system_event', log_then_swap)
    response = client.get(f'/game/{cover_game.game.uuid}/local_image/cover')
    data = response.data
    response.close()

    assert response.status_code == 200
    assert SECRET not in data
    assert data == b'\xff\xd8REAL-COVER'


def test_local_cover_of_a_game_folder_swapped_after_the_path_check_is_not_served(client, cover_game, secret, monkeypatch):
    from oneirodex.routes_games_ext import details

    (secret.parent / 'cover.jpg').write_bytes(SECRET)  # a cover the folder never held
    real_check = details.is_safe_path

    def check_then_swap(path, bases):
        verdict = real_check(path, bases)
        cover_game.folder.rename(cover_game.library_root / 'Cover Game.moved')
        _link(cover_game.folder, secret.parent, directory=True)
        return verdict

    monkeypatch.setattr(details, 'is_safe_path', check_then_swap)
    response = client.get(f'/game/{cover_game.game.uuid}/local_image/cover')

    assert SECRET not in response.data
    assert response.status_code in (403, 404)
