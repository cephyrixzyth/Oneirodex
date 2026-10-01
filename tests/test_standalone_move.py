"""Household move command (DESK-05): the parts that need no database.

The whole move (export from a real standalone install, import into an empty
server database, re-keyed saves, cross-OS paths, every refusal) is
``scripts/spikes/desk03/run_proof_e.sh``.
"""
import json
import os
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from oneirodex_standalone import move
from oneirodex_standalone.move import SAVE_MAGIC, Refused, UsageError


def _library(tmp_path):
    lib = tmp_path / 'library'
    for rel, body in {
        'images/a_cover.jpg': b'art',
        'generated/pack/tile.webp': b'gen',
        'saves/1/g/slot1.sav': b'plain-save',
        'chat-attachments/x.png': b'chat',
        'themes/default/theme.json': b'{}',
        'themes/ocean/theme.json': json.dumps({move.PRESET_MARKER_KEY: {'slug': 'ocean'}}).encode(),
        'themes/mine/theme.json': b'{"name": "Mine"}',
        'themes/mine/css/base.css': b':root{}',
        'icon-themes/soft/manifest.json': b'{}',
        'fonts/x.ttf': b'font',
        'anticheat/games.json': b'{}',
    }.items():
        path = lib / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    return lib


def test_only_members_files_travel(tmp_path):
    carried = {p.as_posix() for p in move.carried_files(_library(tmp_path))}
    assert carried == {
        'images/a_cover.jpg', 'generated/pack/tile.webp', 'saves/1/g/slot1.sav', 'chat-attachments/x.png',
        'themes/mine/theme.json', 'themes/mine/css/base.css',
    }, 'the default theme, generated presets, icon packs, fonts and caches are rebuilt by the server'


def test_the_save_key_matches_the_apps_own(app):
    from oneirodex.utils import save_crypto

    with app.app_context():
        token = save_crypto._fernet().encrypt(b'x')
        assert Fernet(move.save_key_for(app.config['SECRET_KEY']).encode()).decrypt(token) == b'x'


def _encrypt(path: Path, key: str):
    path.write_bytes(SAVE_MAGIC + Fernet(key.encode()).encrypt(path.read_bytes()))


def test_encrypted_saves_are_recorded_by_content_and_rekeyed_for_the_server(tmp_path):
    lib = _library(tmp_path)
    source, server = move.save_key_for('standalone-secret'), move.save_key_for('server-secret')
    _encrypt(lib / 'saves/1/g/slot1.sav', source)
    files = move.snapshot_files(lib, source)
    entry = next(e for e in files if e['path'] == 'saves/1/g/slot1.sav')
    assert entry['plain_sha256'] == move._sha256(b'plain-save')
    assert not any('plain_sha256' in e for e in files if e is not entry)

    manifest = {'files': files, 'save_key': source}
    assert move.rekey_saves(lib, manifest, server) == 1
    data = (lib / 'saves/1/g/slot1.sav').read_bytes()
    assert Fernet(server.encode()).decrypt(data[len(SAVE_MAGIC):]) == b'plain-save'
    with pytest.raises(Exception):
        Fernet(source.encode()).decrypt(data[len(SAVE_MAGIC):])
    assert move.rekey_saves(lib, {'files': files, 'save_key': server}, server) == 0, 'same key: nothing to do'




