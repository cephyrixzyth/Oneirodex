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



def windows_environment_block(env):
    """Create an unambiguous, explicit Unicode block; never inherit CI secrets."""
    seen = set()
    for key, value in env.items():
        if (not isinstance(key, str) or not key or '=' in key or '\0' in key
                or not isinstance(value, str) or '\0' in value or key.upper() in seen):
            raise ProbeFailure('invalid_child_environment')
        seen.add(key.upper())
    return '\0'.join(f'{key}={env[key]}' for key in sorted(env, key=str.upper)) + '\0\0'


class _WindowsStandardAPI:
    """Win32 calls remain unreachable outside the explicit disposable CI fence."""
    def __init__(self):
        require_ci_execution(os.name, os.environ)
        import ctypes as c
        from ctypes import wintypes as w

        self.c, self.w = c, w
        self.kernel = c.WinDLL('kernel32', use_last_error=True)
        self.advapi = c.WinDLL('advapi32', use_last_error=True)

        class SID_ATTRIBUTES(c.Structure):
            _fields_ = [('Sid', c.c_void_p), ('Attributes', w.DWORD)]

        class STARTUPINFO(c.Structure):
            _fields_ = [('cb', w.DWORD), ('lpReserved', w.LPWSTR), ('lpDesktop', w.LPWSTR),
                        ('lpTitle', w.LPWSTR), ('dwX', w.DWORD), ('dwY', w.DWORD),
                        ('dwXSize', w.DWORD), ('dwYSize', w.DWORD),
                        ('dwXCountChars', w.DWORD), ('dwYCountChars', w.DWORD),
                        ('dwFillAttribute', w.DWORD), ('dwFlags', w.DWORD),
                        ('wShowWindow', w.WORD), ('cbReserved2', w.WORD),
                        ('lpReserved2', c.POINTER(w.BYTE)), ('hStdInput', w.HANDLE),
                        ('hStdOutput', w.HANDLE), ('hStdError', w.HANDLE)]

        class PROCESSINFO(c.Structure):
            _fields_ = [('hProcess', w.HANDLE), ('hThread', w.HANDLE),
                        ('dwProcessId', w.DWORD), ('dwThreadId', w.DWORD)]

        self.SID_ATTRIBUTES, self.STARTUPINFO, self.PROCESSINFO = SID_ATTRIBUTES, STARTUPINFO, PROCESSINFO
        def bind(library, name, result, args):
            fn = getattr(library, name)
            fn.restype, fn.argtypes = result, args
            return fn

        H, D, P = w.HANDLE, w.DWORD, c.c_void_p
        self._current = bind(self.kernel, 'GetCurrentProcess', H, [])
        self._open_token = bind(self.advapi, 'OpenProcessToken', w.BOOL, [H, D, c.POINTER(H)])
        self._restrict = bind(self.advapi, 'CreateRestrictedToken', w.BOOL,
                              [H, D, D, P, D, P, D, P, c.POINTER(H)])
        self._sid = bind(self.advapi, 'ConvertStringSidToSidW', w.BOOL, [w.LPCWSTR, c.POINTER(P)])
        self._sid_length = bind(self.advapi, 'GetLengthSid', D, [P])
        self._set_token = bind(self.advapi, 'SetTokenInformation', w.BOOL, [H, c.c_int, P, D])
        self._get_token = bind(self.advapi, 'GetTokenInformation', w.BOOL,
                              [H, c.c_int, P, D, c.POINTER(D)])
        self._sid_count = bind(self.advapi, 'GetSidSubAuthorityCount', c.POINTER(w.BYTE), [P])
        self._sid_part = bind(self.advapi, 'GetSidSubAuthority', c.POINTER(D), [P, D])
        self._create = bind(self.advapi, 'CreateProcessAsUserW', w.BOOL,
                            [H, w.LPCWSTR, w.LPWSTR, P, P, w.BOOL, D, P, w.LPCWSTR,
                             c.POINTER(STARTUPINFO), c.POINTER(PROCESSINFO)])
        self._resume = bind(self.kernel, 'ResumeThread', D, [H])
        self._wait = bind(self.kernel, 'WaitForSingleObject', D, [H, D])
        self._exit_code = bind(self.kernel, 'GetExitCodeProcess', w.BOOL, [H, c.POINTER(D)])
        self._terminate = bind(self.kernel, 'TerminateProcess', w.BOOL, [H, w.UINT])
        self._close = bind(self.kernel, 'CloseHandle', w.BOOL, [H])
        self._free = bind(self.kernel, 'LocalFree', P, [P])

    def check(self, result, code):
        if not result:
            raise ProbeFailure(f'{code}_winerror_{self.c.get_last_error()}')

    def close_handle(self, handle):
        if handle:
            self._close(handle)

    def restricted_token(self):
        c, w = self.c, self.w
        source, restricted, sid = w.HANDLE(), w.HANDLE(), c.c_void_p()
        # QUERY | DUPLICATE | ASSIGN_PRIMARY | ADJUST_DEFAULT.
        self.check(self._open_token(self._current(), 0x8B, c.byref(source)), 'open_ci_token')
        try:
            # DISABLE_MAX_PRIVILEGE | LUA_TOKEN. Never SANDBOX_INERT.
            self.check(self._restrict(source, 0x5, 0, None, 0, None, 0, None,
                                      c.byref(restricted)), 'restrict_ci_token')
            self.check(self._sid('S-1-16-8192', c.byref(sid)), 'medium_integrity_sid')
            label = self.SID_ATTRIBUTES(sid, 0x20)  # SE_GROUP_INTEGRITY.
            self.check(self._set_token(restricted, 25, c.byref(label),
                                      c.sizeof(label) + self._sid_length(sid)), 'set_medium_integrity')
            result = restricted.value
            restricted = w.HANDLE()
            return result
        finally:
            if sid:
                self._free(sid)
            self.close_handle(restricted)
            self.close_handle(source)

    def create_suspended(self, token, executable, env):
        c = self.c
        executable = Path(executable).resolve(strict=True)
        command = subprocess.list2cmdline([str(executable)])
        if len(command) >= 1024:
            raise ProbeFailure('child_command_too_long')
        startup, info = self.STARTUPINFO(), self.PROCESSINFO()
        startup.cb = c.sizeof(startup)
        # Inherit the runner's interactive desktop; do not edit desktop ACLs.
        block = c.create_unicode_buffer(windows_environment_block(env))
        # CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT, no inherited environment.
        self.check(self._create(token, str(executable), c.create_unicode_buffer(command),
                                None, None, False, 0x404, block, str(executable.parent), c.byref(startup),
                                c.byref(info)), 'create_standard_child')
        return info.hProcess, info.hThread, int(info.dwProcessId)

    def process_security(self, handle):
        c, w = self.c, self.w
        token, size, elevation = w.HANDLE(), w.DWORD(), w.DWORD()
        self.check(self._open_token(handle, 0x8, c.byref(token)), 'open_child_token')
        try:
            self.check(self._get_token(token, 20, c.byref(elevation), c.sizeof(elevation),
                                      c.byref(size)), 'child_elevation')
            self._get_token(token, 25, None, 0, c.byref(size))
            if not 0 < size.value <= 65536:
                raise ProbeFailure('child_integrity_size_invalid')
            buffer = c.create_string_buffer(size.value)
            self.check(self._get_token(token, 25, buffer, size.value, c.byref(size)),
                       'child_integrity')
            label = c.cast(buffer, c.POINTER(self.SID_ATTRIBUTES)).contents
            count = self._sid_count(label.Sid)
            if not count or not 1 <= count[0] <= 15:
                raise ProbeFailure('child_integrity_sid_invalid')
            rid = self._sid_part(label.Sid, count[0] - 1)
            if not rid:
                raise ProbeFailure('child_integrity_rid_missing')
            return {'elevated': bool(elevation.value), 'integrity_rid': int(rid[0])}
        finally:
            self.close_handle(token)

    def resume(self, handle):
        if self._resume(handle) != 1:
            raise ProbeFailure('child_not_resumed_from_owned_suspension')

    def wait(self, handle, milliseconds):
        result = self._wait(handle, milliseconds)
        if result not in (0, 258):  # WAIT_OBJECT_0 / WAIT_TIMEOUT.
            raise ProbeFailure('owned_process_wait_failed')
        return result == 0

    def exit_code(self, handle):
        code = self.w.DWORD()
        self.check(self._exit_code(handle, self.c.byref(code)), 'owned_process_exit_code')
        return int(code.value)

    def terminate(self, handle):
        # A concurrent exit is harmless; every operation uses the retained handle.
        if not self._terminate(handle, 1) and not self.wait(handle, 0):
            self.check(False, 'owned_process_terminate')


