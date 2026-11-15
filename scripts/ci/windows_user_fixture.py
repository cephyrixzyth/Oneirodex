"""Disposable Windows CI identity and private desktop; never an operator login."""
from __future__ import annotations

import ntpath
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import uuid

from probe_windows_packaged import runtime_environment, observer_environment, windows_environment_block


class FixtureFailure(RuntimeError):
    def __init__(self, code):
        super().__init__(code if re.fullmatch(r'[a-z][a-z0-9_]{1,120}', code)
                         else 'fixture_operation_failed')


def safe_fixture_diagnostic(raw):
    if not isinstance(raw, dict):
        return {}
    selected = {}
    if raw.get('stage') in ('lookup', 'password', 'create_user', 'membership', 'existing_account',
                           'profile_wait', 'profile_validate', 'profile_delete', 'account_delete', 'verify'):
        selected['stage'] = raw['stage']
    if raw.get('category') in ('ResourceExists', 'PermissionDenied', 'InvalidArgument',
                              'InvalidOperation', 'ObjectNotFound', 'NotSpecified', 'SecurityError'):
        selected['category'] = raw['category']
    if isinstance(raw.get('hresult'), str) and re.fullmatch(r'0x[0-9a-fA-F]{8}', raw['hresult']):
        selected['hresult'] = raw['hresult'].lower()
    return selected


def require_fixture_ci():
    env = os.environ
    if not (os.name == 'nt' and env.get('GITHUB_ACTIONS') == 'true'
            and env.get('RUNNER_OS') == 'Windows'
            and env.get('GITHUB_REPOSITORY') == 'cephyrixzyth/Oneirodex'
            and re.fullmatch(r'[1-9][0-9]*', env.get('GITHUB_RUN_ID', ''))
            and env.get('RUNNER_TEMP')):
        raise FixtureFailure('execution_requires_disposable_windows_ci')


def profile_is_owned(profile, profiles_root, name):
    if not all(isinstance(v, str) and v for v in (profile, profiles_root, name)):
        return False
    if not re.fullmatch(r'odci[a-f0-9]{12}', name):
        return False
    normalized, root = ntpath.normpath(profile), ntpath.normpath(profiles_root)
    if (not ntpath.isabs(normalized) or normalized.startswith('\\\\')
            or not ntpath.isabs(root) or root.startswith('\\\\')
            or ntpath.splitdrive(normalized)[0].lower() != ntpath.splitdrive(root)[0].lower()):
        return False
    leaf = ntpath.basename(normalized).lower()
    return (ntpath.dirname(normalized).lower() == root.lower()
            and (leaf == name or leaf.startswith(name + '.')))


def _inside(path, root):
    if not isinstance(path, str) or not ntpath.isabs(path) or path.startswith('\\\\'):
        return False
    try:
        return ntpath.commonpath([ntpath.normpath(path), root]).lower() == root.lower()
    except ValueError:
        return False


class _OwnedChild:
    def __init__(self, api, handle, pid):
        self.api, self.handle, self.pid = api, handle, pid
        self.security = {'elevated': False, 'integrity_rid': 8192, 'same_fixture_account': True}

    def poll(self):
        return self.api.exit_code(self.handle) if self.api.wait(self.handle, 0) else None

    def wait(self, timeout):
        if not 0 <= timeout <= 180:
            raise FixtureFailure('fixture_wait_out_of_bounds')
        if not self.api.wait(self.handle, int(timeout * 1000)):
            raise subprocess.TimeoutExpired('owned fixture child', timeout)
        return self.api.exit_code(self.handle)

    def terminate(self):
        self.api.terminate(self.handle)

    def close(self):
        if self.handle is None:
            return
        if self.poll() is None:
            self.terminate()
            self.wait(20)
        self.api.close_handle(self.handle)
        self.handle = None


