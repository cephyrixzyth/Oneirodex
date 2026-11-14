"""Validate native runtime configuration and required source-built SPA assets."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from oneirodex.runtime_native.app_config import build_runtime_config
from oneirodex.runtime_native.runtime_context import NativeRuntimeContext


PACKAGE_ROOT = ROOT / 'oneirodex'
SPA_TARGETS = {
    'member-app': 'index.html',
    'member-auth': 'auth.html',
    'admin-app': 'index.html',
    'admin-pilot': 'index.html',
    'ops-glance': 'index.html',
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def validate_assets(dist_root: Path) -> list[str]:
    problems: list[str] = []
    manifest_path = dist_root / 'server-ui-manifest.json'
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return ['Missing or invalid server-ui-manifest.json']
    if not isinstance(manifest, dict):
        return ['Server UI manifest root must be a JSON object']

    if manifest.get('schema_version') != 1:
        problems.append('Unsupported server UI manifest schema')
    lock_digest = manifest.get('package_lock_sha256')
    if not isinstance(lock_digest, str) or len(lock_digest) != 64:
        problems.append('Manifest package-lock digest is missing or invalid')
    else:
        lock_path = ROOT / 'package-lock.json'
        if lock_path.is_file() and _sha256(lock_path) != lock_digest:
            problems.append('Manifest package-lock digest does not match this source tree')
    commit = manifest.get('source_commit')
    if commit is not None and (
        not isinstance(commit, str)
        or len(commit) != 40
        or any(c not in '0123456789abcdef' for c in commit)
    ):
        problems.append('Manifest source commit is invalid')

    targets = manifest.get('targets')
    if not isinstance(targets, dict) or set(targets) != set(SPA_TARGETS):
        problems.append('Manifest must contain exactly the five supported SPA targets')
        targets = targets if isinstance(targets, dict) else {}

    for target, expected_entry in SPA_TARGETS.items():
        record = targets.get(target)
        if not isinstance(record, dict):
            problems.append(f'Manifest target is missing: {target}')
            continue
        if record.get('entrypoint') != expected_entry:
            problems.append(f'Manifest entrypoint mismatch: {target}')
        files = record.get('files')
        if not isinstance(files, list) or not files:
            problems.append(f'Manifest has no file inventory: {target}')
            continue
        seen: set[str] = set()
        for item in files:
            if not isinstance(item, dict):
                problems.append(f'Malformed file record in {target}')
                continue
            relative = item.get('path')
            digest = item.get('sha256')
            size = item.get('size_bytes')
            if (
                not isinstance(relative, str)
                or not relative
                or Path(relative).is_absolute()
                or '..' in Path(relative).parts
            ):
                problems.append(f'Unsafe file path in {target} manifest')
                continue
            if relative in seen:
                problems.append(f'Duplicate file record in {target}: {relative}')
                continue
            seen.add(relative)
            path = (dist_root / target / relative).resolve()
            try:
                path.relative_to((dist_root / target).resolve())
            except ValueError:
                problems.append(f'File escapes target directory: {target}/{relative}')
                continue
            if not path.is_file():
                problems.append(f'Manifest file is missing: {target}/{relative}')
                continue
            if not isinstance(size, int) or path.stat().st_size != size:
                problems.append(f'Manifest file size mismatch: {target}/{relative}')
                continue
            if not isinstance(digest, str) or len(digest) != 64 or _sha256(path) != digest:
                problems.append(f'Manifest file digest mismatch: {target}/{relative}')
        if expected_entry not in seen:
            problems.append(f'Entrypoint is absent from file inventory: {target}/{expected_entry}')
        actual_files = {
            path.relative_to(dist_root / target).as_posix()
            for path in (dist_root / target).rglob('*')
            if path.is_file()
        }
        if actual_files != seen:
            problems.append(f'Manifest inventory differs from files on disk: {target}')
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--root',
        type=Path,
        default=PACKAGE_ROOT / 'static' / 'dist',
        help='SPA dist root (defaults to the installed package bundle)',
    )
    args = parser.parse_args()
    problems = validate_assets(args.root)
    if problems:
        print('\n'.join(problems))
        return 1

    runtime_config = build_runtime_config(package_root=PACKAGE_ROOT)
    runtime = NativeRuntimeContext(runtime_config, package_root=PACKAGE_ROOT)
    if Path(runtime.static_folder).resolve() != (PACKAGE_ROOT / 'static').resolve():
        print('Native runtime static root does not resolve to the application package.')
        return 1

    print(f'Native runtime configuration and {len(SPA_TARGETS)} SPA asset manifests validated.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
