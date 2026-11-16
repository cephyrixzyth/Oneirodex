"""Pinned Linux release verification; native execution only on disposable CI."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import zipfile

REPOSITORY = 'cephyrixzyth/Oneirodex'
SOURCE = 'dc8e0ddea9ef2e4b6ba3ba8a905021c5dc2674f3'
ARCHIVE_DIGEST = '106d0dd61f7aa59f385fdca74272ff39725fb9f604ef6c23e2be2ab754561270'
DEB_DIGEST = '6e1e8931752633323a8e28abaa8c17a5cdec2beda6c38c6857a24c1db284a297'
BINARY_DIGEST = '8f74ca079fb7344910206c738b2e49729c92255c82ef439f81ff713a7f21db19'
DEB_MEMBER = 'deb/Oneirodex_1.1.9_amd64.deb'
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024


class ProbeFailure(RuntimeError):
    """Fixed sanitized code; never a raw subprocess/native message."""


def require_ci_execution(platform, env, uid):
    if not (platform == 'linux' and type(uid) is int and uid > 0
            and env.get('GITHUB_ACTIONS') == 'true' and env.get('RUNNER_OS') == 'Linux'
            and env.get('GITHUB_REPOSITORY') == REPOSITORY
            and re.fullmatch(r'[1-9][0-9]*', env.get('GITHUB_RUN_ID', ''))):
        raise ProbeFailure('execution_requires_ordinary_disposable_linux_ci')


def validate_selection(env):
    if (env.get('LINUX_PACKAGED_SMOKE_ONLY') != 'true'
            or any(env.get(key) == 'true' for key in ('PROBE_ONLY','PROBE_FAMILY',
                'WINDOWS_PACKAGED_SMOKE_ONLY','WINDOWS_USER_FIXTURE_ONLY')) or env.get('RELEASE_TAG')
            or env.get('PACKAGE_SOURCE_RUN') != '43803881137'
            or env.get('PACKAGE_SOURCE_COMMIT') != SOURCE or env.get('PACKAGE_ARCHIVE_DIGEST') != ARCHIVE_DIGEST):
        raise ProbeFailure('linux_package_selection_not_exclusive_or_pinned')


def validate_source(run, artifacts, expected_source, expected_digest):
    if (expected_source, expected_digest) != (SOURCE, ARCHIVE_DIGEST):
        raise ProbeFailure('unexpected_linux_package_pin')
    if not (run.get('head_sha') == expected_source and run.get('head_branch') == 'codex/release-v1.1.9'
            and run.get('event') == 'push' and run.get('status') == 'completed'
            and run.get('conclusion') == 'success'):
        raise ProbeFailure('source_run_not_qualified')
    candidates = [item for item in artifacts if item.get('name') == 'oneirodex-full-linux']
    if len(candidates) != 1:
        raise ProbeFailure('linux_artifact_missing_or_ambiguous')
    artifact = candidates[0]
    if not (type(artifact.get('id')) is int and artifact['id'] == 14197603603
            and artifact.get('expired') is False and artifact.get('digest') == 'sha256:' + expected_digest
            and type(artifact.get('size_in_bytes')) is int and artifact['size_in_bytes'] == 85645912):
        raise ProbeFailure('linux_artifact_not_qualified')
    return artifact


def create_workspace(path, owned_root):
    root, work = Path(owned_root).resolve(strict=True), Path(path).resolve()
    if work == root or not work.is_relative_to(root) or work.exists():
        raise ProbeFailure('workspace_not_fresh_or_owned')
    work.mkdir(parents=True, exist_ok=False)
    return work


def extract_deb(data, work, expected_digest=DEB_DIGEST, expected_size=3870350):
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ProbeFailure('linux_archive_too_large')
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            allowed = {DEB_MEMBER, 'appimage/Oneirodex_1.1.9_amd64.AppImage', 'deb/', 'appimage/'}
            if (not entries or len(entries) > 4 or len({item.filename for item in entries}) != len(entries)
                    or any(item.filename not in allowed
                           or stat.S_IFMT(item.external_attr >> 16) not in (
                               (0, stat.S_IFDIR) if item.is_dir() else (0, stat.S_IFREG))
                           or not 0 <= item.file_size <= MAX_ARCHIVE_BYTES for item in entries)):
                raise ProbeFailure('unsafe_linux_archive_payload')
            debs = [item for item in entries if item.filename == DEB_MEMBER and not item.is_dir()]
            if len(debs) != 1 or debs[0].file_size != expected_size or not 0 < expected_size <= 32*1024*1024:
                raise ProbeFailure('linux_deb_missing_or_wrong_size')
            with archive.open(debs[0]) as source:
                content = source.read(expected_size + 1)
            if len(content) != expected_size or hashlib.sha256(content).hexdigest() != expected_digest:
                raise ProbeFailure('linux_deb_digest_mismatch')
    except (zipfile.BadZipFile, RuntimeError, EOFError):
        raise ProbeFailure('invalid_linux_zip') from None
    target = Path(work) / 'Oneirodex_1.1.9_amd64.deb'
    try:
        with target.open('xb') as output:
            try:
                output.write(content)
            except BaseException:
                output.close()
                target.unlink()
                raise
    except FileExistsError:
        raise ProbeFailure('linux_deb_target_not_fresh') from None
    return target


def _gh_json(path):
    try:
        result = subprocess.run(['gh', 'api', path], capture_output=True, timeout=45, check=True)
        if len(result.stdout) > 1024*1024:
            raise ProbeFailure('github_metadata_too_large')
        return json.loads(result.stdout)
    except (subprocess.SubprocessError, ValueError):
        raise ProbeFailure('github_metadata_unavailable') from None


def retrieve_package(work, source_run, source_commit, archive_digest, progress):
    if source_run != '43803881137':
        raise ProbeFailure('unexpected_linux_source_run')
    prefix = 'repos/' + REPOSITORY + '/actions/'
    run = _gh_json(prefix + 'runs/' + source_run)
    artifacts = _gh_json(prefix + 'runs/' + source_run + '/artifacts')['artifacts']
    artifact = validate_source(run, artifacts, source_commit, archive_digest)
    archive = work / 'source-artifact.zip'
    try:
        with archive.open('xb') as output:
            subprocess.run(['gh', 'api', prefix + 'artifacts/' + str(artifact['id']) + '/zip'],
                           stdout=output, stderr=subprocess.PIPE, timeout=120, check=True)
    except subprocess.SubprocessError:
        raise ProbeFailure('linux_archive_download_failed') from None
    if archive.stat().st_size != artifact['size_in_bytes']:
        raise ProbeFailure('linux_archive_size_mismatch')
    data = archive.read_bytes()
    if len(data) > MAX_ARCHIVE_BYTES or hashlib.sha256(data).hexdigest() != archive_digest:
        raise ProbeFailure('linux_archive_digest_mismatch')
    deb = extract_deb(data, work)
    progress.update(source_commit=source_commit, source_run=int(source_run), artifact_id=artifact['id'],
                    archive_sha256=archive_digest, deb_sha256=DEB_DIGEST, source_and_digest_verified=True)
    return deb


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--connected', action='store_true')
    parser.add_argument('--work-dir', type=Path, required=True)
    parser.add_argument('--source-run', required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--archive-digest', required=True)
    args = parser.parse_args(argv)
    receipt = {'observed_utc': datetime.now(timezone.utc).isoformat(), 'status': 'failed',
               'mode': 'remote-companion', 'installed_runtime_acceptance': False,
               'acceptance_scope':'linux_connected_accounts_and_credentials' if args.connected else 'linux_cold_ui_native_ipc'}
    try:
        require_ci_execution(sys.platform, os.environ, getattr(os, 'geteuid', lambda: -1)())
        if not args.execute:
            raise ProbeFailure('linux_execution_not_requested')
        validate_selection(os.environ)
        work = create_workspace(args.work_dir, os.environ['RUNNER_TEMP'])
        deb = retrieve_package(work, args.source_run, args.source_commit, args.archive_digest, receipt)
        if args.connected:
            from linux_connected_journey import run_connected_package
            run_connected_package(deb,work,receipt)
        else:
            from linux_packaged_runtime import execute_probe
            execute_probe(deb, work, receipt)
        receipt['status'] = 'passed'
        code = 0
    except ProbeFailure as error:
        receipt['installed_runtime_acceptance']=False
        receipt['code'] = str(error)
        code = 2 if str(error) in ('execution_requires_ordinary_disposable_linux_ci',
                                  'linux_execution_not_requested') else 1
        if code == 2:
            receipt['status'] = 'unsupported'
    except Exception as error:
        receipt['installed_runtime_acceptance']=False
        receipt.update(code='linux_packaged_probe_failed', error_class=type(error).__name__)
        code = 1
    print(json.dumps(receipt, indent=2))
    return code


if __name__ == '__main__':
    sys.modules.setdefault('probe_linux_packaged', sys.modules[__name__])
    sys.exit(main())