class _OwnedStandardProcess:
    def __init__(self, api, handle, pid, security):
        self.api, self.handle, self.pid, self.security = api, handle, pid, security

    def poll(self):
        return self.api.exit_code(self.handle) if self.api.wait(self.handle, 0) else None

    def wait(self, timeout):
        milliseconds = int(timeout * 1000)
        if not 0 <= milliseconds < 0xFFFFFFFF:
            raise ProbeFailure('invalid_owned_wait_timeout')
        if not self.api.wait(self.handle, milliseconds):
            raise subprocess.TimeoutExpired('owned standard-integrity app', timeout)
        return self.api.exit_code(self.handle)

    def terminate(self):
        self.api.terminate(self.handle)

    def close(self):
        if self.handle is not None:
            self.api.close_handle(self.handle)
            self.handle = None


def _start_standard_user(executable, env, api):
    token = api.restricted_token()
    try:
        process, thread, pid = api.create_suspended(token, executable, env)
    finally:
        api.close_handle(token)
    try:
        security = api.process_security(process)
        if security.get('elevated') is not False or security.get('integrity_rid') != 8192:
            raise ProbeFailure('child_not_standard_integrity')
        api.resume(thread)
        return _OwnedStandardProcess(api, process, pid, security)
    except BaseException:
        try:
            api.terminate(process)
            if not api.wait(process, 20000):
                raise ProbeFailure('unresumed_owned_child_not_reaped')
        finally:
            api.close_handle(process)
        raise
    finally:
        api.close_handle(thread)


