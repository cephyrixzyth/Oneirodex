"""Real file-manager context and location-bar evidence, disposable CI only."""
import configparser
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import stat
import sys
import urllib.parse
import urllib.request

from probe_linux_packaged import ProbeFailure, require_ci_execution
from linux_packaged_native import process_group_members, wait_for
from linux_game_journey import ProcAPI, verified_pidfd


def desktop_handler(text):
    try:
        parser = configparser.ConfigParser(interpolation=None)
        parser.read_string(text)
        entry = parser['Desktop Entry']
        argv = shlex.split(entry['Exec'])
        if (entry.get('Type') != 'Application' or 'inode/directory' not in entry.get('MimeType', '').split(';')
                or not argv or Path(argv[0]).name.lower() != 'thunar'):
            raise ValueError()
        return argv[0]
    except (ValueError, KeyError, configparser.Error):
        raise ProbeFailure('linux_directory_handler_not_thunar') from None


def location_matches(text, expected):
    text = text.strip()
    if not text or len(text) > 8192 or any(value in text for value in ('\0', '\n', '\r')):
        return False
    try:
        parsed = urllib.parse.urlsplit(text)
        if parsed.scheme == 'file':
            if parsed.netloc or parsed.query or parsed.fragment: return False
            candidate = Path(urllib.request.url2pathname(parsed.path))
        elif parsed.scheme and not (len(text) >= 3 and text[1] == ':' and text[2] in '/\\'):
            return False
        else:
            candidate = Path(text)
        return candidate.is_absolute() and candidate.resolve() == expected.resolve()
    except (OSError, ValueError):
        return False


def window_ids(raw):
    if len(raw) > 4096: raise ProbeFailure('linux_manager_window_list_too_large')
    lines = raw.decode('ascii').splitlines()
    if len(lines) > 16 or any(not re.fullmatch(r'[1-9][0-9]{0,9}', line) for line in lines):
        raise ProbeFailure('linux_manager_window_identifier_invalid')
    values = [int(line) for line in lines]
    if len(set(values)) != len(values) or any(value >= 2**32 for value in values):
        raise ProbeFailure('linux_manager_window_identifier_invalid')
    return values