def _bundle(tmp_path):
    """A move folder as export writes it; returns (folder, manifest, fingerprint)."""
    lib = _library(tmp_path)
    bundle = tmp_path / 'move'
    files = move.snapshot_files(lib, None)
    for entry in files:
        target = bundle / 'files' / entry['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((lib / entry['path']).read_bytes())
    (bundle / 'db.dump').write_bytes(b'dump')
    manifest = {'format': move.FORMAT, 'roots': {'library': str(lib)}, 'files': files,
                'db_dump': {'sha256': move._sha256(b'dump'), 'size': 4, 'pg_major': 17}}
    return bundle, manifest, _seal(bundle, manifest)


def _seal(bundle, manifest):
    """Write the manifest as export does; returns its fingerprint."""
    raw = json.dumps(manifest, sort_keys=True)
    (bundle / 'manifest.json').write_text(raw, encoding='utf-8')
    (bundle / 'manifest.sha256').write_text(move._sha256(raw.encode()), encoding='utf-8')
    return move._sha256(raw.encode())


def test_a_complete_bundle_passes_the_check(tmp_path):
    bundle, manifest, fingerprint = _bundle(tmp_path)
    assert move.check_bundle(bundle, fingerprint) == json.loads(json.dumps(manifest))
    assert move.check_bundle(bundle, fingerprint[:16].upper()), 'a 16-character prefix is enough'


def test_a_resealed_bundle_does_not_match_the_exported_fingerprint(tmp_path):
    bundle, manifest, fingerprint = _bundle(tmp_path)
    (bundle / 'files/images/a_cover.jpg').write_bytes(b'swapped art')
    for entry in manifest['files']:
        if entry['path'] == 'images/a_cover.jpg':
            entry['sha256'] = move._sha256(b'swapped art')
    _seal(bundle, manifest)  # self-consistent again, but not what was exported
    with pytest.raises(Refused, match='does not match the fingerprint'):
        move.check_bundle(bundle, fingerprint)
    with pytest.raises(UsageError):
        move.check_bundle(bundle, fingerprint[:8])


@pytest.mark.parametrize('planted', ['static-overrides/dist/member-app/evil.js', 'themes/default/css/base.css',
                                     'icon-themes/soft/pack.css'])
def test_the_import_accepts_only_what_export_carries(tmp_path, planted):
    bundle, manifest, _ = _bundle(tmp_path)
    (bundle / 'files' / planted).parent.mkdir(parents=True, exist_ok=True)
    (bundle / 'files' / planted).write_bytes(b'x')
    manifest['files'].append({'path': planted, 'size': 1, 'sha256': move._sha256(b'x')})
    with pytest.raises(Refused, match='never carries'):
        move.check_bundle(bundle, _seal(bundle, manifest))


@pytest.mark.parametrize('damage', ['file', 'dump', 'missing', 'manifest', 'format'])
def test_an_altered_or_incomplete_bundle_is_refused(tmp_path, damage):
    bundle, manifest, fingerprint = _bundle(tmp_path)
    if damage == 'file':
        (bundle / 'files/saves/1/g/slot1.sav').write_bytes(b'plain-savX')
    elif damage == 'dump':
        (bundle / 'db.dump').write_bytes(b'dumX')
    elif damage == 'missing':
        (bundle / 'files/images/a_cover.jpg').unlink()
    elif damage == 'manifest':
        (bundle / 'manifest.json').write_text('{}', encoding='utf-8')
    else:
        manifest['format'] = 'something-else/9'
        fingerprint = _seal(bundle, manifest)
    with pytest.raises(Refused):
        move.check_bundle(bundle, fingerprint)


@pytest.mark.parametrize('rel', ['../escape.txt', '/etc/passwd', 'images/../../escape.txt', '..\\escape.txt',
                                 'C:\\Windows\\win.ini', '\\\\attacker\\share\\x', 'images//x'])
def test_manifest_paths_cannot_leave_their_folder(tmp_path, rel):
    bundle, manifest, _ = _bundle(tmp_path)
    manifest['files'].append({'path': rel, 'size': 1, 'sha256': '0' * 64})
    with pytest.raises(Refused, match='unsafe path|never carries'):
        move.check_bundle(bundle, _seal(bundle, manifest))
    with pytest.raises(Refused, match='unsafe path'):
        move._safe_join(tmp_path, rel, 'test')


def test_existing_different_files_on_the_server_are_conflicts(tmp_path):
    bundle, manifest, _ = _bundle(tmp_path)
    server = tmp_path / 'server'
    (server / 'images').mkdir(parents=True)
    (server / 'images/a_cover.jpg').write_bytes(b'art')          # same content: fine
    (server / 'generated/pack').mkdir(parents=True)
    (server / 'generated/pack/tile.webp').write_bytes(b'other')  # different: conflict
    assert move._file_conflicts(manifest, server) == ['generated/pack/tile.webp']


def test_a_save_reencrypted_by_an_earlier_import_is_not_a_conflict(tmp_path):
    lib = _library(tmp_path)
    source, server = move.save_key_for('standalone'), move.save_key_for('server')
    _encrypt(lib / 'saves/1/g/slot1.sav', source)
    manifest = {'files': move.snapshot_files(lib, source), 'save_key': source}
    target = tmp_path / 'server'
    (target / 'saves/1/g').mkdir(parents=True)
    (target / 'saves/1/g/slot1.sav').write_bytes((lib / 'saves/1/g/slot1.sav').read_bytes())
    move.rekey_saves(target, manifest, server)  # what a first import left behind
    assert move._file_conflicts(manifest, target, server) == [], 'retrying after a rollback must work'
    assert move._file_conflicts(manifest, target, move.save_key_for('another server')) == ['saves/1/g/slot1.sav']


def test_an_undecryptable_save_stops_the_export_with_its_name(tmp_path):
    lib = _library(tmp_path)
    (lib / 'saves/1/g/slot1.sav').write_bytes(SAVE_MAGIC + b'not a token')
    with pytest.raises(Refused, match='saves/1/g/slot1.sav'):
        move.snapshot_files(lib, move.save_key_for('standalone'))


def test_a_file_swapped_after_the_check_is_not_copied(tmp_path):
    src, dest = tmp_path / 'src.bin', tmp_path / 'dest.bin'
    src.write_bytes(b'checked')
    expected = move._sha256(b'checked')
    src.write_bytes(b'swapped')
    with pytest.raises(Refused, match='changed'):
        move._copy_checked(src, dest, expected)
    assert not dest.exists() and not list(tmp_path.glob('*.moving'))
    src.write_bytes(b'checked')
    move._copy_checked(src, dest, expected)
    assert dest.read_bytes() == b'checked'


@pytest.mark.parametrize('name', ['x:y', 'games"; DROP TABLE users; --', '', '1abc'])
def test_unexpected_identifiers_are_refused_not_spliced_into_sql(name):
    with pytest.raises(Refused, match='unexpected table or column name'):
        move._quote(name)
    assert move._quote('full_disk_path') == '"full_disk_path"'


@pytest.mark.parametrize('rel, carried', [
    ('images/a.jpg', True), ('saves/1/g/s.sav', True), ('themes/mine/theme.json', True),
    ('themes/default/x.css', False), ('themes/mine', False), ('static-overrides/dist/x.js', False),
    ('fonts/x.ttf', False), ('images', False)])
def test_carried_paths(rel, carried):
    assert move.is_carried_path(rel) is carried


def test_the_database_password_goes_through_the_environment(monkeypatch):
    monkeypatch.setenv('PGPASSFILE', '/somewhere')
    env = move._libpq_env('postgresql://mover:p%40ss%3Aword@db.lan:5433/oneirodex_moved?sslmode=require')
    assert (env['PGHOST'], env['PGPORT'], env['PGUSER'], env['PGDATABASE']) == ('db.lan', '5433', 'mover', 'oneirodex_moved')
    assert env['PGPASSWORD'] == 'p@ss:word' and env['PGSSLMODE'] == 'require'
    assert 'PGPASSFILE' not in env, 'stray libpq settings from the environment are dropped'


def test_socket_and_certificate_settings_reach_pg_restore():
    env = move._libpq_env('postgresql://u:p@/moved?host=/run/postgresql&port=6543&sslrootcert=/certs/ca.pem')
    assert (env['PGHOST'], env['PGPORT'], env['PGSSLROOTCERT']) == ('/run/postgresql', '6543', '/certs/ca.pem')


@pytest.mark.parametrize('path, windows', [
    ('C:\\Games', True), ('d:/games', True), ('\\\\nas\\roms', True), ('/mnt/user/games', False), ('games', False)])
def test_windows_paths_are_recognised(path, windows):
    assert move.is_windows_path(path) is windows


@pytest.mark.parametrize('value, absolute', [
    ('/mnt/games/x', True), ('C:\\Games\\x', True), ('c:/games', True), ('\\\\nas\\roms', True),
    ('extras', False), ('library/images/avatars_users/a.png', False), ('', False)])
def test_only_absolute_paths_count_as_left_behind(value, absolute):
    import re
    assert bool(re.match(move.ABSOLUTE_PATH_RE, value)) is absolute


def test_root_names_are_checked():
    with pytest.raises(UsageError):
        move._pairs(['games'])
    with pytest.raises(UsageError, match='set for you'):
        move._pairs(['library=/x'])
    assert move._pairs(['games=C:\\Games\\', 'roms=/mnt/roms/']) == {'games': 'C:\\Games', 'roms': '/mnt/roms'}, \
        'a trailing separator must not change which rows match'
    for whole_disk in ('/', 'C:\\', 'd:/'):
        with pytest.raises(UsageError, match='name a folder'):
            move._pairs([f'games={whole_disk}'])


def test_a_pg_restore_older_than_the_dump_is_refused(tmp_path, monkeypatch):
    tool = tmp_path / ('pg_restore.exe' if os.name == 'nt' else 'pg_restore')
    tool.write_text('')

    class _Done:
        stdout = 'pg_restore (PostgreSQL) 16.4'
        stderr = ''
        returncode = 0

    monkeypatch.setattr(move.subprocess, 'run', lambda *a, **k: _Done())
    with pytest.raises(Refused, match='cannot read a PostgreSQL 17 dump'):
        move.restore('postgresql://u:p@h/db', tmp_path / 'db.dump', str(tmp_path), 17)


def test_export_refuses_without_an_install_or_into_a_used_folder(tmp_path):
    args = type('A', (), {'data_dir': tmp_path / 'nothing', 'to': str(tmp_path / 'out'), 'pg_home': tmp_path, 'root': None})
    with pytest.raises(Refused, match='no standalone install'):
        move.export(args)
    (tmp_path / 'nothing').mkdir()
    (tmp_path / 'nothing' / 'standalone.json').write_text('{}')
    (tmp_path / 'out').mkdir()
    (tmp_path / 'out' / 'keep.txt').write_text('mine')
    with pytest.raises(Refused, match='new or empty'):
        move.export(args)
    assert (tmp_path / 'out' / 'keep.txt').read_text() == 'mine'


def test_cli_refusals_exit_1_and_usage_errors_exit_2(tmp_path, capsys):
    assert move.main(['import', str(tmp_path / 'not-a-bundle'), '--expect', '0123456789abcdef']) == 1
    assert 'REFUSED' in capsys.readouterr().err
    bundle, _, fingerprint = _bundle(tmp_path)
    assert move.main(['import', str(bundle), '--expect', fingerprint, '--root', 'nameless']) == 2
    assert move.main(['import', str(bundle), '--expect', 'abc']) == 2
    with pytest.raises(SystemExit) as exc:
        move.main(['import', str(bundle)])  # --expect is required
    assert exc.value.code == 2