def start_standard_user(executable, env):
    require_ci_execution(os.name, os.environ)
    return _start_standard_user(executable, env, _WindowsStandardAPI())


def safe_process_diagnostic(record, expected_port):
    command = record.get('command') or ''
    name = record.get('name') or ''
    return {'pid': int(record['pid']), 'parent': int(record['parent']),
            'name': name if re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', name) else 'unrecognized',
            'expected_debug_port_flag': bool(re.search(
                r'--remote-debugging-port=' + str(int(expected_port)) + r'(?:\s|$|\")', command)),
            'probe_profile_flag': 'webview-profile' in command}



def safe_native_initialization(record):
    """Only bounded static categories and numeric error codes can leave CI."""
    if not isinstance(record, dict):
        record = {}
    allowed_words = {'Oneirodex Desktop', 'Connection', 'Server URL', 'WebView2',
                     'user data', 'access', 'error', 'failed', 'initialization', 'Application Error'}

    def entries(value, key):
        result = value.get(key)
        return result if isinstance(result, list) else []

    def codes(value, key):
        return sorted({item.lower() for item in entries(value, key)[:128]
                       if isinstance(item, str) and re.fullmatch(r'0x[0-9a-fA-F]{8}', item)})[:12]

    count = record.get('window_count', 0)
    observation = record.get('window_observation')
    events = []
    for event in entries(record, 'events')[:64]:
        if not isinstance(event, dict):
            continue
        application = event.get('application', '')
        if (type(event.get('event_id')) is not int or event['event_id'] not in (1000, 1001, 1026)
                or not isinstance(application, str)
                or application.lower() not in ('oneirodex-desktop.exe', 'msedgewebview2.exe')):
            continue
        events.append({'event_id': event['event_id'], 'application': application.lower(),
                       'hresult_codes': codes(event, 'hresult_codes'),
                       'association': 'name_and_time_only'})
        if len(events) == 12:
            break
    return {'window_count': max(0, min(count, 12)) if type(count) is int else 0,
            'window_observation': observation if observation in ('complete', 'failed', 'not_attempted') else 'unknown',
            'keywords': sorted({item for item in entries(record, 'keywords')[:128]
                                if isinstance(item, str) and item in allowed_words}),
            'hresult_codes': codes(record, 'hresult_codes'),
            'query_hresult_codes': codes(record, 'query_hresult_codes'),
            'event_observation': record.get('event_observation') if record.get('event_observation')
            in ('complete', 'empty_or_unavailable', 'failed') else 'unknown',
            'events': events}


