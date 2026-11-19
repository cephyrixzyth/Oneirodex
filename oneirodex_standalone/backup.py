"""Create and inspect offline standalone backups.

The initial backup contract deliberately reuses the standalone move snapshot:
the application must be stopped, its PostgreSQL cluster must not be running,
and the exporter starts only that database while it captures the DB and
managed file generations. A completed backup remains compatible with the
existing verified move importer.
"""
from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import subprocess
import sys

from oneirodex_standalone.move import (
    Refused,
    UsageError,
    _safe_join,
    _sha256,
    export as export_move,
)


def _source_commit() -> str | None:
    root = Path(__file__).resolve().parents[1]
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--verify', 'HEAD'], cwd=root,
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = result.stdout.strip()
    return value if result.returncode == 0 and len(value) == 40 else None


def _verify_payload(bundle: Path, manifest: dict) -> None:
    if not isinstance(manifest, dict):
        raise Refused('backup manifest is invalid')
    dump_info = manifest.get('db_dump')
    if not isinstance(dump_info, dict) or not isinstance(dump_info.get('size'), int) \
            or not isinstance(dump_info.get('sha256'), str):
        raise Refused('backup database metadata is invalid')
    dump = bundle / 'db.dump'
    if dump.is_symlink() or not dump.is_file() or dump.stat().st_size != dump_info['size']:
        raise Refused('backup database dump is missing or incomplete')
    if _sha256(dump) != dump_info['sha256']:
        raise Refused('backup database dump failed its checksum')
    files = manifest.get('files')
    if not isinstance(files, list):
        raise Refused('backup file manifest is invalid')
    for entry in files:
        if (not isinstance(entry, dict) or not isinstance(entry.get('path'), str)
                or not isinstance(entry.get('size'), int) or not isinstance(entry.get('sha256'), str)):
            raise Refused('backup file metadata is invalid')
        path = _safe_join(bundle / 'files', entry['path'], 'backup')
        if path.is_symlink() or not path.is_file() or path.stat().st_size != entry['size']:
            raise Refused('a referenced backup file is missing or incomplete')
        if _sha256(path) != entry['sha256']:
            raise Refused('a referenced backup file failed its checksum')


def _atomic_write(path: Path, raw: bytes) -> None:
    temporary = path.with_name(path.name + '.pending')
    with temporary.open('xb') as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    _sync_directory(path.parent)


def _sync_directory(path: Path) -> None:
    if os.name != 'nt':
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _sync_staged_bundle(bundle: Path) -> None:
    if os.name == 'nt':
        return  # Python does not expose flushable directory handles on Windows.
    for directory, _dirs, filenames in os.walk(bundle, topdown=False):
        for filename in filenames:
            with (Path(directory) / filename).open('rb') as handle:
                os.fsync(handle.fileno())
        _sync_directory(Path(directory))


def _publish_new_directory(source: Path, destination: Path) -> None:
    """Rename without replacing a destination created by another process."""
    if os.name == 'nt':
        try:
            os.rename(source, destination)  # Windows refuses an existing destination.
        except OSError:
            if destination.exists() or destination.is_symlink():
                raise Refused('the backup destination changed during export') from None
            raise
        return
    import ctypes
    import errno

    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == 'darwin':
        result = libc.renamex_np(os.fsencode(source), os.fsencode(destination), 4)  # RENAME_EXCL
    elif sys.platform.startswith('linux') and hasattr(libc, 'renameat2'):
        result = libc.renameat2(-100, os.fsencode(source), -100, os.fsencode(destination), 1)
    else:
        raise Refused('this platform cannot atomically publish a new backup directory')
    if result != 0:
        error = ctypes.get_errno()
        if error in {errno.EEXIST, errno.ENOTEMPTY}:
            raise Refused('the backup destination changed during export')
        raise OSError(error, os.strerror(error), destination)


