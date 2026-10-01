"""Standalone launcher (DESK-04 / ADR 0011): pure logic, no PostgreSQL needed.

The end-to-end run (initdb, health, crash restart, clean stop, second start)
is ``scripts/spikes/desk03/run_proof_d.sh``.
"""
import json
import os
import socket
import stat
import sys
from pathlib import Path

import pytest

from oneirodex_standalone import launcher
from oneirodex_standalone.postgres import EXE, BundleError, BundledPostgres, find_bin_dir


def _bundle(root, layout):
    bin_dir = root / 'bin' if layout == 'flat' else root / 'usr' / 'lib' / 'postgresql' / '17' / 'bin'
    bin_dir.mkdir(parents=True)
    for tool in ('postgres', 'initdb', 'pg_ctl'):
        (bin_dir / f'{tool}{EXE}').write_text('')
    return bin_dir


@pytest.mark.parametrize('layout', ['flat', 'debian'])
def test_finds_the_server_binaries_in_either_bundle_layout(tmp_path, layout):
    bin_dir = _bundle(tmp_path, layout)
    assert find_bin_dir(tmp_path) == bin_dir


def test_a_bundle_without_the_server_is_refused(tmp_path):
    (tmp_path / 'bin').mkdir()
    (tmp_path / 'bin' / f'psql{EXE}').write_text('')
    with pytest.raises(BundleError):
        find_bin_dir(tmp_path)


def test_first_run_creates_secrets_once_and_keeps_them(tmp_path):
    state = launcher.load_state(tmp_path)
    assert len(state['db_password']) >= 24 and len(state['secret_key']) >= 48 and state['db_port'] > 0
    assert launcher.load_state(tmp_path) == state
    if os.name != 'nt':
        assert stat.S_IMODE((tmp_path / launcher.STATE_FILE).stat().st_mode) == 0o600


def test_a_saved_port_taken_by_something_else_is_replaced(tmp_path):
    with socket.socket() as busy:
        busy.bind(('127.0.0.1', 0))
        busy.listen()
        port = busy.getsockname()[1]
        (tmp_path / launcher.STATE_FILE).write_text(json.dumps({'db_password': 'p' * 24, 'secret_key': 'k' * 48, 'db_port': port}))
        assert launcher.load_state(tmp_path)['db_port'] != port
        # ...but not when it is our own cluster that holds it.
        (tmp_path / launcher.STATE_FILE).write_text(json.dumps({'db_password': 'p' * 24, 'secret_key': 'k' * 48, 'db_port': port}))
        (tmp_path / 'pgdata').mkdir()
        (tmp_path / 'pgdata' / 'postmaster.pid').write_text(f'123\n{tmp_path}\n1790000000\n{port}\n')
        assert launcher.load_state(tmp_path)['db_port'] == port


def _pg(tmp_path, **kw):
    return BundledPostgres(pg_home=tmp_path, data_dir=tmp_path / 'pgdata', log_file=tmp_path / 'pg.log',
                           port=kw.get('port', 54999), password=kw.get('password', 'p@ss/word:1'))


def test_the_server_gets_a_local_url_and_http_cookies(tmp_path):
    env = launcher.server_env(_pg(tmp_path), {'secret_key': 'k' * 48}, tmp_path)
    assert env['DATABASE_URL'] == 'postgresql://oneirodex:p%40ss%2Fword%3A1@127.0.0.1:54999/oneirodex'
    assert env['ONEIRODEX_LIBRARY_DIR'] == str(tmp_path / 'library'), 'writes go to the data folder'
    assert env['SECRET_KEY'] == 'k' * 48
    assert env['SESSION_COOKIE_SECURE'] == 'false' and env['REMEMBER_COOKIE_SECURE'] == 'false'
    assert launcher.server_command(5006)[-6:] == ['--host', '127.0.0.1', '--port', '5006', '--workers', '1']
    assert 'run_complete_startup_initialization' in launcher.init_command()[-1]


def test_database_process_listens_on_loopback_only(tmp_path):
    _bundle(tmp_path, 'flat')
    args = _pg(tmp_path).server_args()
    assert 'listen_addresses=127.0.0.1' in args and 'port=54999' in args
    if os.name != 'nt':
        assert 'unix_socket_directories=' in args


def test_bundle_env_drops_stray_libpq_settings_and_adds_bundled_libs(tmp_path, monkeypatch):
    (tmp_path / 'libs').mkdir()
    for key in ('PGHOST', 'PGPASSWORD', 'PGDATA'):
        monkeypatch.setenv(key, 'x')
    monkeypatch.setattr(sys, 'platform', 'linux')
    env = _pg(tmp_path).env()
    assert not {'PGHOST', 'PGPASSWORD', 'PGDATA'} & set(env)
    assert env['LD_LIBRARY_PATH'].split(os.pathsep)[0] == str(tmp_path / 'libs')


class _FakeServer:
    def __init__(self, code=None):
        self.code = code

    def poll(self):
        return self.code


class _FakePg:
    def __init__(self, up=True):
        self.up, self.starts = up, 0

    def running(self):
        return self.up

    def start(self):
        self.starts += 1
        self.up = True


