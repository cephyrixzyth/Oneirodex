"""Native Linux CI operations. Importing this module creates no resources."""
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from probe_linux_packaged import BINARY_DIGEST, ProbeFailure, require_ci_execution
from linux_packaged_runtime import runtime_environment

GUARDIAN_CODE = '''import signal, subprocess, sys, time
finish = False
def stop(signum, frame):
    global finish
    finish = True
signal.signal(signal.SIGTERM, lambda signum, frame: None)
signal.signal(signal.SIGUSR1, stop)
child = subprocess.Popen(sys.argv[1:])
while not finish:
    child.poll()
    time.sleep(0.1)
'''


def wait_for(check, seconds, code):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.2)
    raise ProbeFailure(code)


def process_group_members(group):
    members = []
    for directory in Path('/proc').iterdir():
        if not directory.name.isdigit():
            continue
        try:
            fields = (directory/'stat').read_text().rsplit(')', 1)[1].split()
            if int(fields[2]) == group and fields[0] != 'Z':
                members.append((int(directory.name), fields[19]))
        except (OSError, ValueError, IndexError):
            continue
    return members


def listener_owned(port, group, *, allow_wildcard=False):
    inodes = []
    for table in ('tcp', 'tcp6'):
        for line in (Path('/proc/net')/table).read_text().splitlines()[1:]:
            fields = line.split()
            address, number = fields[1].split(':')
            if int(number, 16) == port and fields[3] == '0A':
                allowed = ('0100007F','00000000') if allow_wildcard else ('0100007F',)
                if table != 'tcp' or address not in allowed:
                    return False
                inodes.append(fields[9])
    if not inodes:
        return False
    owned = set()
    for pid, started in process_group_members(group):
        directory = Path('/proc')/str(pid)
        try:
            if directory.stat().st_uid != os.geteuid():
                continue
            sockets = set()
            for fd in (directory/'fd').iterdir():
                try:
                    sockets.add(os.readlink(fd))
                except OSError:
                    continue  # A different descriptor closing must not hide an observed listener.
            current = (directory/'stat').read_text().rsplit(')', 1)[1].split()
            if current[19] == started:
                owned.update(value[8:-1] for value in sockets if value.startswith('socket:['))
        except (OSError, ValueError, IndexError):
            continue
    return all(inode in owned for inode in inodes)


def free_port():
    with socket.socket() as connection:
        connection.bind(('127.0.0.1', 0))
        return connection.getsockname()[1]


def port_closed(port):
    with socket.socket() as connection:
        connection.settimeout(0.2)
        return connection.connect_ex(('127.0.0.1', port)) != 0