class StandardUserFixture:
    @classmethod
    def open(cls, work):
        require_fixture_ci()
        return cls._open_for_api(work, Path(os.environ['RUNNER_TEMP']), NativeFixtureAPI())

    @classmethod
    def _open_for_api(cls, work, owned_root, api):
        root, path = Path(owned_root).resolve(), Path(work).resolve()
        if path == root or not path.is_relative_to(root) or path.exists():
            raise FixtureFailure('fixture_workspace_not_fresh_or_owned')
        path.mkdir(parents=True, exist_ok=False)
        context = cls(path, api)
        try:
            context._provision()
            return context
        except BaseException as error:
            try:
                context.close()
            except Exception:
                error.add_note('fixture_cleanup_failed')
            raise

    def __init__(self, work, api):
        self.work, self.api = work, api
        self._nonce = uuid.uuid4().hex
        self._name = 'odci' + self._nonce[:12]
        self._marker = 'oneirodex-ci-' + self._nonce
        self._password = 'Aa9!' + secrets.token_hex(24)
        self._sid, self._desktop, self.profile_root = None, None, None
        self.environment, self._children = {}, []
        self._closed, self._ready = False, False
        self.receipt = {'standard_user_verified': False, 'cleanup_verified': False, 'cleanup_errors': []}

    def _validated_state(self, state):
        if not (state.get('sid') == self._sid and state.get('elevated') is False
                and state.get('integrity_rid') == 8192):
            raise FixtureFailure('fixture_child_identity_not_verified')
        profile = state.get('profile_root')
        if not profile_is_owned(profile, state.get('profiles_root'), self._name):
            raise FixtureFailure('fixture_profile_not_owned')
        environment = runtime_environment(state.get('environment', {}))
        values = {k.upper(): v for k, v in environment.items()}
        if (not isinstance(values.get('USERPROFILE'), str)
                or ntpath.normcase(values['USERPROFILE']) != ntpath.normcase(profile)
                or not all(_inside(values.get(key), profile) for key in ('APPDATA', 'LOCALAPPDATA'))):
            raise FixtureFailure('fixture_environment_not_profile_bound')
        if self.profile_root is not None and ntpath.normcase(profile) != ntpath.normcase(self.profile_root):
            raise FixtureFailure('fixture_profile_changed')
        return profile, environment

    def _spawn(self, executable, environment, arguments, bootstrap=False):
        handle, thread, pid = self.api.spawn(self._name, self._password, executable,
                                              arguments, environment, self._desktop[2])
        child = _OwnedChild(self.api, handle, pid)
        self._children.append(child)
        try:
            profile, actual_env = self._validated_state(self.api.state(handle))
            if bootstrap:
                self.profile_root, self.environment = profile, actual_env
            self.api.resume(thread)
            return child
        except BaseException as error:
            try:
                child.close()
            except Exception:
                error.add_note('fixture_child_cleanup_failed')
            raise
        finally:
            self.api.close_handle(thread)

    def _provision(self):
        self._sid = self.api.create_account(self._name, self._password, self._marker)
        if not isinstance(self._sid, str) or not re.fullmatch(r'S-1-5-21-(?:[0-9]+-){3}[0-9]+', self._sid):
            raise FixtureFailure('fixture_account_sid_invalid')
        self._desktop = self.api.open_desktop(self._sid, self._nonce)
        self.api.grant_work(self.work, self._sid)
        child = self._spawn(self.api.bootstrap_executable(), None, ['/d', '/c', 'exit', '0'], bootstrap=True)
        try:
            if child.wait(20) != 0:
                raise FixtureFailure('fixture_profile_bootstrap_failed')
        finally:
            child.close()
        self._ready = True
        self.receipt.update(standard_user_verified=True, profile_environment_verified=True,
                            private_desktop_created=True)

    def start(self, executable, environment, arguments=None):
        if not self._ready or self._closed:
            raise FixtureFailure('fixture_not_ready')
        expected = {k.upper(): v for k, v in self.environment.items()}
        supplied = {k.upper(): v for k, v in environment.items()}
        extra = {'WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS', 'WEBVIEW2_USER_DATA_FOLDER'}
        if (len(supplied) != len(environment) or any(
                key not in extra and (key not in expected or expected[key] != value)
                for key, value in supplied.items())
                or any(supplied.get(key) != value for key, value in expected.items())):
            raise FixtureFailure('fixture_environment_override_rejected')
        windows_environment_block(environment)
        return self._spawn(executable, environment, arguments or [])

    def close(self):
        if self._closed:
            if self.receipt['cleanup_errors']:
                raise FixtureFailure('fixture_cleanup_failed')
            return
        self._closed, self._ready = True, False
        errors = self.receipt['cleanup_errors']
        for child in reversed(self._children):
            try:
                child.close()
            except Exception:
                errors.append('fixture_owned_child_cleanup_failed')
        if errors:
            # A live or unverified child retains its profile/desktop dependencies.
            self._password = None
            raise FixtureFailure('fixture_cleanup_failed')
        if self._desktop is not None:
            try:
                self.api.close_desktop(self._desktop)
            except Exception:
                errors.append('fixture_desktop_cleanup_failed')
        if self._sid is not None:
            try:
                self.api.delete_account(self._name, self._sid, self._marker, self.profile_root)
            except Exception as error:
                errors.append(str(error) if isinstance(error, FixtureFailure) else 'fixture_account_cleanup_failed')
        self._password = None
        self.receipt['cleanup_verified'] = not errors
        if errors:
            raise FixtureFailure('fixture_cleanup_failed')

    def __enter__(self):
        return self

    def __exit__(self, kind, error, traceback):
        try:
            self.close()
        except Exception:
            if error is None:
                raise
            error.add_note('fixture_cleanup_failed')
        return False


