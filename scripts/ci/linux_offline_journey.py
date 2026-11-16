"""Real reachable-denial/outage local Play journey; file-manager Reveal is opt-in."""
from pathlib import Path
import time

from probe_linux_packaged import ProbeFailure
from linux_packaged_native import wait_for
from linux_game_journey import expected_profile, native_running, observe_sessions, wait_native_launch
from linux_reveal_context import RevealContext


SHELF_SCRIPT = '''return (() => {
  const summary=document.querySelector('#auth-summary')?.textContent||'';
  const library=document.querySelector('#library');
  const card=Array.from(library?.querySelectorAll('[data-game-uuid]')||[]).find(item=>item.dataset.gameUuid===arguments[0]);
  const enabled=action=>{const button=card?.querySelector('[data-action="'+action+'"]');
    return button instanceof HTMLButtonElement&&!button.disabled;};
  const banner=library?.querySelector('.offline-banner')?.textContent||'';
  const serverActions=['download','install','update','uninstall','apply_mods','apply_patch'];
  return {mode_denied:summary.includes('Server access denied'),mode_offline:summary.includes('Offline (server unreachable)'),
    cached_shelf_disclosed:banner.includes('previously verified'),possession_disclosed:banner.includes('OS-level access'),
    state_installed:card?.querySelector('.state strong')?.textContent==='installed',
    play_enabled:enabled('play'),reveal_enabled:enabled('reveal_path'),
    server_actions_blocked:serverActions.every(action=>!document.querySelector('button[data-action="'+action+'"]:not(:disabled)')),
    private_visible:(library?.textContent||'').includes('Synthetic CI Adult Private Game')};
})();'''
SHELF_FIELDS = ('mode_denied','mode_offline','cached_shelf_disclosed','possession_disclosed',
                'state_installed','play_enabled','reveal_enabled','server_actions_blocked','private_visible')


def require_local_shelf(native, game_uuid, mode, progress, label):
    if mode not in ('denied','offline'): raise ProbeFailure('linux_local_shelf_mode_invalid')
    value = native.execute_js(SHELF_SCRIPT, [game_uuid])
    snapshot = {key: value.get(key) is True for key in SHELF_FIELDS}
    required = ('mode_'+mode,'cached_shelf_disclosed','possession_disclosed','state_installed',
                'play_enabled','reveal_enabled','server_actions_blocked')
    if not all(snapshot[key] for key in required) or snapshot['private_visible']:
        progress['failed_local_shelf_snapshot'] = snapshot
        raise ProbeFailure('linux_verified_local_shelf_not_available')
    progress.setdefault('local_access_checks', {})[label+'_verified_local_shelf'] = True


def install_record(native, game_uuid):
    value = native.execute_async('''const done=arguments[arguments.length-1], id=arguments[0];
      window.__TAURI_INTERNALS__.invoke('load_installs').then(data=>done(data.installs?.[id]??null),()=>done(null));''', [game_uuid])
    if not isinstance(value, dict) or not isinstance(value.get('exe_path'), str) or not isinstance(value.get('extract_path'), str):
        raise ProbeFailure('linux_local_install_record_missing')
    entry, target = Path(value['exe_path']).resolve(strict=True), Path(value['extract_path']).resolve(strict=True)
    root = (native.app_directory/'installs').resolve(strict=True)
    if not entry.is_relative_to(root) or entry.parent != target or target == root:
        raise ProbeFailure('linux_local_install_record_not_contained')
    return entry, target


