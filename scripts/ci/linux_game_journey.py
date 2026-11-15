"""Actual installed wrapper/family/recovery evidence on disposable Linux CI."""
import json
import os
from pathlib import Path
import re
import secrets
import select
import signal
import stat
import sys

from probe_linux_packaged import ProbeFailure, require_ci_execution
from linux_packaged_native import wait_for


class ProcAPI:
    def snapshot(self, pid):
        root = Path('/proc')/str(pid)
        with (root/'cmdline').open('rb') as source:
            raw = source.read(8193)
        if len(raw) > 8192:
            raise ProbeFailure('linux_game_argv_too_large')
        fields = (root/'stat').read_text(encoding='ascii').rsplit(')', 1)[1].split()
        return {'uid': root.stat().st_uid, 'start': fields[19],
                'session': int(fields[3]), 'exe': str((root/'exe').resolve(strict=True)),
                'cwd': str((root/'cwd').resolve(strict=True)),
                'argv': [part.decode() for part in raw.rstrip(b'\0').split(b'\0')]}

    def open(self, pid): return os.pidfd_open(pid)
    def close(self, handle): os.close(handle)
    def exited(self, handle): return bool(select.select([handle], [], [], 0)[0])
    def terminate(self, handle): signal.pidfd_send_signal(handle, signal.SIGTERM)


def verified_pidfd(pid, uid, cwd, argv, api=None):
    api = api or ProcAPI()
    if not isinstance(pid, int) or isinstance(pid, bool) or not 1 < pid < 2**31:
        raise ProbeFailure('linux_game_pid_invalid')
    before = api.snapshot(pid)
    if (before.get('uid') != uid or before.get('argv') != argv
            or (cwd is not None and Path(before.get('cwd', '')) != cwd)
            or not re.fullmatch(r'[1-9][0-9]*', before.get('start', ''))):
        raise ProbeFailure('linux_game_process_not_owned')
    handle = api.open(pid)
    try:
        if api.snapshot(pid) != before or api.exited(handle):
            raise ProbeFailure('linux_game_pid_changed_during_acquisition')
    except BaseException:
        api.close(handle)
        raise
    return handle


def require_launch(value, game_uuid):
    if (not isinstance(value, dict) or value.get('supported') is not True
            or value.get('unverified') != 0 or not isinstance(value.get('launches'), list)):
        raise ProbeFailure('linux_game_inventory_not_verified')
    matches = [row for row in value['launches'] if isinstance(row, dict) and row.get('game_uuid') == game_uuid]
    if len(matches) != 1:
        raise ProbeFailure('linux_game_launch_not_unique')
    row = matches[0]
    if (not isinstance(row.get('pid'), int) or isinstance(row['pid'], bool) or not 1 < row['pid'] < 2**31
            or not isinstance(row.get('launch_id'), str)
            or not re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}', row['launch_id'])):
        raise ProbeFailure('linux_game_launch_identity_invalid')
    return row


def session_projection(rows, adult_id):
    if any(row.status not in ('active', 'ended', 'orphaned') for row in rows):
        raise ProbeFailure('linux_game_session_status_unknown')
    return {'total': len(rows), **{name: sum(row.status == name for row in rows) for name in ('active', 'ended', 'orphaned')},
            'adult_owned': all(row.user_id == adult_id for row in rows),
            'desktop_only': all(row.client == 'desktop' for row in rows),
            'active_heartbeat_observed': any(row.status == 'active' and row.last_heartbeat_at is not None
                                           and row.last_heartbeat_at > row.started_at for row in rows)}