class NativeLinuxAPI:
    def __init__(self, work, progress):
        require_ci_execution(sys.platform, os.environ, getattr(os, 'geteuid', lambda: -1)())
        self.work, self.progress, self.data_root = work, progress, work/'data'
        self.env = runtime_environment(work)
        for key in ('HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME', 'XDG_RUNTIME_DIR', 'TMPDIR'):
            Path(self.env[key]).mkdir(mode=0o700)
        self.driver = Path(os.environ['RUNNER_TEMP'])/'oneirodex-tauri-driver/bin/tauri-driver'
        self.executable = Path('/usr/bin/oneirodex-desktop')
        self.support, self.active, self.ports, self.session = [], None, [], None
        self.log, self.log_file, self.round_number = None, None, None
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        progress.update(platform='Linux', effective_uid_nonzero=True, tauri_driver_version='2.1.0',
                        process_cleanup_scope='Owned session/process groups and explicit driver ports; not product game-launch identity.')

    def command(self, args, code, timeout=60, allow_failure=False):
        try:
            result = subprocess.run(args, env=self.env, capture_output=True, timeout=timeout)
        except subprocess.SubprocessError:
            raise ProbeFailure(code) from None
        if result.returncode and not allow_failure:
            raise ProbeFailure(code + '_exit_' + str(result.returncode & 0xFFFFFFFF))
        return result

    def present(self):
        code = self.command(['dpkg-query', '-W', 'oneirodex'], 'linux_package_query_failed', allow_failure=True).returncode
        if code not in (0, 1):
            raise ProbeFailure('linux_package_query_failed')
        return code == 0

    def install(self, deb):
        metadata = self.command(['dpkg-deb', '-f', str(deb), 'Package', 'Version', 'Architecture'], 'linux_deb_metadata_failed').stdout.decode()
        if metadata.splitlines() != ['Package: oneirodex', 'Version: 1.1.9', 'Architecture: amd64']:
            raise ProbeFailure('linux_deb_metadata_not_qualified')
        self.progress['installer_executed'] = True
        self.command(['sudo', '-n', 'dpkg', '-i', str(deb)], 'linux_package_install_failed', timeout=180)

    def verify_binary(self):
        info = self.executable.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o6000
                or hashlib.sha256(self.executable.read_bytes()).hexdigest() != BINARY_DIGEST):
            raise ProbeFailure('linux_installed_binary_not_qualified')
        self.progress['installed_binary_sha256'] = BINARY_DIGEST
        versions = {}
        for package in ('webkit2gtk-driver', 'libwebkit2gtk-4.1-0'):
            value = self.command(['dpkg-query', '-W', '-f=${Version}', package], 'linux_tool_version_unavailable').stdout.decode().strip()
            if not re.fullmatch(r'[a-zA-Z0-9.+:~_-]{1,100}', value):
                raise ProbeFailure('linux_tool_version_invalid')
            versions[package] = value
        self.progress['native_package_versions'] = versions
        self.progress['tauri_driver_sha256'] = hashlib.sha256(self.driver.read_bytes()).hexdigest()

    def spawn(self, args, output=None, *, input_pipe=False):
        return subprocess.Popen([sys.executable, '-c', GUARDIAN_CODE, *args], env=self.env,
                                stdin=subprocess.PIPE if input_pipe else subprocess.DEVNULL,
                                stdout=output or subprocess.DEVNULL, stderr=output or subprocess.DEVNULL,
                                start_new_session=True)

    def stop(self, process):
        # The guardian stays alive/unreaped until the last numeric group signal is sent.
        # Never signal a group after its leader was reaped: its numeric ID could be reused.
        if process.returncode is not None:
            if process_group_members(process.pid):
                raise ProbeFailure('linux_group_leader_already_reaped')
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            wait_for(lambda: all(pid == process.pid for pid, _ in process_group_members(process.pid)),
                     10, 'linux_owned_group_not_stopped')
            try:
                os.kill(process.pid, signal.SIGUSR1)
            except ProcessLookupError:
                pass
        except ProbeFailure:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait(timeout=10)
        wait_for(lambda: not process_group_members(process.pid), 10, 'linux_owned_group_not_stopped')

    def start_context(self):
        for number in range(200, 1000):
            if not Path('/tmp/.X11-unix/X'+str(number)).exists() and not Path('/tmp/.X'+str(number)+'-lock').exists():
                break
        else:
            raise ProbeFailure('linux_owned_display_unavailable')
        authority = self.work/'Xauthority'
        self.command(['xauth', '-f', str(authority), 'add', ':'+str(number), '.', secrets.token_hex(16)], 'linux_xauthority_failed')
        self.env.update(DISPLAY=':'+str(number), XAUTHORITY=str(authority))
        display = self.spawn(['Xvfb', self.env['DISPLAY'], '-screen', '0', '1280x800x24', '-nolisten', 'tcp', '-auth', str(authority)])
        self.support.append(display)
        wait_for(lambda: Path('/tmp/.X11-unix/X'+str(number)).exists(),
                 15, 'linux_owned_display_not_ready')
        bus_socket = self.work/'dbus.sock'
        self.env['DBUS_SESSION_BUS_ADDRESS'] = 'unix:path='+str(bus_socket)
        bus = self.spawn(['dbus-daemon', '--session', '--nofork', '--nopidfile', '--address='+self.env['DBUS_SESSION_BUS_ADDRESS']])
        self.support.append(bus)
        wait_for(lambda: bus_socket.exists(), 15, 'linux_owned_dbus_not_ready')
        self.progress['owned_display_and_dbus_started'] = True

    def start_secret_service(self):
        control = self.work/'runtime/keyring'
        control.mkdir(mode=0o700)
        process = self.spawn(['gnome-keyring-daemon','--foreground','--components=secrets','--unlock',
                              '--control-directory='+str(control)],input_pipe=True)
        self.support.append(process)  # Own the guardian before any pipe operation can fail.
        try:
            process.stdin.write(secrets.token_urlsafe(40).encode())
            process.stdin.close()
        except OSError:
            raise ProbeFailure('linux_secret_service_unlock_transport_failed') from None
        def ready():
            result = self.command(['gdbus','call','--session','--dest','org.freedesktop.DBus',
                '--object-path','/org/freedesktop/DBus','--method','org.freedesktop.DBus.NameHasOwner',
                'org.freedesktop.secrets'],'linux_secret_service_query_failed',allow_failure=True)
            return result.returncode == 0 and result.stdout.strip() == b'(true,)'
        wait_for(ready,20,'linux_owned_secret_service_not_ready')
        version = self.command(['dpkg-query','-W','-f=${Version}','gnome-keyring'],
                               'linux_secret_service_version_unavailable').stdout.decode().strip()
        if not re.fullmatch(r'[a-zA-Z0-9.+:~_-]{1,100}',version):
            raise ProbeFailure('linux_secret_service_version_invalid')
        self.progress.update(secret_service_owned_bus_ready=True,secret_service_package_version=version)

    def request(self, method, suffix, payload=None):
        if not self.active or not all(listener_owned(port, self.active.pid) for port in self.ports):
            raise ProbeFailure('linux_webdriver_listener_not_owned')
        address = 'http://127.0.0.1:'+str(self.ports[0])+suffix
        assert ipaddress.ip_address(urllib.parse.urlsplit(address).hostname).is_loopback
        body = None if payload is None else json.dumps(payload).encode()
        request = urllib.request.Request(address, data=body, method=method, headers={'Content-Type': 'application/json'})
        try:
            with self.opener.open(request, timeout=65) as response:
                data = response.read(1024*1024+1)
        except urllib.error.HTTPError as error:
            raise ProbeFailure('linux_webdriver_http_'+str(error.code)) from None
        except (OSError, urllib.error.URLError):
            raise ProbeFailure('linux_webdriver_transport_failed') from None
        if len(data) > 1024*1024:
            raise ProbeFailure('linux_webdriver_response_too_large')
        return json.loads(data)['value']

    def open_round(self, number):
        self.round_number = number
        self.ports = [free_port(), free_port()]
        if self.ports[0] == self.ports[1]:
            raise ProbeFailure('linux_webdriver_port_collision')
        self.log_file = self.work/('driver-round-'+str(number)+'.log')
        self.log = self.log_file.open('xb')
        self.active = self.spawn([str(self.driver), '--port', str(self.ports[0]), '--native-port', str(self.ports[1]),
                                  '--native-host', '127.0.0.1'], self.log)
        wait_for(lambda: all(listener_owned(port, self.active.pid) for port in self.ports),
                 30, 'linux_webdriver_not_ready_or_owned')
        value = self.request('POST', '/session', {'capabilities': {'alwaysMatch': {
            'browserName': 'wry', 'tauri:options': {'application': str(self.executable)}}}})
        session = value.get('sessionId')
        if not isinstance(session, str) or not re.fullmatch(r'[a-zA-Z0-9-]{1,128}', session):
            raise ProbeFailure('linux_webdriver_session_invalid')
        self.session = '/session/'+session
        self.request('POST', self.session+'/timeouts', {'script': 30000, 'pageLoad': 30000, 'implicit': 0})

    def execute_js(self,script,args=None):
        return self.request('POST',self.session+'/execute/sync',{'script':script,'args':args or []})

    def execute_async(self,script,args=None):
        return self.request('POST',self.session+'/execute/async',{'script':script,'args':args or []})

    def round(self, number):
        self.open_round(number)
        script = '''const done = arguments[arguments.length - 1]; (async () => {
          const ipc = window.__TAURI_INTERNALS__;
          if (!ipc || typeof ipc.invoke !== 'function') return {bridge: false};
          const config = await ipc.invoke('load_config');
          const directory = await ipc.invoke('get_app_subdir', {subdir: 'installs'});
          let denied = false;
          try { await ipc.invoke('get_app_subdir', {subdir: '..'}); } catch { denied = true; }
          return {bridge: true, fresh: !config.base_url && !config.token,
            heading: [...document.querySelectorAll('h1,h2')].some(e => e.textContent.trim() === 'Oneirodex Desktop'),
            form: !!document.querySelector('#connect-form'), emptyToken: document.querySelector('#token').value.length === 0,
            url: location.href, directory, parentDenied: denied};
        })().then(done, () => done({bridge: false}));'''
        checks = self.request('POST', self.session+'/execute/async', {'script': script, 'args': []})
        if not all(checks.get(key) is True for key in ('bridge','fresh','heading','form','emptyToken','parentDenied')):
            raise ProbeFailure('linux_bundled_ui_or_native_ipc_failed')
        url = urllib.parse.urlsplit(checks.get('url',''))
        if (url.scheme, url.hostname) != ('tauri', 'localhost'):
            raise ProbeFailure('linux_renderer_not_bundled_app')
        apps = [pid for pid, _ in process_group_members(self.active.pid)
                if (Path('/proc')/str(pid)/'exe').resolve() == self.executable]
        if len(apps) != 1 or (Path('/proc')/str(apps[0])).stat().st_uid != os.geteuid():
            raise ProbeFailure('linux_actual_app_identity_not_verified')
        return checks['directory'], {'bundled_renderer':True,'native_ipc':True,'parent_directory_denied':True,
                                     'ordinary_user':True,'listener_ownership_verified':True}

    def stop_round(self):
        error = None
        try:
            if self.session and self.active:
                try:
                    self.request('DELETE', self.session)
                except Exception:
                    pass  # Held process-group cleanup and explicit port closure are still mandatory.
            if self.active:
                self.stop(self.active)
                for port in self.ports:
                    wait_for(lambda: port_closed(port), 10, 'linux_owned_listener_not_closed')
        except Exception as failed:
            error = failed
        finally:
            self.session = None
            if error is None:
                self.active = None
            if self.log:
                self.log.close(); self.log = None
            if self.log_file:
                try:
                    with self.log_file.open('rb') as source:
                        data = source.read(65537)
                    prefix = data[:65536]; text = prefix.decode(errors='replace').lower()
                    categories = ('permission denied','cannot open display','not found','failed to create','automation','crash','sandbox')
                    self.progress.setdefault('selected_driver_logs', []).append({
                        'round':self.round_number,'prefix_bytes':len(prefix),'truncated':len(data)>65536,
                        'prefix_sha256':hashlib.sha256(prefix).hexdigest(),
                        'matched_categories':[value.replace(' ','_') for value in categories if value in text],
                        'limits':'Static selected terms, not a causal diagnosis; raw text remains on disposable runner.'})
                except OSError:
                    self.progress.setdefault('selected_driver_logs', []).append({'round':self.round_number,'observation':'unavailable'})
                finally:
                    self.log_file = None
        if error:
            raise error

    def stop_context(self):
        failures = []
        try:
            self.stop_round()
        except Exception:
            failures.append(True)
        for process in reversed(self.support):
            try:
                self.stop(process)
            except Exception:
                failures.append(True)
        if failures:
            raise ProbeFailure('linux_owned_context_not_stopped')

    def uninstall(self):
        self.command(['sudo', '-n', 'dpkg', '--purge', 'oneirodex'], 'linux_package_uninstall_failed', timeout=120)

    def absent(self):
        return not self.present() and not self.executable.exists()
