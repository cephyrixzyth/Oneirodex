"""Inspect a pinned Windows package; GUI execution is restricted to disposable CI."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import time
import socket
import ipaddress
import uuid
import urllib.parse
import urllib.request
import zipfile

REPOSITORY = 'cephyrixzyth/Oneirodex'
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024


class ProbeFailure(RuntimeError):
    """A controlled, secret-free diagnostic code."""


def require_ci_execution(platform, env):
    if not (platform == 'nt' and env.get('GITHUB_ACTIONS') == 'true'
            and env.get('RUNNER_OS') == 'Windows'
            and env.get('GITHUB_REPOSITORY') == REPOSITORY
            and re.fullmatch(r'[1-9][0-9]*', env.get('GITHUB_RUN_ID', ''))):
        raise ProbeFailure('execution_requires_disposable_windows_ci')


def validate_source(run, artifacts, expected_source, expected_digest):
    if not (re.fullmatch(r'[a-f0-9]{40}', expected_source)
            and re.fullmatch(r'[a-f0-9]{64}', expected_digest)):
        raise ProbeFailure('invalid_source_pin')
    if not (run.get('head_sha') == expected_source
            and run.get('head_branch') == 'codex/release-v1.1.9'
            and run.get('event') == 'push'
            and run.get('status') == 'completed'
            and run.get('conclusion') == 'success'):
        raise ProbeFailure('source_run_not_qualified')
    matches = [a for a in artifacts if a.get('name') == 'oneirodex-full-windows']
    if len(matches) != 1:
        raise ProbeFailure('artifact_missing_or_ambiguous')
    artifact = matches[0]
    if not (artifact.get('expired') is False
            and artifact.get('digest') == 'sha256:' + expected_digest
            and type(artifact.get('id')) is int and artifact['id'] > 0
            and type(artifact.get('size_in_bytes')) is int
            and 0 < artifact['size_in_bytes'] <= MAX_ARCHIVE_BYTES):
        raise ProbeFailure('artifact_not_qualified')
    return artifact


def verify_digest(data, expected_digest):
    if len(data) > MAX_ARCHIVE_BYTES or hashlib.sha256(data).hexdigest() != expected_digest:
        raise ProbeFailure('archive_digest_or_size_mismatch')


def create_workspace(path, owned_root):
    root = Path(owned_root).resolve()
    work = Path(path).resolve()
    if work == root or not work.is_relative_to(root) or work.exists():
        raise ProbeFailure('workspace_not_fresh_or_owned')
    work.mkdir(parents=True, exist_ok=False)
    return work


def extract_installer(data, work):
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ProbeFailure('archive_too_large')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        files = [entry for entry in archive.infolist() if not entry.is_dir()]
        if len(files) != 1:
            raise ProbeFailure('installer_missing_or_ambiguous')
        entry = files[0]
        path = PurePosixPath(entry.filename)
        if (path.is_absolute() or len(path.parts) != 1 or '..' in path.parts
                or '\\' in entry.filename or ':' in entry.filename
                or not re.fullmatch(r'Oneirodex_\d+\.\d+\.\d+_x64-setup\.exe', path.name)
                or stat.S_IFMT(entry.external_attr >> 16) not in (0, stat.S_IFREG)
                or not 0 < entry.file_size <= MAX_ARCHIVE_BYTES):
            raise ProbeFailure('unsafe_installer_payload')
        target = Path(work) / path.name
        with archive.open(entry) as source, target.open('xb') as output:
            remaining = MAX_ARCHIVE_BYTES
            while chunk := source.read(min(64 * 1024, remaining + 1)):
                remaining -= len(chunk)
                if remaining < 0:
                    raise ProbeFailure('expanded_installer_too_large')
                output.write(chunk)
        return target


def listener_is_owned(listeners, parents, root_pid):
    if not listeners:
        return False
    for listener in listeners:
        try:
            if not ipaddress.ip_address(listener['address']).is_loopback:
                return False
            pid = int(listener['pid'])
        except (ValueError, KeyError, TypeError):
            return False
        seen = set()
        while pid != root_pid:
            if pid in seen or len(seen) >= 32 or pid not in parents:
                return False
            seen.add(pid)
            pid = parents[pid]
    return True


def _wait(check, seconds, code):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.25)
    raise ProbeFailure(code)


def _listener_snapshot(port):
    # Only numeric process/network metadata is read; no command lines or secrets.
    script = (
        f'$listeners=@(Get-NetTCPConnection -State Listen -LocalPort {int(port)} '
        '-ErrorAction Stop | ForEach-Object { @{address=$_.LocalAddress;pid=$_.OwningProcess} });'
        '$parents=@(Get-CimInstance Win32_Process | ForEach-Object '
        '{ @{pid=$_.ProcessId;parent=$_.ParentProcessId} });'
        '@{listeners=$listeners;parents=$parents}|ConvertTo-Json -Depth 4 -Compress'
    )
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                            capture_output=True, encoding='utf-8', timeout=20)
    if result.returncode:
        raise ProbeFailure('listener_observation_failed')
    data = json.loads(result.stdout)
    return data['listeners'], {int(p['pid']): int(p['parent']) for p in data['parents']}


def _port_closed(port):
    with socket.socket() as connection:
        connection.settimeout(0.5)
        return connection.connect_ex(('127.0.0.1', port)) != 0


def runtime_environment(env):
    allowed = {'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'PATH', 'PATHEXT', 'USERPROFILE',
               'APPDATA', 'LOCALAPPDATA', 'PROGRAMFILES', 'PROGRAMFILES(X86)', 'PROGRAMDATA',
               'COMSPEC', 'SYSTEMDRIVE', 'USERNAME', 'USERDOMAIN', 'HOMEDRIVE', 'HOMEPATH',
               'ALLUSERSPROFILE', 'COMMONPROGRAMFILES', 'COMMONPROGRAMFILES(X86)',
               'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE', 'PROCESSOR_IDENTIFIER'}
    return {key: value for key, value in env.items() if key.upper() in allowed}


def _cold_start(executable, work, round_number, progress):
    from playwright.sync_api import sync_playwright

    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    env = runtime_environment(os.environ)
    env['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] = (
        f'--remote-debugging-address=127.0.0.1 --remote-debugging-port={port}'
    )
    env['WEBVIEW2_USER_DATA_FOLDER'] = str(work / 'webview-profile')
    process = subprocess.Popen([str(executable)], env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    browser = None
    client = None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def endpoint_ready():
        if process.poll() is not None:
            raise ProbeFailure('installed_app_exited_before_ready')
        try:
            with opener.open(f'http://127.0.0.1:{port}/json/version', timeout=1) as response:
                return response.status == 200
        except OSError:
            return False

    try:
        progress['phase'] = f'cold_{round_number}_webview_startup'
        _wait(endpoint_ready, 60, 'webview_endpoint_not_ready')
        progress['phase'] = f'cold_{round_number}_listener_ownership'
        listeners, parents = _listener_snapshot(port)
        if process.poll() is not None or not listener_is_owned(listeners, parents, process.pid):
            raise ProbeFailure('unowned_or_non_loopback_debug_listener')
        client = sync_playwright().start()
        browser = client.chromium.connect_over_cdp(f'http://127.0.0.1:{port}', timeout=15_000)
        progress['phase'] = f'cold_{round_number}_bundled_renderer'
        _wait(lambda: any(context.pages for context in browser.contexts),
              30, 'packaged_window_not_ready')
        pages = [page for context in browser.contexts for page in context.pages]
        if len(pages) != 1:
            raise ProbeFailure('unexpected_packaged_window_count')
        page = pages[0]
        page.get_by_role('heading', name='Oneirodex Desktop', exact=True).wait_for(timeout=30_000)
        page.locator('#connect-form').wait_for()
        if urllib.parse.urlsplit(page.url).hostname != 'tauri.localhost':
            raise ProbeFailure('renderer_is_not_the_bundled_app')
        progress['phase'] = f'cold_{round_number}_native_ipc'
        checks = page.evaluate('''async () => {
            const ipc = window.__TAURI_INTERNALS__;
            if (!ipc || typeof ipc.invoke !== 'function') return {bridge: false};
            const config = await ipc.invoke('load_config');
            const directory = await ipc.invoke('get_app_subdir', {subdir: 'installs'});
            let denied = false;
            try { await ipc.invoke('get_app_subdir', {subdir: '..'}); }
            catch { denied = true; }
            return {bridge: true, fresh: !config.base_url && !config.token,
                emptyToken: document.querySelector('#token').value.length === 0,
                directory, parentDenied: denied};
        }''')
        if not all(checks.get(key) is True for key in ('bridge', 'fresh', 'emptyToken', 'parentDenied')):
            raise ProbeFailure('packaged_ui_or_native_ipc_contract_failed')
        directory = Path(checks['directory']).resolve()
        profile = Path(os.environ['USERPROFILE']).resolve()
        if directory == profile or not directory.is_relative_to(profile) or not directory.is_dir():
            raise ProbeFailure('installs_directory_not_owned_by_ci_profile')
        return directory, {'round': round_number, 'bundled_renderer': True,
                           'native_ipc': True, 'fresh_config': True,
                           'webview_version': browser.version,
                           'parent_directory_denied': True, 'listener_ownership_verified': True}
    finally:
        try:
            if browser:
                browser.close()
        finally:
            if client:
                client.stop()
            if process.poll() is None:
                # Popen retains the owned Windows process handle. Avoid PID lookup
                # and tree termination, including when game journeys are added later.
                process.terminate()
            process.wait(timeout=20)
            _wait(lambda: _port_closed(port), 15, 'owned_webview_listener_not_closed')


def execute_cold_probe(installer, work, progress):
    require_ci_execution(os.name, os.environ)
    install = work / 'installed'
    progress['phase'] = 'silent_install'
    result = subprocess.run([str(installer), '/S', '/D=' + str(install)],
                            env=runtime_environment(os.environ),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
    if result.returncode:
        raise ProbeFailure('silent_install_failed')
    uninstaller = install / 'uninstall.exe'
    marker = None
    content = b'Oneirodex owned CI retention fixture; not a registered game or save.\n'
    result_receipt = progress
    import ctypes
    result_receipt['ci_account_elevated'] = bool(ctypes.windll.shell32.IsUserAnAdmin())
    result_receipt['windows_build'] = sys.getwindowsversion().build
    try:
        executables = [p for p in install.glob('*.exe')
                       if p.is_file() and not p.name.lower().startswith('uninstall')]
        if len(executables) != 1:
            raise ProbeFailure('installed_binary_missing_or_ambiguous')
        executable = executables[0]
        result_receipt['installed_binary_sha256'] = hashlib.sha256(executable.read_bytes()).hexdigest()
        directory, first = _cold_start(executable, work, 1, progress)
        marker = directory / ('oneirodex-ci-retention-' + uuid.uuid4().hex + '.txt')
        with marker.open('xb') as output:
            output.write(content)
        reopened_directory, second = _cold_start(executable, work, 2, progress)
        if directory != reopened_directory or marker.read_bytes() != content:
            raise ProbeFailure('owned_marker_not_retained_across_reopen')
        result_receipt.update(cold_start_rounds=[first, second], installed_cold_start_verified=True,
                              genuine_ipc_success_and_denial=True,
                              owned_app_roots_stopped_and_debug_listeners_closed=True)
    finally:
        if not uninstaller.is_file():
            raise ProbeFailure('owned_uninstaller_missing')
        cleanup = subprocess.run([str(uninstaller), '/S'], stdout=subprocess.DEVNULL,
                                 env=runtime_environment(os.environ),
                                 stderr=subprocess.DEVNULL, timeout=90)
        if cleanup.returncode:
            raise ProbeFailure('owned_uninstall_failed')
        _wait(lambda: not any(p.name.lower() != 'uninstall.exe' for p in install.glob('*.exe')),
              30, 'installed_binary_remained_after_uninstall')
        if marker:
            if not marker.is_file() or marker.read_bytes() != content:
                raise ProbeFailure('uninstall_removed_owned_installs_marker')
            result_receipt['owned_installs_marker_retained_by_uninstaller'] = True
            marker.unlink()  # Delete only this probe's own exact, content-verified marker.
            result_receipt['probe_removed_its_own_marker_after_verification'] = True
        result_receipt['owned_application_uninstalled'] = True
    return result_receipt


def github_json(endpoint):
    result = subprocess.run(['gh', 'api', f'repos/{REPOSITORY}/{endpoint}'],
                            capture_output=True, encoding='utf-8', timeout=60)
    if result.returncode:
        raise ProbeFailure('github_metadata_read_failed')
    return json.loads(result.stdout)


def inspect_package(args):
    run = github_json(f'actions/runs/{args.source_run}')
    artifacts = github_json(f'actions/runs/{args.source_run}/artifacts?per_page=100')['artifacts']
    artifact = validate_source(run, artifacts, args.expected_source, args.artifact_digest)
    owned_root = (Path(os.environ['RUNNER_TEMP']) if args.execute
                  else Path.cwd() / '.artifacts')
    work = create_workspace(args.work_dir, owned_root)
    zip_path = work / 'source-artifact.zip'
    with zip_path.open('xb') as output:
        # Capture binary bytes directly; PowerShell text redirection corrupts ZIPs.
        result = subprocess.run(
            ['gh', 'api', f'repos/{REPOSITORY}/actions/artifacts/{artifact["id"]}/zip'],
            stdout=output, stderr=subprocess.PIPE, timeout=90)
    if result.returncode:
        raise ProbeFailure('github_archive_download_failed')
    if zip_path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ProbeFailure('archive_too_large')
    data = zip_path.read_bytes()
    verify_digest(data, args.artifact_digest)
    installer = extract_installer(data, work)
    receipt = {
        'source_commit': args.expected_source, 'source_run': args.source_run,
        'artifact_id': artifact['id'], 'artifact_name': artifact['name'],
        'archive_sha256': hashlib.sha256(data).hexdigest(),
        'archive_bytes': len(data), 'installer_name': installer.name,
        'installer_sha256': hashlib.sha256(installer.read_bytes()).hexdigest(),
        'source_and_digest_verified': True, 'installer_executed': False,
        'mode': 'remote-companion',
        'installed_runtime_acceptance': False,
    }
    return work, installer, receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-run', type=int, required=True)
    parser.add_argument('--expected-source', required=True)
    parser.add_argument('--artifact-digest', required=True)
    parser.add_argument('--work-dir', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    receipt = {'observed_utc': datetime.now(timezone.utc).isoformat(),
               'status': 'failed', 'installed_runtime_acceptance': False}
    work = None
    try:
        if args.execute:
            require_ci_execution(os.name, os.environ)
        if args.source_run <= 0:
            raise ProbeFailure('invalid_run_id')
        work, installer, inspected = inspect_package(args)
        receipt.update(inspected, status='inspected')
        if args.execute:
            receipt['installer_executed'] = True
            receipt.update(execute_cold_probe(installer, work, receipt), status='cold-start-passed', phase='complete')
        code = 0
    except ProbeFailure as error:
        receipt['status'] = 'failed'
        receipt['code'] = str(error)
        code = 2 if str(error) == 'execution_requires_disposable_windows_ci' else 1
        if code == 2:
            receipt['status'] = 'unsupported'
    except Exception as error:
        receipt['status'] = 'failed'
        receipt['code'] = 'probe_observation_failed'
        receipt['error_class'] = type(error).__name__
        code = 1
    if work:
        (work / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(receipt, indent=2))
    return code


if __name__ == '__main__':
    sys.exit(main())