def finalize_backup_manifest(
    bundle: Path,
    *,
    data_dir: Path,
    source_commit: str | None = None,
    created_at: str | None = None,
) -> str:
    """Add the standalone snapshot contract and publish its completion marker."""
    manifest_path = bundle / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    _verify_payload(bundle, manifest)
    database_metadata = manifest.get('db')
    if not isinstance(database_metadata, dict):
        raise Refused('backup database manifest is invalid')
    if database_metadata.get('legacy_reusable_secret_count') not in (None, 0):
        raise Refused('migrate remaining reusable plaintext credentials before creating a protected backup')
    recorded_secret_keys = database_metadata.get('reusable_secret_key_ids') or []
    if not isinstance(recorded_secret_keys, list) or not all(isinstance(item, str) for item in recorded_secret_keys):
        raise Refused('backup reusable-secret key references are invalid')
    required_secret_keys = set(recorded_secret_keys)
    if required_secret_keys:
        try:
            from oneirodex.utils.store_credentials import load_store_credential_keyring

            keyring = load_store_credential_keyring()
        except Exception:  # noqa: BLE001 - do not expose key paths or values
            raise Refused('restore the protected reusable-secret keyring before backup') from None
        if not required_secret_keys.issubset(keyring.keys):
            raise Refused('the reusable-secret keyring is missing required key IDs')
    manifest['required_reusable_secret_key_ids'] = sorted(required_secret_keys)
    pg_version_path = data_dir / 'pgdata' / 'PG_VERSION'
    if not pg_version_path.is_file():
        raise Refused('standalone PostgreSQL version metadata is missing')
    pg_major_text = pg_version_path.read_text(encoding='ascii').strip()
    if not pg_major_text.isdigit():
        raise Refused('standalone PostgreSQL version metadata is invalid')

    tables = manifest['db']['tables']
    manifest['backup'] = {
        'format': 'oneirodex-standalone-backup/2',
        'created_at': created_at or datetime.now(timezone.utc).isoformat(),
        'source_commit': source_commit if source_commit and len(source_commit) == 40 else None,
        'postgresql_major': int(pg_major_text),
        'schema_revision': manifest['db']['alembic_revision'],
        'snapshot_contract': 'application-stopped; bundled PostgreSQL was verified stopped before capture',
        'save_generation_identity': {
            table: tables.get(table)
            for table in ('emulator_saves', 'emulator_save_generations')
            if table in tables
        },
        'excluded': [
            'external game-library contents (root mappings only)',
            'library/bios (copy separately when required)',
            'operator credential and save keyring material',
        ],
        'key_recovery': 'restore independently protected operator keyrings matching the required key IDs',
    }
    raw = json.dumps(manifest, indent=2, sort_keys=True) + '\n'
    _atomic_write(manifest_path, raw.encode('utf-8'))
    fingerprint = _sha256(raw.encode('utf-8'))
    _atomic_write(bundle / 'manifest.sha256', (fingerprint + '\n').encode('ascii'))
    complete = {
        'format': 'oneirodex-standalone-backup-complete/2',
        'manifest_sha256': fingerprint,
    }
    _atomic_write(bundle / 'backup.complete.json',
                  (json.dumps(complete, sort_keys=True) + '\n').encode('utf-8'))
    return fingerprint


def verify_complete_backup(bundle: Path) -> dict:
    """Reject partial, altered or unsupported backup folders."""
    try:
        if ((bundle / 'manifest.json').is_symlink()
                or (bundle / 'backup.complete.json').is_symlink()
                or (bundle / 'manifest.sha256').is_symlink()):
            raise Refused('backup metadata cannot be symbolic links')
        manifest = json.loads((bundle / 'manifest.json').read_text(encoding='utf-8'))
        complete = json.loads((bundle / 'backup.complete.json').read_text(encoding='utf-8'))
        recorded = (bundle / 'manifest.sha256').read_text(encoding='ascii').strip()
    except Refused:
        raise
    except (OSError, ValueError):
        raise Refused('backup is incomplete or unreadable') from None
    actual = _sha256((bundle / 'manifest.json').read_bytes())
    backup_metadata = manifest.get('backup')
    if not isinstance(backup_metadata, dict):
        raise Refused('backup manifest is incomplete or has changed')
    backup_format = backup_metadata.get('format')
    completion_format = complete.get('format')
    supported = {
        'oneirodex-standalone-backup/1': 'oneirodex-standalone-backup-complete/1',
        'oneirodex-standalone-backup/2': 'oneirodex-standalone-backup-complete/2',
    }
    if (backup_format not in supported
            or completion_format != supported[backup_format]
            or actual != recorded or actual != complete.get('manifest_sha256')):
        raise Refused('backup manifest is incomplete or has changed')
    database_metadata = manifest.get('db')
    if not isinstance(database_metadata, dict):
        raise Refused('backup database manifest is invalid')
    if database_metadata.get('legacy_reusable_secret_count') not in (None, 0):
        raise Refused('backup contains reusable plaintext credentials; migrate them before restore')
    database_key_ids = database_metadata.get('reusable_secret_key_ids') or []
    required_key_ids = manifest.get('required_reusable_secret_key_ids') or []
    if (not isinstance(database_key_ids, list) or not all(isinstance(item, str) for item in database_key_ids)
            or not isinstance(required_key_ids, list) or not all(isinstance(item, str) for item in required_key_ids)
            or sorted(set(database_key_ids)) != sorted(set(required_key_ids))):
        raise Refused('backup reusable-secret key references do not match the manifest')
    _verify_payload(bundle, manifest)
    return manifest