class RevealContext:
    def __init__(self, native, progress):
        require_ci_execution(sys.platform, os.environ, getattr(os, 'geteuid', lambda: -1)())
        self.native, self.progress, self.api = native, progress, ProcAPI()
        self.guardians, self.manager_handle = [], None
        self.manager_attempted, self.closed = False, False
        self.binary, self.manager_pid = None, None

    def owner(self, name):
        value = self.native.command(['gdbus','call','--session','--dest','org.freedesktop.DBus',
            '--object-path','/org/freedesktop/DBus','--method','org.freedesktop.DBus.GetConnectionUnixProcessID',name],
            'linux_manager_bus_owner_failed', allow_failure=True)
        if value.returncode: return None
        match = re.fullmatch(r'\(uint32 ([1-9][0-9]*),\)\s*', value.stdout.decode('ascii'))
        return int(match.group(1)) if match else None

    def _spawn(self, argv):
        guardian = self.native.spawn(argv)
        self.guardians.append(guardian)
        self.native.support.append(guardian)
        return guardian

    def _root_binary(self, path):
        path = path.resolve(strict=True)
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o6000:
            raise ProbeFailure('linux_manager_binary_not_root_owned')
        return path

    def start(self):
        self.progress['phase'] = 'linux_real_manager_prerequisites'
        versions = {}
        for package in ('thunar','xfconf','xdotool','xclip','xdg-utils','x11-utils'):
            value = self.native.command(['dpkg-query','-W','-f=${Version}',package], 'linux_manager_package_missing').stdout.decode().strip()
            if not re.fullmatch(r'[a-zA-Z0-9.+:~_-]{1,100}', value):
                raise ProbeFailure('linux_manager_package_version_invalid')
            versions[package] = value
        paths = self.native.command(['dpkg-query','-L','thunar'], 'linux_manager_package_inventory_failed').stdout.decode().splitlines()
        selected = []
        for item in paths:
            path = Path(item)
            if path.parent != Path('/usr/share/applications') or path.suffix != '.desktop': continue
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_size > 65536:
                raise ProbeFailure('linux_manager_desktop_entry_not_owned')
            try: selected.append((path, desktop_handler(path.read_text(encoding='utf-8'))))
            except ProbeFailure: continue
        if len(selected) != 1: raise ProbeFailure('linux_manager_directory_handler_not_unique')
        desktop, command = selected[0]
        executable = shutil.which(command, path=self.native.env['PATH'])
        if not executable: raise ProbeFailure('linux_manager_executable_unavailable')
        self.binary = self._root_binary(Path(executable))
        help_text = self.native.command([str(self.binary),'--help'], 'linux_manager_help_unavailable').stdout.decode()
        if '--daemon' not in help_text or '--quit' not in help_text:
            raise ProbeFailure('linux_manager_foreground_contract_unavailable')
        conf_paths = self.native.command(['dpkg-query','-L','xfconf'], 'linux_xfconf_inventory_failed').stdout.decode().splitlines()
        conf = [Path(path) for path in conf_paths if Path(path).name == 'xfconfd']
        if len(conf) != 1: raise ProbeFailure('linux_xfconf_daemon_not_unique')
        conf = self._root_binary(conf[0])
        if '--no-daemon' not in self.native.command([str(conf),'--help'], 'linux_xfconf_help_unavailable').stdout.decode():
            raise ProbeFailure('linux_xfconf_foreground_unavailable')
        self.progress['phase'] = 'linux_owned_xfconf_start'
        conf_guardian = self._spawn([str(conf),'--no-daemon'])
        wait_for(lambda: self.owner('org.xfce.Xfconf') is not None, 15, 'linux_owned_xfconf_not_ready')
        if self.owner('org.xfce.Xfconf') not in {pid for pid, _ in process_group_members(conf_guardian.pid)}:
            raise ProbeFailure('linux_xfconf_not_in_owned_group')
        self.native.command(['xdg-mime','default',desktop.name,'inode/directory'], 'linux_owned_mime_default_failed')
        default = self.native.command(['xdg-mime','query','default','inode/directory'], 'linux_owned_mime_query_failed').stdout.decode().strip()
        if default != desktop.name: raise ProbeFailure('linux_owned_mime_default_not_verified')
        self.progress['phase'] = 'linux_owned_thunar_start'
        self.manager_attempted = True
        guardian = self._spawn([str(self.binary),'--daemon'])
        wait_for(lambda: self.owner('org.xfce.Thunar') is not None, 15, 'linux_owned_manager_not_ready')
        self.manager_pid = self.owner('org.xfce.Thunar')
        self.manager_handle = verified_pidfd(self.manager_pid, os.geteuid(), None, [str(self.binary),'--daemon'], self.api)
        if self.manager_pid not in {pid for pid, _ in process_group_members(guardian.pid)}:
            raise ProbeFailure('linux_manager_not_in_owned_group')
        self.progress['file_manager_versions'] = versions
        self.progress['owned_real_file_manager_ready'] = True

    def windows(self):
        result = self.native.command(['xdotool','search','--onlyvisible','--class','Thunar'],
                                     'linux_manager_window_query_failed', allow_failure=True)
        if result.returncode not in (0,1) or (result.returncode == 1 and result.stdout):
            raise ProbeFailure('linux_manager_window_query_failed')
        return window_ids(result.stdout)

    def reveal(self, game_uuid, expected, label):
        if label not in ('online','denied','offline') or self.windows():
            raise ProbeFailure('linux_manager_reveal_baseline_not_empty')
        self.progress['phase'] = 'linux_real_reveal_'+label
        expected = expected.resolve(strict=True)
        if not expected.is_relative_to((self.native.app_directory/'installs').resolve(strict=True)):
            raise ProbeFailure('linux_manager_target_not_owned_install')
        clicked = self.native.execute_js('''const card=Array.from(document.querySelectorAll('#library [data-game-uuid]'))
          .find(item=>item.dataset.gameUuid===arguments[0]);const button=card?.querySelector('[data-action="reveal_path"]');
          if(!(button instanceof HTMLButtonElement)||button.disabled)return false;button.click();return true;''', [game_uuid])
        if clicked is not True: raise ProbeFailure('linux_real_reveal_button_unavailable')
        observed = []
        def opened():
            values = self.windows()
            if len(values) != 1: return False
            wid = str(values[0])
            pid = self.native.command(['xdotool','getwindowpid',wid], 'linux_manager_window_owner_unavailable').stdout.decode().strip()
            title = self.native.command(['xdotool','getwindowname',wid], 'linux_manager_window_title_unavailable').stdout.decode()
            if pid != str(self.manager_pid) or expected.name not in title: return False
            observed.append(wid)
            return True
        wait_for(opened, 20, 'linux_real_manager_window_target_not_verified')
        wid = observed[-1]
        self.native.command(['xdotool','windowfocus','--sync',wid], 'linux_owned_manager_focus_failed')
        focused = self.native.command(['xdotool','getwindowfocus'], 'linux_owned_manager_focus_query_failed').stdout.decode().strip()
        if focused != wid: raise ProbeFailure('linux_owned_manager_focus_not_verified')
        for key in ('ctrl+l','ctrl+a'):
            self.native.command(['xdotool','key','--clearmodifiers',key], 'linux_owned_manager_location_shortcut_failed')
        challenge = 'oneirodex-ci-'+secrets.token_hex(16)
        self.native.command(['xdotool','type','--clearmodifiers','--delay','1',challenge], 'linux_owned_manager_challenge_type_failed')
        self.native.command(['xdotool','key','--clearmodifiers','ctrl+a','ctrl+c'], 'linux_owned_manager_challenge_copy_failed')
        def selection_matches(check):
            try:
                result = self.native.command(['xclip','-selection','clipboard','-out'],
                                             'linux_owned_manager_location_read_failed', timeout=2, allow_failure=True)
                return result.returncode == 0 and len(result.stdout) <= 8192 and check(result.stdout.decode())
            except ProbeFailure:
                return False
        wait_for(lambda: selection_matches(lambda value: value.strip() == challenge),
                 5, 'linux_owned_manager_challenge_not_copied')
        self.native.command(['xdotool','key','--clearmodifiers','Escape','ctrl+l','ctrl+a','ctrl+c'],
                            'linux_owned_manager_location_restore_failed')
        wait_for(lambda: selection_matches(lambda value: location_matches(value, expected)),
                 5, 'linux_real_manager_location_mismatch')
        self.progress.setdefault('reveal_checks', {})[label+'_real_window_and_exact_location'] = True
        self.native.command(['xdotool','key','--clearmodifiers','Escape','ctrl+w'], 'linux_owned_manager_close_window_failed')
        wait_for(lambda: not self.windows(), 10, 'linux_owned_manager_window_not_closed')

    def close(self):
        if self.closed: return
        errors = []
        if self.manager_handle is not None:
            try:
                self.native.command([str(self.binary),'--quit'], 'linux_owned_manager_quit_failed', timeout=10)
                wait_for(lambda: self.api.exited(self.manager_handle), 10, 'linux_owned_manager_exit_not_verified')
            except Exception:
                errors.append('linux_owned_manager_exit_not_verified')
                try: self.api.terminate(self.manager_handle)
                except OSError: pass
            finally:
                try: self.api.close(self.manager_handle)
                except OSError: errors.append('linux_owned_manager_pidfd_close_failed')
        elif self.manager_attempted:
            errors.append('linux_owned_manager_identity_unverified')
        for guardian in reversed(self.guardians):
            try: self.native.stop(guardian)
            except Exception: errors.append('linux_owned_manager_group_cleanup_failed')
        self.closed = True
        self.progress['file_manager_cleanup_verified'] = not errors
        if errors: raise ProbeFailure(errors[0])