class NativeFixtureAPI:
    def __init__(self):
        require_fixture_ci()
        import ctypes as c
        from ctypes import wintypes as w
        from probe_windows_packaged import _WindowsStandardAPI
        self.c, self.w, self.base = c, w, _WindowsStandardAPI()
        self.STARTUPINFO, self.PROCESSINFO = self.base.STARTUPINFO, self.base.PROCESSINFO
        self.user = c.WinDLL('user32', use_last_error=True)
        self.profile = c.WinDLL('userenv', use_last_error=True)
        self.powershell = str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
        self.observer_env = observer_environment(os.environ)

        class SecurityAttributes(c.Structure):
            _fields_ = [('length', w.DWORD), ('descriptor', c.c_void_p), ('inherit', w.BOOL)]
        self.SecurityAttributes = SecurityAttributes
        def bind(library, name, result, arguments):
            call = getattr(library, name)
            call.restype, call.argtypes = result, arguments
            return call
        H, P, D = w.HANDLE, c.c_void_p, w.DWORD
        self._create_logon = bind(self.base.advapi, 'CreateProcessWithLogonW', w.BOOL,
                                 [w.LPCWSTR, w.LPCWSTR, w.LPCWSTR, D, w.LPCWSTR, w.LPWSTR,
                                  D, P, w.LPCWSTR, c.POINTER(self.STARTUPINFO), c.POINTER(self.PROCESSINFO)])
        self._descriptor = bind(self.base.advapi, 'ConvertStringSecurityDescriptorToSecurityDescriptorW',
                                w.BOOL, [w.LPCWSTR, D, c.POINTER(P), P])
        self._free = bind(self.base.kernel, 'LocalFree', P, [P])
        self._sid_string = bind(self.base.advapi, 'ConvertSidToStringSidW', w.BOOL, [P, c.POINTER(P)])
        self._get_station = bind(self.user, 'GetProcessWindowStation', H, [])
        self._set_station = bind(self.user, 'SetProcessWindowStation', w.BOOL, [H])
        self._thread_id = bind(self.base.kernel, 'GetCurrentThreadId', D, [])
        self._get_desktop = bind(self.user, 'GetThreadDesktop', H, [D])
        self._set_desktop = bind(self.user, 'SetThreadDesktop', w.BOOL, [H])
        self._create_station = bind(self.user, 'CreateWindowStationW', H, [w.LPCWSTR, D, D, P])
        self._create_desktop = bind(self.user, 'CreateDesktopW', H, [w.LPCWSTR, P, P, D, D, P])
        self._close_station = bind(self.user, 'CloseWindowStation', w.BOOL, [H])
        self._close_desktop = bind(self.user, 'CloseDesktop', w.BOOL, [H])
        self._profile_path = bind(self.profile, 'GetUserProfileDirectoryW', w.BOOL, [H, w.LPWSTR, c.POINTER(D)])
        self._profiles_path = bind(self.profile, 'GetProfilesDirectoryW', w.BOOL, [w.LPWSTR, c.POINTER(D)])
        self._environment = bind(self.profile, 'CreateEnvironmentBlock', w.BOOL, [c.POINTER(P), H, w.BOOL])
        self._destroy_environment = bind(self.profile, 'DestroyEnvironmentBlock', w.BOOL, [P])

    def _checked(self, result, code):
        if not result:
            raise FixtureFailure(code + '_winerror_' + str(self.c.get_last_error()))

    @staticmethod
    def _account_identity(name, marker, sid=None):
        if (not re.fullmatch(r'odci[a-f0-9]{12}', name)
                or not re.fullmatch(r'oneirodex-ci-[a-f0-9]{32}', marker)
                or (sid is not None and not re.fullmatch(r'S-1-5-21-(?:[0-9]+-){3}[0-9]+', sid))):
            raise FixtureFailure('fixture_account_identity_invalid')

    def _account_command(self, script, payload, code):
        try:
            result = subprocess.run(
                [self.powershell, '-NoProfile', '-NonInteractive', '-Command', script],
                input=json.dumps(payload), env=self.observer_env, capture_output=True,
                encoding='utf-8', timeout=60, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if result.returncode or len(result.stdout) > 4096:
                error = FixtureFailure(code)
                try:
                    raw = json.loads(result.stdout) if len(result.stdout) <= 4096 else {}
                except ValueError:
                    raw = {}
                error.diagnostic = safe_fixture_diagnostic(raw)
                raise error
            return json.loads(result.stdout)
        except (ValueError, subprocess.SubprocessError, OSError):
            raise FixtureFailure(code) from None

    def create_account(self, name, password, marker):
        self._account_identity(name, marker)
        script = r'''
$ErrorActionPreference='Stop'
$p=ConvertFrom-Json ([Console]::In.ReadToEnd());$created=$null;$secure=$null;$stage='lookup'
try {
    if(Get-LocalUser -Name $p.name -ErrorAction SilentlyContinue){
        [Console]::WriteLine('{"stage":"existing_account","category":"ResourceExists"}');exit 2
    }
    $stage='password'
    $secure=ConvertTo-SecureString $p.password -AsPlainText -Force
    $stage='create_user'
    $created=New-LocalUser -Name $p.name -Password $secure -Description $p.marker -UserMayNotChangePassword
    $stage='membership'
    $group=Get-LocalGroup -SID 'S-1-5-32-545'
    Add-LocalGroupMember -Group $group -Member $created -ErrorAction Stop
    [Console]::WriteLine((@{sid=$created.SID.Value}|ConvertTo-Json -Compress))
} catch {
    $diagnostic=@{stage=$stage;category=[string]$_.CategoryInfo.Category;hresult=('0x{0:x8}' -f $_.Exception.HResult)}
    if($created -and $created.Description -eq $p.marker){
        Remove-LocalUser -SID $created.SID -ErrorAction SilentlyContinue
    }
    [Console]::WriteLine(($diagnostic|ConvertTo-Json -Compress))
    exit 1
} finally {
    if($secure){$secure.Dispose()};$p.password=$null
}
'''
        try:
            result = self._account_command(script, {'name': name, 'password': password, 'marker': marker},
                                           'fixture_account_creation_failed')
            sid = result.get('sid')
            self._account_identity(name, marker, sid)
            if sid is None:
                raise FixtureFailure('fixture_account_sid_missing')
            return sid
        except BaseException as error:
            # Covers timeout/transport failure after OS creation, without owning a foreign collision.
            try:
                self.delete_account(name, None, marker, None)
                error.cleanup_verified = True
            except Exception:
                error.cleanup_verified = False
                error.add_note('fixture_unclaimed_account_cleanup_failed')
            raise

    def delete_account(self, name, sid, marker, profile):
        self._account_identity(name, marker, sid)
        script = r'''
$ErrorActionPreference='Stop'
$p=ConvertFrom-Json ([Console]::In.ReadToEnd());$owned=$null;$failed=$false
try {
    $current=Get-LocalUser -Name $p.name -ErrorAction SilentlyContinue
    if($current){
        if($current.Description -ne $p.marker -or ($p.sid -and $current.SID.Value -ne $p.sid)){exit 2}
        $owned=$current
        if(-not $p.sid){$p.sid=$current.SID.Value}
    }
    if($p.sid){
        $root=[Environment]::ExpandEnvironmentVariables((Get-ItemPropertyValue -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList' -Name ProfilesDirectory))
        $root=[IO.Path]::GetFullPath($root).TrimEnd('\')
        $profiles=@()
        for($attempt=0;$attempt -lt 40;$attempt++){
            $profiles=@(Get-CimInstance Win32_UserProfile -Filter ("SID='"+$p.sid+"'"))
            if(-not @($profiles|Where-Object {$_.Loaded}).Count){break}
            Start-Sleep -Milliseconds 250
        }
        foreach($item in $profiles){
            $path=[IO.Path]::GetFullPath($item.LocalPath).TrimEnd('\')
            $leaf=[IO.Path]::GetFileName($path)
            if($item.Loaded -or [IO.Path]::GetDirectoryName($path) -ine $root -or
                -not ($leaf -ieq $p.name -or $leaf.StartsWith($p.name+'.',[StringComparison]::OrdinalIgnoreCase)) -or
                ($p.profile -and $path -ine ([IO.Path]::GetFullPath($p.profile).TrimEnd('\')))) {throw 'profile_identity_mismatch'}
            $item|Remove-CimInstance -ErrorAction Stop
        }
        if(@(Get-CimInstance Win32_UserProfile -Filter ("SID='"+$p.sid+"'")).Count){throw 'profile_remained'}
    }
} catch {$failed=$true}
finally {
    if($owned){
        try {Remove-LocalUser -SID $owned.SID -ErrorAction Stop}catch {$failed=$true}
    }
}
if($failed -or (Get-LocalUser -Name $p.name -ErrorAction SilentlyContinue)){exit 1}
[Console]::WriteLine('{"removed":true}')
'''
        result = self._account_command(script, {'name': name, 'sid': sid, 'marker': marker, 'profile': profile},
                                       'fixture_account_cleanup_failed')
        if result.get('removed') is not True:
            raise FixtureFailure('fixture_account_cleanup_not_verified')

    @contextmanager
    def _security(self, sid):
        c = self.c
        descriptor = c.c_void_p()
        # New objects only; no Everyone or inherited interactive-desktop ACL mutation.
        sddl = f'D:P(A;;GA;;;{sid})(A;;GA;;;SY)(A;;GA;;;BA)S:(ML;;NW;;;ME)'
        self._checked(self._descriptor(sddl, 1, c.byref(descriptor), None), 'fixture_security_descriptor')
        try:
            attributes = self.SecurityAttributes(c.sizeof(self.SecurityAttributes), descriptor, False)
            yield c.byref(attributes)
        finally:
            self._free(descriptor)

    def open_desktop(self, sid, nonce):
        if (not re.fullmatch(r'S-1-5-21-(?:[0-9]+-){3}[0-9]+', sid)
                or not re.fullmatch(r'[a-f0-9]{32}', nonce)):
            raise FixtureFailure('fixture_desktop_identity_invalid')
        original_station, original_desktop = self._get_station(), self._get_desktop(self._thread_id())
        self._checked(original_station and original_desktop, 'fixture_original_desktop')
        station = desktop = None
        name = 'odci-' + nonce
        try:
            with self._security(sid) as security:
                try:
                    station = self._create_station(name, 1, 0xF037F, security)
                    self._checked(station, 'fixture_create_private_station')
                    self._checked(self._set_station(station), 'fixture_select_private_station')
                    desktop = self._create_desktop('private', None, None, 0, 0xF01FF, security)
                    self._checked(desktop, 'fixture_create_private_desktop')
                finally:
                    station_restored = self._set_station(original_station)
                    desktop_restored = self._set_desktop(original_desktop)
                    self._checked(station_restored and desktop_restored, 'fixture_restore_original_desktop')
            return station, desktop, name + '\\private'
        except BaseException:
            if desktop:
                self._close_desktop(desktop)
            if station:
                self._close_station(station)
            raise

    def close_desktop(self, resources):
        desktop_closed = self._close_desktop(resources[1])
        station_closed = self._close_station(resources[0])
        self._checked(desktop_closed and station_closed, 'fixture_close_private_desktop')

    def grant_work(self, work, sid):
        result = subprocess.run([str(Path(os.environ['SystemRoot']) / 'System32/icacls.exe'),
                                 str(work), '/grant', '*' + sid + ':(OI)(CI)M'],
                                env=self.observer_env, capture_output=True, timeout=20,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise FixtureFailure('fixture_work_access_failed')

    def bootstrap_executable(self):
        return Path(os.environ['SystemRoot']) / 'System32/cmd.exe'

    def spawn(self, name, password, executable, arguments, environment, desktop):
        c = self.c
        executable = Path(executable).resolve(strict=True)
        command = subprocess.list2cmdline([str(executable), *arguments])
        if len(command) >= 1024:
            raise FixtureFailure('fixture_command_too_long')
        startup, info = self.STARTUPINFO(), self.PROCESSINFO()
        startup.cb, startup.lpDesktop = c.sizeof(startup), desktop
        block = None if environment is None else c.create_unicode_buffer(windows_environment_block(environment))
        secret = c.create_unicode_buffer(password)
        try:
            self._checked(self._create_logon(name, '.', secret, 1, str(executable),
                                             c.create_unicode_buffer(command), 0x404, block,
                                             str(executable.parent), c.byref(startup), c.byref(info)),
                          'fixture_create_logon_child')
            return info.hProcess, info.hThread, int(info.dwProcessId)
        finally:
            c.memset(c.addressof(secret), 0, c.sizeof(secret))

    def state(self, process):
        c, w = self.c, self.w
        security = self.base.process_security(process)
        token, size, sid_text, environment = w.HANDLE(), w.DWORD(), c.c_void_p(), c.c_void_p()
        self._checked(self.base._open_token(process, 0xA, c.byref(token)), 'fixture_open_child_token')
        try:
            self.base._get_token(token, 1, None, 0, c.byref(size))
            if not 0 < size.value <= 65536:
                raise FixtureFailure('fixture_child_sid_size_invalid')
            user = c.create_string_buffer(size.value)
            self._checked(self.base._get_token(token, 1, user, size.value, c.byref(size)), 'fixture_child_user')
            sid = c.cast(user, c.POINTER(c.c_void_p))[0]
            self._checked(self._sid_string(sid, c.byref(sid_text)), 'fixture_child_sid')
            sid_value = c.wstring_at(sid_text)
            def path(query, *prefix):
                count = w.DWORD()
                query(*prefix, None, c.byref(count))
                if not 0 < count.value <= 32768:
                    raise FixtureFailure('fixture_profile_path_size_invalid')
                value = c.create_unicode_buffer(count.value)
                self._checked(query(*prefix, value, c.byref(count)), 'fixture_profile_path')
                return value.value
            profile_root = path(self._profile_path, token)
            profiles_root = path(self._profiles_path)
            self._checked(self._environment(c.byref(environment), token, False), 'fixture_user_environment')
            chars = c.cast(environment, c.POINTER(c.c_wchar))
            entries, current = [], []
            for index in range(65536):
                char = chars[index]
                if char != '\0':
                    current.append(char)
                elif not current:
                    break
                else:
                    entries.append(''.join(current))
                    current = []
            else:
                raise FixtureFailure('fixture_environment_too_large')
            variables = dict(item.split('=', 1) for item in entries if '=' in item and not item.startswith('='))
            return {**security, 'sid': sid_value, 'profile_root': profile_root,
                    'profiles_root': profiles_root, 'environment': variables}
        finally:
            if environment:
                self._destroy_environment(environment)
            if sid_text:
                self._free(sid_text)
            self.base.close_handle(token)

    def resume(self, thread):
        self.base.resume(thread)

    def wait(self, process, milliseconds):
        return self.base.wait(process, milliseconds)

    def exit_code(self, process):
        return self.base.exit_code(process)

    def terminate(self, process):
        self.base.terminate(process)

    def close_handle(self, handle):
        self.base.close_handle(handle)