def _startup_diagnostics(process, port, work):
    script = r'''
$root=Get-Process -Id ROOTPID -ErrorAction SilentlyContinue
$rootName=if($root){$root.ProcessName+'.exe'}else{'oneirodex-desktop.exe'}
$processes=@(Get-CimInstance Win32_Process | Where-Object {
    $_.ProcessId -eq ROOTPID -or $_.Name -eq $rootName -or $_.Name -eq 'msedgewebview2.exe'
} | ForEach-Object { @{pid=$_.ProcessId;parent=$_.ParentProcessId;name=$_.Name;command=$_.CommandLine} })
$ids=@($processes|ForEach-Object {$_.pid})
$listeners=@(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object {
    $_.OwningProcess -in $ids
} | ForEach-Object { @{pid=$_.OwningProcess;port=$_.LocalPort;address=$_.LocalAddress} })
$versions=@()
foreach($folder in @("${env:ProgramFiles(x86)}\Microsoft\EdgeWebView\Application",
    "$env:ProgramFiles\Microsoft\EdgeWebView\Application",
    "$env:LOCALAPPDATA\Microsoft\EdgeWebView\Application")) {
    $versions+=@(Get-ChildItem -LiteralPath $folder -Directory -ErrorAction SilentlyContinue |
        Where-Object {$_.Name -match '^\d+\.\d+\.\d+\.\d+$'} | ForEach-Object {$_.Name})
}
$policies=@()
foreach($key in @('HKLM:\SOFTWARE\Policies\Microsoft\Edge','HKCU:\SOFTWARE\Policies\Microsoft\Edge')) {
    $value=Get-ItemPropertyValue -LiteralPath $key -Name DeveloperToolsAvailability -ErrorAction SilentlyContinue
    if($null -ne $value){$policies+=@([int]$value)}
}
$keywords=@()
$windowCount=0;$windowObservation='not_attempted';$windowCodes=@();$queryCodes=@()
if($root) {
    try {
        Add-Type -AssemblyName UIAutomationClient
        $condition=New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::ProcessIdProperty,[int]ROOTPID)
        $windows=[System.Windows.Automation.AutomationElement]::RootElement.FindAll(
            [System.Windows.Automation.TreeScope]::Children,$condition)
        $names=@()
        foreach($element in @($windows|Select-Object -First 12)) {
            $windowCount++
            $names+=@($element.Current.Name)
            $nodes=$element.FindAll([System.Windows.Automation.TreeScope]::Descendants,
                [System.Windows.Automation.Condition]::TrueCondition)
            $names+=@($nodes|Select-Object -First 100|ForEach-Object {$_.Current.Name})
        }
        $text=@($names|ForEach-Object {if($_.Length -gt 4096){$_.Substring(0,4096)}else{$_}}) -join ' '
        foreach($word in @('Oneirodex Desktop','Connection','Server URL','WebView2','user data',
            'access','error','failed','initialization','Application Error')) {
            if($text -match [regex]::Escape($word)){$keywords+=@($word)}
        }
        $windowCodes=@([regex]::Matches($text,'\b0x[0-9a-fA-F]{8}\b')|
            ForEach-Object {$_.Value.ToLowerInvariant()}|Select-Object -Unique -First 12)
        $windowObservation='complete'
    } catch {
        $windowObservation='failed'
        $queryCodes+=@(('0x{0:x8}' -f $_.Exception.HResult))
    }
}
$nativeEvents=@();$eventObservation='complete'
try {
    $events=Get-WinEvent -FilterHashtable @{LogName='Application';Id=@(1000,1001,1026);
        StartTime=(Get-Date).AddMinutes(-3)} -MaxEvents 20 -ErrorAction Stop
    foreach($event in $events) {
        $xml=[xml]$event.ToXml();$fields=@{}
        foreach($node in $xml.Event.EventData.Data) {
            $fields[$node.GetAttribute('Name')]=[string]$node.InnerText
        }
        $app=$null
        foreach($value in $fields.Values) {
            try {$name=[IO.Path]::GetFileName([string]$value).ToLowerInvariant()}catch{continue}
            if($name -in @('oneirodex-desktop.exe','msedgewebview2.exe')){$app=$name;break}
        }
        if(-not $app){continue}
        $codes=@()
        foreach($key in @('ExceptionCode','ExceptionStatus','HResult','ErrorCode')) {
            if($fields.ContainsKey($key) -and $fields[$key].Trim() -match '^(?:0x)?([0-9a-fA-F]{8})$') {
                $codes+=@('0x'+$Matches[1].ToLowerInvariant())
            }
        }
        $nativeEvents+=@(@{event_id=[int]$event.Id;application=$app;hresult_codes=$codes;
            association='name_and_time_only'})
    }
} catch {$eventObservation='empty_or_unavailable'}
$nativeInitialization=@{window_count=$windowCount;window_observation=$windowObservation;
    keywords=$keywords;hresult_codes=$windowCodes;query_hresult_codes=$queryCodes;
    event_observation=$eventObservation;events=$nativeEvents}
@{root_alive=[bool]$root;has_main_window=[bool]($root -and $root.MainWindowHandle.ToInt64() -ne 0);
    product_window_title=[bool]($root -and $root.MainWindowTitle -match 'Oneirodex');
    session_id=$(if($root){$root.SessionId}else{-1});visible_text_keywords=$keywords;
    processes=$processes;listeners=$listeners;runtime_versions=$versions;devtools_policy_values=$policies;
    native_initialization=$nativeInitialization} |
    ConvertTo-Json -Depth 5 -Compress
'''.replace('ROOTPID', str(int(process.pid)))
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                            capture_output=True, encoding='utf-8', timeout=20)
    if result.returncode:
        return {'observation': 'failed', 'code': 'startup_metadata_query_failed'}
    raw = json.loads(result.stdout)
    raw['processes'] = [safe_process_diagnostic(p, port) for p in raw['processes']]
    raw['native_initialization'] = safe_native_initialization(raw.get('native_initialization'))
    raw['probe_webview_profile_created'] = (work / 'webview-profile').exists()
    raw['parent_has_browser_folder_override'] = bool(os.environ.get('WEBVIEW2_BROWSER_EXECUTABLE_FOLDER'))
    return raw