class GameFixture:
    def __init__(self, native, progress):
        require_ci_execution(sys.platform, os.environ, getattr(os, 'geteuid', lambda: -1)())
        self.native, self.progress, self.api = native, progress, ProcAPI()
        self.root = Path(native.env['HOME']).resolve(strict=True)/'.oneirodex-ci-game'
        self.root.mkdir(mode=0o700)
        self.nonce = secrets.token_hex(16)
        self.handles, self.stopping = [], False
        self.launched, self.cleaned = False, False
        with (self.root/'next').open('x', encoding='ascii') as output:
            output.write(self.nonce+'\n')

    def read_pid(self, label):
        path = self.root/(label+'-'+self.nonce+'.pid')
        if not path.exists(): return None
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_size > 32 or path.resolve(strict=True) != path):
            raise ProbeFailure('linux_game_marker_not_owned')
        text = path.read_text(encoding='ascii').strip()
        return int(text) if re.fullmatch(r'[1-9][0-9]{0,9}', text) else None

    def attach_child(self, entry):
        wait_for(lambda: self.read_pid('child') is not None, 30, 'linux_game_child_marker_missing')
        pid = self.read_pid('child')
        handle = verified_pidfd(pid, os.geteuid(), entry.parent, ['/bin/sh', str(entry), 'child'], self.api)
        self.handles.append(handle)
        snapshot = self.api.snapshot(pid)
        if snapshot['session'] != pid or snapshot['exe'] != str(Path('/bin/sh').resolve(strict=True)):
            raise ProbeFailure('linux_game_child_not_detached_shell')
        return pid

    def attach_supervisor(self, record, game_uuid, entry):
        root = self.native.app_directory/'launches'/record['launch_id']
        request_path = root/'request.json'
        if (root.resolve(strict=True) != root or not stat.S_ISREG(request_path.lstat().st_mode)
                or request_path.stat().st_size > 16384):
            raise ProbeFailure('linux_game_supervisor_request_not_owned')
        request = json.loads(request_path.read_text(encoding='utf-8'))
        if (request.get('launch_id') != record['launch_id'] or request.get('game_uuid') != game_uuid
                or request.get('executable') != str(entry)
                or request.get('install_root') != str(self.native.app_directory/'installs')):
            raise ProbeFailure('linux_game_supervisor_request_mismatch')
        expected = [str(self.native.executable), '--oneirodex-launch-supervisor', str(root)]
        matches = []
        for proc in Path('/proc').iterdir():
            if not proc.name.isdecimal(): continue
            try:
                snapshot = self.api.snapshot(int(proc.name))
                if (snapshot['uid'] == os.geteuid() and snapshot['argv'] == expected
                        and snapshot['exe'] == str(self.native.executable.resolve(strict=True))):
                    matches.append(int(proc.name))
            except (OSError, ValueError, UnicodeError, IndexError):
                continue
        if len(matches) != 1:
            raise ProbeFailure('linux_game_supervisor_process_not_unique')
        self.handles.append(verified_pidfd(matches[0], os.geteuid(), None, expected, self.api))

    def require_live(self):
        if len(self.handles) != 2 or any(self.api.exited(handle) for handle in self.handles):
            raise ProbeFailure('linux_game_family_did_not_survive')

    def stop(self):
        if self.cleaned: return
        if not self.stopping:
            self.stopping = True
            with (self.root/('stop-'+self.nonce)).open('xb') as output: output.write(b'')
        errors = []
        if self.launched and len(self.handles) != 2:
            errors.append('linux_game_family_cleanup_unverified')
        for handle in self.handles:
            try:
                wait_for(lambda: self.api.exited(handle), 10, 'linux_game_cooperative_exit_not_verified')
            except ProbeFailure:
                errors.append('linux_game_cooperative_exit_not_verified')
                try:
                    self.api.terminate(handle)
                    wait_for(lambda: self.api.exited(handle), 10, 'linux_game_pidfd_cleanup_failed')
                except Exception:
                    errors.append('linux_game_pidfd_cleanup_failed')
            finally:
                try: self.api.close(handle)
                except OSError: errors.append('linux_game_pidfd_close_failed')
        self.handles.clear()
        self.cleaned = True
        self.progress['game_fixture_cleanup_verified'] = not errors
        if errors: raise ProbeFailure(errors[0])


def native_inventory(native, profile):
    return native.execute_async('''const done=arguments[arguments.length-1];
      window.__TAURI_INTERNALS__.invoke('list_launches',{profileBinding:arguments[0]})
      .then(done,()=>done({supported:false,launches:[],unverified:1}));''', [profile])


