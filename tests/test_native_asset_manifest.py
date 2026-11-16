"""Verify source-built native SPA manifests reject incomplete bundles."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'validate_native_install', ROOT / 'scripts' / 'validate-native-install.py'
)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


TARGETS = {
    'member-app': 'index.html',
    'member-auth': 'auth.html',
    'admin-app': 'index.html',
    'admin-pilot': 'index.html',
    'ops-glance': 'index.html',
}


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def make_bundle(root: Path) -> Path:
    root.mkdir()
    manifest = {
        'schema_version': 1,
        'source_commit': 'a' * 40,
        'package_lock_sha256': _digest((ROOT / 'package-lock.json').read_bytes()),
        'targets': {},
    }
    for target, entrypoint in TARGETS.items():
        target_root = root / target
        target_root.mkdir()
        entry = b'<html><script src="assets/app.js"></script></html>'
        asset = b'compiled javascript'
        (target_root / entrypoint).write_bytes(entry)
        (target_root / 'assets').mkdir()
        (target_root / 'assets' / 'app.js').write_bytes(asset)
        manifest['targets'][target] = {
            'entrypoint': entrypoint,
            'files': [
                {'path': entrypoint, 'sha256': _digest(entry), 'size_bytes': len(entry)},
                {'path': 'assets/app.js', 'sha256': _digest(asset), 'size_bytes': len(asset)},
            ],
        }
    (root / 'server-ui-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    return root


def _write_manifest(root: Path, manifest: dict) -> None:
    (root / 'server-ui-manifest.json').write_text(json.dumps(manifest), encoding='utf-8')


def test_native_asset_manifest_accepts_complete_five_target_bundle(tmp_path):
    root = make_bundle(tmp_path / 'dist')

    assert VALIDATOR.validate_assets(root) == []


@pytest.mark.parametrize('target', TARGETS)
def test_native_asset_manifest_rejects_each_missing_target(tmp_path, target):
    root = make_bundle(tmp_path / 'dist')
    manifest_path = root / 'server-ui-manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    del manifest['targets'][target]
    _write_manifest(root, manifest)

    assert any(f'Manifest target is missing: {target}' in item
               for item in VALIDATOR.validate_assets(root))


def test_native_asset_manifest_rejects_missing_and_tampered_referenced_files(tmp_path):
    root = make_bundle(tmp_path / 'dist')
    (root / 'member-app' / 'assets' / 'app.js').write_bytes(b'compiled Javascript')
    (root / 'admin-app' / 'index.html').unlink()

    problems = VALIDATOR.validate_assets(root)
    assert 'Manifest file digest mismatch: member-app/assets/app.js' in problems
    assert 'Manifest file is missing: admin-app/index.html' in problems


def test_native_asset_manifest_rejects_unlisted_stale_files_and_lock_mismatch(tmp_path):
    root = make_bundle(tmp_path / 'dist')
    (root / 'ops-glance' / 'old-stale.js').write_text('stale', encoding='utf-8')
    manifest_path = root / 'server-ui-manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest['package_lock_sha256'] = '0' * 64
    _write_manifest(root, manifest)

    problems = VALIDATOR.validate_assets(root)
    assert 'Manifest inventory differs from files on disk: ops-glance' in problems
    assert 'Manifest package-lock digest does not match this source tree' in problems


def test_native_asset_manifest_rejects_non_object_json_root(tmp_path):
    root = tmp_path / 'dist'
    root.mkdir()
    (root / 'server-ui-manifest.json').write_text('[]', encoding='utf-8')

    assert VALIDATOR.validate_assets(root) == ['Server UI manifest root must be a JSON object']