def safe_startup_trace(record, root_pid, cleanup_time):
    """Diagnostic lifecycles only; never adopt a numeric PID after its stop/reuse."""
    raw_events = record.get('events', []) if isinstance(record, dict) else []
    events = []
    for event in raw_events[:128] if isinstance(raw_events, list) else []:
        if not isinstance(event, dict):
            continue
        name, stamp = event.get('name'), event.get('time_created')
        if (name not in ('oneirodex-desktop.exe', 'msedgewebview2.exe')
                or event.get('kind') not in ('start', 'stop')
                or type(event.get('pid')) is not int or not 0 < event['pid'] <= 0xFFFFFFFF
                or type(event.get('parent')) is not int or not 0 <= event['parent'] <= 0xFFFFFFFF
                or not isinstance(stamp, str) or not re.fullmatch(r'[1-9][0-9]{0,19}', stamp)):
            continue
        selected = {key: event[key] for key in ('kind', 'pid', 'parent', 'name', 'time_created')}
        if event['kind'] == 'stop':
            status = event.get('exit_status')
            selected['exit_status'] = status.lower() if isinstance(status, str) and re.fullmatch(
                r'0x[0-9a-fA-F]{8}', status) else None
            selected['before_controller_cleanup'] = int(stamp) < cleanup_time if cleanup_time is not None else None
        events.append(selected)
    active, related, unrelated = {}, [], []
    root_seen = False
    for event in sorted(events, key=lambda e: int(e['time_created'])):
        pid = event['pid']
        if event['kind'] == 'start':
            active.pop(pid, None)  # New start invalidates the earlier lifetime.
            related_now = ((pid == root_pid and event['name'] == 'oneirodex-desktop.exe')
                           or event['parent'] in active)
            if related_now:
                active[pid] = (event['parent'], event['name'])
                root_seen |= pid == root_pid
        else:
            related_now = active.pop(pid, None) == (event['parent'], event['name'])
        event['association'] = 'parent_chain_trace' if related_now else 'name_and_time_only'
        (related if related_now else unrelated).append(event)
    dropped = record.get('dropped', 0)
    return {'observation': record.get('status') if record.get('status') in ('complete', 'deadline', 'failed') else 'unknown',
            'capture_complete': record.get('status') == 'complete' and type(dropped) is int and dropped == 0,
            'root_start_seen': root_seen, 'parent_chain_events': related,
            'unattributed_events': unrelated, 'dropped': dropped if type(dropped) is int and dropped >= 0 else None,
            'limits': 'Read-only name/parent/time diagnostics, not product launch identity. Completion describes local collection only; provider delivery is not exhaustive. Root stop after controller cleanup is intentional.'}


