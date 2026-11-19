import hashlib
import json
from pathlib import Path

import pytest

from oneirodex_standalone.backup import (
    Refused,
    finalize_backup_manifest,
    verify_complete_backup,
)


def _move_bundle(tmp_path: Path) -> tuple[Path, Path]:
    bundle = tmp_path / 'backup'
    data_dir = tmp_path / 'data'
    (bundle / 'files' / 'saves' / 'generation-12').mkdir(parents=True)
    (data_dir / 'pgdata').mkdir(parents=True)
    (data_dir / 'pgdata' / 'PG_VERSION').write_text('17\n', encoding='ascii')
    dump = b'synthetic-postgres-dump'
    save = b'synthetic-save-generation'
    (bundle / 'db.dump').write_bytes(dump)
    save_path = bundle / 'files' / 'saves' / 'generation-12' / 'slot.sav'
    save_path.write_bytes(save)
    manifest = {
        'format': 'oneirodex-household-move/2',
        'db': {
            'alembic_revision': 'revision-test',
            'tables': {
                'emulator_saves': {'rows': 1, 'md5': 'save-row-digest'},
                'emulator_save_generations': {'rows': 1, 'md5': 'history-row-digest'},
            },
        },
        'db_dump': {'size': len(dump), 'sha256': hashlib.sha256(dump).hexdigest(), 'pg_major': 17},
        'files': [{
            'path': 'saves/generation-12/slot.sav', 'size': len(save),
            'sha256': hashlib.sha256(save).hexdigest(),
        }],
        'required_save_key_ids': ['save-key-1'],
    }
    (bundle / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    return bundle, data_dir


def test_completed_backup_binds_manifest_dump_and_save_generations(tmp_path):
    bundle, data_dir = _move_bundle(tmp_path)

    fingerprint = finalize_backup_manifest(
        bundle, data_dir=data_dir, source_commit='a' * 40,
        created_at='2026-11-07T12:00:00+00:00',
    )
    manifest = verify_complete_backup(bundle)

    assert fingerprint == (bundle / 'manifest.sha256').read_text(encoding='ascii').strip()
    assert manifest['backup']['format'] == 'oneirodex-standalone-backup/2'
    assert manifest['backup']['source_commit'] == 'a' * 40
    assert manifest['backup']['postgresql_major'] == 17
    assert manifest['backup']['schema_revision'] == 'revision-test'
    assert manifest['backup']['save_generation_identity']['emulator_save_generations']['rows'] == 1
    assert 'operator credential and save keyring material' in manifest['backup']['excluded']
    assert b'save-key-1' not in (bundle / 'backup.complete.json').read_bytes()


@pytest.mark.parametrize('tamper', ['dump', 'file', 'manifest', 'completion'])
def test_incomplete_or_changed_backup_is_rejected(tmp_path, tamper):
    bundle, data_dir = _move_bundle(tmp_path)
    finalize_backup_manifest(bundle, data_dir=data_dir, source_commit=None)
    target = {
        'dump': bundle / 'db.dump',
        'file': bundle / 'files' / 'saves' / 'generation-12' / 'slot.sav',
        'manifest': bundle / 'manifest.json',
        'completion': bundle / 'backup.complete.json',
    }[tamper]
    target.write_bytes(target.read_bytes() + b'changed')

    with pytest.raises(Refused):
        verify_complete_backup(bundle)


def test_backup_without_completion_marker_is_not_a_restorable_backup(tmp_path):
    bundle, data_dir = _move_bundle(tmp_path)
    finalize_backup_manifest(bundle, data_dir=data_dir)
    (bundle / 'backup.complete.json').unlink()

    with pytest.raises(Refused, match='incomplete or unreadable'):
        verify_complete_backup(bundle)


def test_legacy_v1_backup_remains_restorable(tmp_path):
    bundle, data_dir = _move_bundle(tmp_path)
    finalize_backup_manifest(bundle, data_dir=data_dir)
    manifest_path = bundle / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest['backup']['format'] = 'oneirodex-standalone-backup/1'
    raw = json.dumps(manifest, indent=2, sort_keys=True) + '\n'
    manifest_path.write_text(raw, encoding='utf-8')
    fingerprint = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    (bundle / 'manifest.sha256').write_text(fingerprint + '\n', encoding='ascii')
    (bundle / 'backup.complete.json').write_text(json.dumps({
        'format': 'oneirodex-standalone-backup-complete/1',
        'manifest_sha256': fingerprint,
    }, sort_keys=True) + '\n', encoding='utf-8')

    assert verify_complete_backup(bundle)['backup']['format'] == 'oneirodex-standalone-backup/1'


def test_backup_refuses_legacy_plaintext_credential_rows(tmp_path):
    bundle, data_dir = _move_bundle(tmp_path)
    manifest_path = bundle / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest['db']['legacy_reusable_secret_count'] = 1
    manifest_path.write_text(json.dumps(manifest), encoding='utf-8')

    with pytest.raises(Refused, match='migrate remaining reusable plaintext'):
        finalize_backup_manifest(bundle, data_dir=data_dir)


@pytest.mark.parametrize('case', ['new', 'empty', 'failed_verification', 'concurrent_writer'])
def test_backup_only_publishes_verified_staging(tmp_path, monkeypatch, case):
    from shutil import copytree
    from types import SimpleNamespace
    from oneirodex_standalone import backup

    source, data_dir = _move_bundle(tmp_path)
    destination = tmp_path / 'published'
    if case == 'empty':
        destination.mkdir()

    def capture(args):
        copytree(source, args.to)
        assert Path(args.to).parent != destination
        assert not destination.exists() or not any(destination.iterdir())
        if case == 'failed_verification':
            (Path(args.to) / 'db.dump').write_bytes(b'incomplete')
        if case == 'concurrent_writer':
            destination.mkdir()
            (destination / 'other.txt').write_text('keep')
        return 0

    monkeypatch.setattr(backup, 'export_move', capture)
    args = SimpleNamespace(to=str(destination), data_dir=data_dir, pg_home=tmp_path, root=[])
    if case in {'new', 'empty'}:
        assert backup.create(args) == 0
        assert verify_complete_backup(destination)['backup']['schema_revision'] == 'revision-test'
    else:
        with pytest.raises(Refused):
            backup.create(args)
        if case == 'concurrent_writer':
            assert (destination / 'other.txt').read_text() == 'keep'
        else:
            assert not destination.exists()
    assert not list(tmp_path.glob('.oneirodex-backup-*'))


def test_managed_save_root_alias_is_remapped_and_missing_generation_refuses(tmp_path):
    from oneirodex_standalone.move import _managed_save_paths

    library = tmp_path / 'library'
    (library / 'saves').mkdir(parents=True)
    (library / 'saves/retained.sav').write_bytes(b'generation')
    alias = tmp_path / 'other-spelling'
    try:
        alias.symlink_to(library, target_is_directory=True)
    except OSError:
        pytest.skip('directory aliases unavailable in this test environment')
    stored = str(alias / 'saves/retained.sav')
    assert _managed_save_paths(library, [stored], require_all=True) == ({stored: 'saves/retained.sav'}, [str(alias)])
    with pytest.raises(Refused, match='retained generation'):
        _managed_save_paths(library, [str(alias / 'saves/missing.sav')], require_all=True)