def test_supervisor_restarts_the_database_and_gives_up_when_it_keeps_dying():
    now = [0.0]
    pg = _FakePg(up=False)
    sup = launcher.Supervisor(pg, _FakeServer(), clock=lambda: now[0])
    assert sup.tick() is None and pg.starts == 1
    for _ in range(launcher.MAX_RESTARTS - 1):
        now[0] += 1
        pg.up = False
        assert sup.tick() is None
    now[0] += 1
    pg.up = False
    assert sup.tick() == 1, 'more than MAX_RESTARTS inside the window stops everything'


def test_old_restarts_age_out_of_the_window():
    now = [0.0]
    pg = _FakePg(up=False)
    sup = launcher.Supervisor(pg, _FakeServer(), clock=lambda: now[0])
    for _ in range(launcher.MAX_RESTARTS * 3):
        now[0] += launcher.RESTART_WINDOW / 2
        pg.up = False
        assert sup.tick() is None


def test_supervisor_stops_when_the_server_exits():
    assert launcher.Supervisor(_FakePg(), _FakeServer(code=4)).tick() == 4


# --- secrets are owner-only from the first byte (LOW: written before chmod) ---

posix_only = pytest.mark.skipif(os.name == 'nt', reason='POSIX permission bits')


def _mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


@pytest.fixture
def open_umask():
    """umask 0: a plain write_text would now produce a world-readable 0666 file."""
    previous = os.umask(0)
    yield
    os.umask(previous)


@posix_only
def test_private_file_is_created_0600_atomically_not_chmoded_afterwards(tmp_path, open_umask, monkeypatch):
    from oneirodex_standalone.postgres import write_private_text

    seen = {}
    real_open = os.open

    def spy(path, flags, mode=0o777, *args, **kwargs):
        seen.update(flags=flags, mode=mode)
        return real_open(path, flags, mode, *args, **kwargs)

    monkeypatch.setattr(os, 'open', spy)
    target = tmp_path / 'secret.txt'
    write_private_text(target, 'hunter2\n')
    assert seen['mode'] == 0o600 and seen['flags'] & os.O_EXCL and seen['flags'] & os.O_CREAT
    assert _mode(target) == 0o600
    assert target.read_text(encoding='utf-8') == 'hunter2\n'


@posix_only
def test_private_write_replaces_a_stale_loose_file_and_ignores_a_planted_link(tmp_path, open_umask):
    from oneirodex_standalone.postgres import write_private_text

    stale = tmp_path / 'stale.tmp'
    stale.write_text('old')
    os.chmod(stale, 0o666)
    write_private_text(stale, 'new')
    assert _mode(stale) == 0o600 and stale.read_text() == 'new'

    victim = tmp_path / 'victim.txt'
    victim.write_text('precious')
    planted = tmp_path / 'planted.tmp'
    os.symlink(victim, planted)
    write_private_text(planted, 'secret')
    assert victim.read_text() == 'precious', 'the write did not follow the link'
    assert not planted.is_symlink() and _mode(planted) == 0o600


def test_private_write_round_trips_on_every_platform(tmp_path):
    from oneirodex_standalone.postgres import write_private_text

    target = tmp_path / 'x.json'
    write_private_text(target, '{"a": 1}')
    assert json.loads(target.read_text(encoding='utf-8')) == {'a': 1}


@posix_only
def test_new_data_folder_is_0700_and_the_state_file_0600(tmp_path, open_umask):
    root = tmp_path / 'oneirodex-data'
    state = launcher.load_state(root)
    assert state['db_password']
    assert _mode(root) == 0o700
    assert _mode(root / launcher.STATE_FILE) == 0o600
    assert sorted(p.name for p in root.iterdir()) == [launcher.STATE_FILE], 'no leftover .tmp file'


@posix_only
def test_an_existing_data_folder_keeps_its_mode_but_the_secrets_stay_private(tmp_path, open_umask):
    root = tmp_path / 'shared-data'
    root.mkdir()
    os.chmod(root, 0o755)
    launcher.load_state(root)
    assert _mode(root) == 0o755, 'a folder the user chose is not re-permissioned'
    assert _mode(root / launcher.STATE_FILE) == 0o600


@posix_only
def test_initdb_password_file_is_private_while_initdb_reads_it(tmp_path, open_umask, monkeypatch):
    import subprocess

    _bundle(tmp_path, 'flat')
    pg = BundledPostgres(pg_home=tmp_path, data_dir=tmp_path / 'fresh' / 'pgdata', log_file=tmp_path / 'pg.log',
                         port=54999, password='s3cret-pw')
    seen = {}

    def fake_run(self, args, **kwargs):
        pwfile = next(a.split('=', 1)[1] for a in args if str(a).startswith('--pwfile='))
        seen.update(mode=_mode(pwfile), text=Path(pwfile).read_text(encoding='utf-8'), parent_mode=_mode(tmp_path / 'fresh'))
        seen['path'] = pwfile
        return subprocess.CompletedProcess(args, 0, stdout='', stderr='')

    monkeypatch.setattr(BundledPostgres, '_run', fake_run)
    pg.init()
    assert seen['mode'] == 0o600
    assert seen['text'].strip() == 's3cret-pw'
    assert seen['parent_mode'] == 0o700, 'the folder that holds pgdata is created owner-only'
    assert not os.path.exists(seen['path']), 'the password file is removed once initdb is done'