_STARTUP_TRACE_SCRIPT = r'''
$ErrorActionPreference='Stop'
$ready=READY_FILE;$stop=STOP_FILE;$output=OUTPUT_FILE;$nonce=NONCE_VALUE
$startId='oneirodex-start-'+$nonce;$stopId='oneirodex-stop-'+$nonce
$records=New-Object System.Collections.Generic.List[object]
$dropped=0;$status='complete';$watch=[Diagnostics.Stopwatch]::StartNew();$stopAt=$null
try {
    $where=" WHERE ProcessName='oneirodex-desktop.exe' OR ProcessName='msedgewebview2.exe'"
    Register-CimIndicationEvent -Namespace root/cimv2 -Query ('SELECT * FROM Win32_ProcessStartTrace'+$where) -SourceIdentifier $startId -OperationTimeoutSec 10 | Out-Null
    Register-CimIndicationEvent -Namespace root/cimv2 -Query ('SELECT * FROM Win32_ProcessStopTrace'+$where) -SourceIdentifier $stopId -OperationTimeoutSec 10 | Out-Null
    [IO.File]::WriteAllText($ready,$nonce)
    while($watch.Elapsed.TotalSeconds -lt 180) {
        foreach($kind in @('start','stop')) {
            $sourceId=if($kind -eq 'start'){$startId}else{$stopId}
            foreach($entry in @(Get-Event -SourceIdentifier $sourceId -ErrorAction SilentlyContinue)) {
                $native=$entry.SourceEventArgs.NewEvent
                if($records.Count -lt 128) {
                    $item=@{kind=$kind;pid=[int]$native.ProcessID;parent=[int]$native.ParentProcessID;
                        name=([string]$native.ProcessName).ToLowerInvariant();
                        time_created=([string]$native.TIME_CREATED)}
                    if($kind -eq 'stop'){$item.exit_status=('0x{0:x8}' -f [uint32]$native.ExitStatus)}
                    $records.Add($item)
                } else {$dropped++}
                Remove-Event -EventIdentifier $entry.EventIdentifier
            }
        }
        if((Test-Path -LiteralPath $stop) -and [IO.File]::ReadAllText($stop) -eq $nonce) {
            if($null -eq $stopAt){$stopAt=$watch.Elapsed.TotalMilliseconds}
            if($watch.Elapsed.TotalMilliseconds-$stopAt -ge 500){break}
        }
        Start-Sleep -Milliseconds 50
    }
    if($watch.Elapsed.TotalSeconds -ge 180){$status='deadline'}
} catch {$status='failed'}
finally {
    foreach($sourceId in @($startId,$stopId)) {
        Unregister-Event -SourceIdentifier $sourceId -ErrorAction SilentlyContinue
        Remove-Event -SourceIdentifier $sourceId -ErrorAction SilentlyContinue
    }
    $result=@{nonce=$nonce;status=$status;dropped=$dropped;events=@($records.ToArray())}
    [IO.File]::WriteAllText($output,($result|ConvertTo-Json -Depth 5 -Compress))
}
'''