def wait_native_launch(native, profile, game_uuid):
    observed = []
    def ready():
        try:
            value = require_launch(native_inventory(native, profile), game_uuid)
        except ProbeFailure:
            return False
        observed.append(value)
        return True
    wait_for(ready, 10, 'linux_game_native_inventory_not_ready')
    return observed[-1]


def expected_profile(native, data, role):
    value = native.execute_async('''const done=arguments[arguments.length-1], base=arguments[0], account=arguments[1];
      (async()=>{const token=await window.__TAURI_INTERNALS__.invoke('secure_store_get',{account:'api_token'});
        const device=localStorage.getItem('oneirodex-device-id');if(!token||!device)return null;
        const sha=async text=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text))))
          .map(value=>value.toString(16).padStart(2,'0')).join('');
        return sha(JSON.stringify(['oneirodex-launch-profile-v1',base,account,device,await sha(token)]));
      })().then(done,()=>done(null));''', [data['base_url'], data['ids'][role]['account_id']])
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value) or value == '0'*64:
        raise ProbeFailure('linux_game_expected_profile_unavailable')
    return value


def native_running(native, record, wrong=False):
    return native.execute_async('''const done=arguments[arguments.length-1];
      window.__TAURI_INTERNALS__.invoke('is_process_running',{pid:arguments[0],launchId:arguments[1]})
      .then(done,()=>done(null));''', [record['pid'], '00000000-0000-4000-8000-000000000000' if wrong else record['launch_id']])


def observe_sessions(fixture):
    data = fixture.private_data
    value = fixture.api.internal('observe-game', {'game_uuid': data['installed_fixture']['game_uuid'],
                                                'user_id': data['ids']['adult']['user_id']})
    fields = ('total', 'active', 'ended', 'orphaned')
    if (not isinstance(value, dict) or any(type(value.get(key)) is not int or not 0 <= value[key] <= 10 for key in fields)
            or value.get('adult_owned') is not True or value.get('desktop_only') is not True
            or value['total'] != sum(value[key] for key in ('active', 'ended', 'orphaned'))):
        raise ProbeFailure('linux_game_database_observation_invalid')
    return value