def create(args) -> int:
    """Create a verified backup from a stopped standalone installation."""
    requested_out = Path(args.to).absolute()
    if requested_out.is_symlink():
        raise Refused('the backup destination cannot be a symbolic link')
    out = requested_out.resolve()
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise Refused('the backup destination must be new or empty')
    original = out.stat() if out.exists() else None
    out.parent.mkdir(parents=True, exist_ok=True)
    data_dir = (args.data_dir or _default_data_dir()).resolve()
    if out.is_relative_to(data_dir / 'library') or out.is_relative_to(data_dir / 'pgdata'):
        raise Refused('choose a backup destination outside the source library and database')
    with tempfile.TemporaryDirectory(prefix='.oneirodex-backup-', dir=out.parent) as private:
        staged = Path(private) / 'bundle'
        export_args = SimpleNamespace(pg_home=args.pg_home, data_dir=args.data_dir, to=str(staged),
                                      root=args.root, require_no_plaintext_secrets=True)
        with redirect_stdout(io.StringIO()):
            result = export_move(export_args)
        if result != 0:
            raise Refused('standalone backup export did not complete')
        fingerprint = finalize_backup_manifest(staged, data_dir=data_dir, source_commit=_source_commit())
        manifest = verify_complete_backup(staged)
        _sync_staged_bundle(staged)
        if original is not None:
            try:
                if out.is_symlink() or not os.path.samestat(original, out.stat()):
                    raise Refused('the backup destination changed during export')
                out.rmdir()  # atomically refuse a concurrently populated directory
            except OSError:
                raise Refused('the backup destination changed during export') from None
        try:
            _publish_new_directory(staged, out)
        except BaseException:
            if original is not None:
                try:
                    out.mkdir(mode=original.st_mode & 0o777)
                except FileExistsError:
                    pass
            raise
        try:
            _sync_directory(out.parent)
        except OSError:
            raise Refused('the verified backup was published but the destination directory could not be flushed') from None
    print(f'backup complete: {len(manifest["files"])} managed files; schema {manifest["backup"]["schema_revision"]}')
    print(f'folder: {out}')
    print(f'manifest sha256: {fingerprint}')
    print('restore with the verified move importer and the matching protected operator keyrings.')
    return 0


def _default_data_dir() -> Path:
    from oneirodex_standalone.launcher import default_data_dir

    return default_data_dir()


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog='python -m oneirodex_standalone backup', description='Create an offline standalone backup.',
    )
    parser.add_argument('--pg-home', required=True, type=Path, help='root of the bundled PostgreSQL')
    parser.add_argument('--data-dir', type=Path, default=None, help='standalone data folder (default: the usual one)')
    parser.add_argument('--to', required=True, help='new or empty folder for the backup')
    parser.add_argument('--root', action='append', help='NAME=PATH: record an external game root (contents excluded)')
    parser.set_defaults(fn=create)
    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except UsageError as exc:
        print(f'usage: {exc}', file=sys.stderr)
        return 2
    except Refused as exc:
        print(f'REFUSED: {exc}', file=sys.stderr)
        return 1
    except OSError as exc:
        print(f'Backup filesystem operation failed ({type(exc).__name__}). Check free space and permissions.',
              file=sys.stderr)
        return 1