class _StartupProcessTrace:
    def __init__(self, work):
        require_ci_execution(os.name, os.environ)
        self.nonce = uuid.uuid4().hex
        self.ready = work / ('trace-ready-' + self.nonce)
        self.stop = work / ('trace-stop-' + self.nonce)
        self.output = work / ('trace-output-' + self.nonce + '.json')
        script = _STARTUP_TRACE_SCRIPT
        for key, value in [('READY_FILE', self.ready), ('STOP_FILE', self.stop),
                           ('OUTPUT_FILE', self.output), ('NONCE_VALUE', self.nonce)]:
            script = script.replace(key, "'" + str(value).replace("'", "''") + "'")
        self.process = subprocess.Popen(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
            env=runtime_environment(os.environ), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

        def ready():
            if self.process.poll() is not None:
                raise ProbeFailure('startup_trace_observer_exited')
            return self.ready.is_file() and self.ready.read_text(encoding='utf-8-sig') == self.nonce
        try:
            _wait(ready, 20, 'startup_trace_observer_not_ready')
        except BaseException:
            self._stop_process()
            raise

    def _stop_process(self):
        if self.process.poll() is None:
            self.process.terminate()
        self.process.wait(timeout=10)

    def finish(self, root_pid, cleanup_time):
        try:
            self.stop.write_text(self.nonce, encoding='utf-8')
            self.process.wait(timeout=15)
            if not self.output.is_file() or self.output.stat().st_size > 65536:
                raise ProbeFailure('startup_trace_result_missing_or_oversized')
            record = json.loads(self.output.read_text(encoding='utf-8-sig'))
            if record.get('nonce') != self.nonce:
                raise ProbeFailure('startup_trace_nonce_mismatch')
            return safe_startup_trace(record, root_pid, cleanup_time)
        except Exception as error:
            code = str(error) if isinstance(error, ProbeFailure) else ''
            return {'observation': 'failed', 'error_class': type(error).__name__,
                    'code': code if re.fullmatch(r'startup_trace_[a-z0-9_]{1,100}', code)
                    else 'startup_trace_observation_failed'}
        finally:
            self._stop_process()


def begin_startup_trace(work, progress, round_number):
    try:
        return _StartupProcessTrace(work)
    except Exception as error:
        code = str(error) if isinstance(error, ProbeFailure) else ''
        progress.setdefault('startup_trace_setup', []).append(
            {'round': round_number, 'observation': 'unavailable', 'error_class': type(error).__name__,
             'code': code if re.fullmatch(r'startup_trace_[a-z0-9_]{1,100}', code)
             else 'startup_trace_setup_failed'})
        return None


def filetime_now():
    return 116444736000000000 + time.time_ns() // 100


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
    progress['phase'] = f'cold_{round_number}_standard_user_launch'
    progress['suspended_creation_api'] = 'CreateProcessAsUserW'
    trace = begin_startup_trace(work, progress, round_number)
    try:
        process = start_standard_user(executable, env)
    except BaseException:
        if trace:
            progress.setdefault('startup_process_traces', []).append(
                {'round': round_number, **trace.finish(0, filetime_now())})
        raise
    progress.setdefault('app_launch_security', []).append({'round': round_number, **process.security})
    browser = None
    client = None
    cleanup_time = None
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
    except Exception:
        try:
            progress['startup_diagnostics'] = _startup_diagnostics(process, port, work)
        except Exception as diagnostic_error:
            progress['startup_diagnostics'] = {'observation': 'failed', 'error_class': type(diagnostic_error).__name__}
        raise
    finally:
        try:
            if browser:
                browser.close()
        finally:
            try:
                if client:
                    client.stop()
            finally:
                try:
                    cleanup_time = filetime_now()
                    if process.poll() is None:
                        process.terminate()
                    process.wait(timeout=20)
                    _wait(lambda: _port_closed(port), 15, 'owned_webview_listener_not_closed')
                    progress['last_owned_root_and_listener_cleanup_verified'] = True
                finally:
                    try:
                        if trace:
                            progress.setdefault('startup_process_traces', []).append(
                                {'round': round_number, **trace.finish(process.pid, cleanup_time)})
                    finally:
                        process.close()


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