def play_local(native, fixture, progress, control, label):
    progress['phase'] = 'linux_local_play_'+label
    data = fixture.private_data
    game_uuid = data['installed_fixture']['game_uuid']
    before = observe_sessions(fixture)
    if before['active'] != 0: raise ProbeFailure('linux_local_play_has_active_server_session')
    entry, _ = install_record(native, game_uuid)
    profile = expected_profile(native, data, 'adult')
    control.reset()
    control.launched = True
    clicked = native.execute_js('''const card=Array.from(document.querySelectorAll('#library [data-game-uuid]'))
      .find(item=>item.dataset.gameUuid===arguments[0]);const button=card?.querySelector('[data-action="play"]');
      if(!(button instanceof HTMLButtonElement)||button.disabled)return false;button.click();return true;''', [game_uuid])
    if clicked is not True: raise ProbeFailure('linux_local_play_button_unavailable')
    control.attach_child(entry)
    launch = wait_native_launch(native, profile, game_uuid)
    control.attach_supervisor(launch, game_uuid, entry)
    if control.read_pid('root') != launch['pid']:
        raise ProbeFailure('linux_local_play_wrapper_identity_mismatch')
    wait_for(lambda: not (Path('/proc')/str(launch['pid'])).exists(), 10, 'linux_local_play_wrapper_still_running')
    control.require_live()
    if native_running(native, launch) is not True:
        raise ProbeFailure('linux_local_play_family_not_running')
    wait_for(lambda: native.execute_js('''const status=document.querySelector('#status');
      return status?.dataset.tone==='success'&&status.textContent.includes('Playtime tracking is unavailable');''') is True,
             10, 'linux_local_play_reporting_limit_not_disclosed')
    started = time.monotonic()
    def one_poll_interval():
        control.require_live()
        return time.monotonic()-started >= 32
    wait_for(one_poll_interval, 36, 'linux_local_play_observation_interval_incomplete')
    if observe_sessions(fixture) != before:
        raise ProbeFailure('linux_local_play_changed_server_reports')
    control.stop()
    wait_for(lambda: native_running(native, launch) is False, 10, 'linux_local_play_family_exit_not_verified')
    if observe_sessions(fixture) != before:
        raise ProbeFailure('linux_local_play_exit_changed_server_reports')
    progress.setdefault('local_access_checks', {}).update({label+'_real_play_and_detached_child':True,
        label+'_reporting_unavailable_disclosed':True,label+'_no_new_playtime_rows':True,
        label+'_held_kernel_family_exit':True})


def run_offline_journey(native, fixture, progress, control, reveal=False):
    """Play locally under reachable denial and backend outage.

    Reveal needs a real file manager on the owned bus/display. That fixture is a
    separate prerequisite, so it stays selectable and never gates local Play.
    """
    from linux_connected_journey import STATE_SCRIPT, connect, ui_session
    from linux_installed_journey import check_native_install
    data = fixture.private_data
    game_uuid = data['installed_fixture']['game_uuid']
    context = RevealContext(native, progress) if reveal else None
    def show(target, mode):
        if context is not None: context.reveal(game_uuid, target, mode)
    progress['phase'] = 'linux_reveal_denial_outage_journey' if reveal else 'linux_denial_outage_play_journey'
    error = None
    try:
        if context is not None: context.start()
        with ui_session(native, 9):
            wait_for(lambda: native.execute_js(STATE_SCRIPT).get('offline') is True, 30, 'linux_local_access_hydration_missing')
            connect(native, data['base_url'], data['tokens']['adult'], 'online', progress,
                    'adult_reveal_connect', private_visible=True)
            _, target = install_record(native, game_uuid)
            show(target, 'online')
            fixture.api.revoke(data['ids']['adult'])
            connect(native, data['base_url'], data['tokens']['adult'], 'denied', progress, 'revoked_installed_adult_denied')
            require_local_shelf(native, game_uuid, 'denied', progress, 'denied')
            check_native_install(native, game_uuid, data['installed_fixture']['manifest'])
            show(target, 'denied')
            play_local(native, fixture, progress, control, 'denied')
            progress['phase'] = 'linux_owned_server_outage'
            fixture.api.stop_for_outage()
        progress['phase'] = 'linux_outage_cold_reopen'
        with ui_session(native, 10):
            wait_for(lambda: native.execute_js(STATE_SCRIPT).get('offline') is True, 30, 'linux_outage_cold_shelf_missing')
            require_local_shelf(native, game_uuid, 'offline', progress, 'outage_cold')
            connect(native, data['base_url'], data['tokens']['adult'], 'offline', progress, 'owned_server_outage_connect')
            require_local_shelf(native, game_uuid, 'offline', progress, 'outage_after_connect')
            _, target = install_record(native, game_uuid)
            check_native_install(native, game_uuid, data['installed_fixture']['manifest'])
            show(target, 'offline')
            play_local(native, fixture, progress, control, 'offline')
        progress['denial_outage_play_journey_verified'] = True
        if reveal: progress['reveal_denial_outage_journey_verified'] = True
        progress['local_access_scope'] = ('Real installed synthetic Play '
            + ('and genuine file-manager Reveal ' if reveal else '')
            + 'with reachable token revocation and owned-backend outage/cold reopen. '
            + ('' if reveal else 'Reveal was not exercised; only its enabled control was observed. ')
            + 'No arbitrary-game/save/platform qualification or server reauthorization while offline.')
    except BaseException as failed:
        error = failed
        raise
    finally:
        cleanup_errors = []
        for cleanup in (control.stop,) + ((context.close,) if context is not None else ()):
            try: cleanup()
            except Exception as failed: cleanup_errors.append(failed)
        if cleanup_errors:
            if error is None: raise cleanup_errors[0]
            error.add_note('linux_local_access_cleanup_failed')