def run_game_journey(native, fixture, progress):
    from linux_connected_journey import connect, ui_session
    from linux_installed_journey import INSTALL_STATE_SCRIPT
    data = fixture.private_data
    game_uuid = data['installed_fixture']['game_uuid']
    progress['phase'] = 'linux_game_family_recovery_journey'
    control = GameFixture(native, progress)
    checks = progress.setdefault('game_play_checks', {})
    error = None
    try:
        with ui_session(native, 7):
            wait_for(lambda: native.execute_js(INSTALL_STATE_SCRIPT, [game_uuid]).get('cached_shelf_disclosed') is True,
                     30, 'linux_game_cached_hydration_missing')
            if observe_sessions(fixture)['total'] != 0:
                raise ProbeFailure('linux_game_sessions_not_initially_empty')
            connect(native, data['base_url'], data['tokens']['adult'], 'online', progress,
                    'adult_game_connect', private_visible=True)
            record = native.execute_async('''const done=arguments[arguments.length-1], id=arguments[0];
              window.__TAURI_INTERNALS__.invoke('load_installs').then(value=>done(value.installs?.[id]??null),()=>done(null));''', [game_uuid])
            entry = Path(record['exe_path']).resolve(strict=True)
            if not entry.is_relative_to((native.app_directory/'installs').resolve(strict=True)):
                raise ProbeFailure('linux_game_entry_not_in_owned_install')
            profile = expected_profile(native, data, 'adult')
            control.launched = True
            clicked = native.execute_js('''const card=Array.from(document.querySelectorAll('#library [data-game-uuid]'))
              .find(item=>item.dataset.gameUuid===arguments[0]);const button=card?.querySelector('[data-action="play"]');
              if(!(button instanceof HTMLButtonElement)||button.disabled)return false;button.click();return true;''', [game_uuid])
            if clicked is not True: raise ProbeFailure('linux_real_play_button_not_available')
            control.attach_child(entry)
            launch = wait_native_launch(native, profile, game_uuid)
            control.attach_supervisor(launch, game_uuid, entry)
            root_pid = control.read_pid('root')
            if root_pid != launch['pid']:
                raise ProbeFailure('linux_game_wrapper_pid_does_not_match_native_launch')
            wait_for(lambda: not (Path('/proc')/str(root_pid)).exists(), 10, 'linux_game_wrapper_has_not_exited')
            control.require_live()
            if native_running(native, launch) is not True or native_running(native, launch, wrong=True) is not False:
                raise ProbeFailure('linux_game_native_identity_controls_failed')
            denied = native_inventory(native, '0'*64)
            if denied.get('supported') is not True or denied.get('launches') != []:
                raise ProbeFailure('linux_game_foreign_profile_recovered_launch')
            checks.update(real_play_detached_child_verified=True, wrapper_exited_family_still_running=True,
                          wrong_launch_identity_refused=True, foreign_profile_refused=True)
            def heartbeat():
                value = observe_sessions(fixture)
                return value['total'] == 1 and value['active'] == 1 and value['active_heartbeat_observed'] is True
            wait_for(heartbeat, 45, 'linux_game_live_child_heartbeat_not_verified')
            progress['game_sessions_before_reopen'] = observe_sessions(fixture)
            checks['heartbeat_after_wrapper_exit'] = True
        control.require_live()
        checks['child_and_supervisor_survived_companion_close'] = True
        with ui_session(native, 8):
            wait_for(lambda: native.execute_js(INSTALL_STATE_SCRIPT, [game_uuid]).get('cached_shelf_disclosed') is True,
                     30, 'linux_game_reopen_cached_shelf_missing')
            if observe_sessions(fixture)['total'] != 1:
                raise ProbeFailure('linux_game_cached_hydration_created_session')
            checks['cached_hydration_does_not_resume_reporting'] = True
            connect(native, data['base_url'], data['tokens']['child_recovery'], 'online', progress,
                    'child_game_recovery_connect', private_visible=False)
            child_profile = expected_profile(native, data, 'child_recovery')
            child_records = native_inventory(native, child_profile)
            if child_records.get('supported') is not True or child_records.get('launches') != [] or observe_sessions(fixture)['total'] != 1:
                raise ProbeFailure('linux_game_child_account_resumed_adult_launch')
            checks['child_account_does_not_recover_adult_launch'] = True
            connect(native, data['base_url'], data['tokens']['adult'], 'online', progress,
                    'adult_game_recovery_connect', private_visible=True)
            recovered = require_launch(native_inventory(native, profile), game_uuid)
            if recovered != launch:
                raise ProbeFailure('linux_game_recovered_a_different_launch')
            control.require_live()
            def resumed():
                value = observe_sessions(fixture)
                return value['total'] == 2 and value['active'] == 1 and value['orphaned'] == 1
            wait_for(resumed, 30, 'linux_game_exact_launch_reporting_not_resumed')
            checks['fresh_adult_identity_resumes_exact_launch'] = True
            progress['game_sessions_after_verified_recovery'] = observe_sessions(fixture)
            control.stop()
            wait_for(lambda: native_running(native, launch) is False, 10, 'linux_game_native_family_remained_running')
            def ended():
                value = observe_sessions(fixture)
                return value['total'] == 2 and value['active'] == 0 and value['ended'] == 1 and value['orphaned'] == 1
            wait_for(ended, 45, 'linux_game_reporter_did_not_stop_after_family_exit')
            progress['game_sessions_after_family_exit'] = observe_sessions(fixture)
            checks.update(child_and_supervisor_exit_verified_by_pidfds=True, family_exit_stops_playtime_reporting=True)
        progress['game_family_recovery_journey_verified'] = True
    except BaseException as failed:
        error = failed
        raise
    finally:
        try: control.stop()
        except Exception:
            if error is None: raise
            error.add_note('linux_game_fixture_cleanup_failed')
