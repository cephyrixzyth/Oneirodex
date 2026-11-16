"""Real packaged Download/Install journey; no payload execution or local resources."""
import hashlib
import io
import itertools
from pathlib import Path
import re
import stat
import zipfile

from probe_linux_packaged import ProbeFailure
from linux_packaged_native import wait_for


def fixture_archive():
    """Self-authored bounded deterministic payload, not a compatibility fixture."""
    members = {
        'synthetic-game.sh': (b'''#!/bin/sh
set -eu
umask 077
control="$HOME/.oneirodex-ci-game"
[ -d "$control" ] && [ -f "$control/next" ] || exit 70
read -r nonce < "$control/next"
case "$nonce" in ''|*[!0-9a-f]*) exit 70;; esac
[ "${#nonce}" -eq 32 ] || exit 70
if [ "${1:-}" != child ]; then
  printf '%s\\n' "$$" > "$control/root-$nonce.pid"
  /usr/bin/setsid /bin/sh "$0" child &
  exit 0
fi
printf '%s\\n' "$$" > "$control/child-$nonce.pid"
count=0
while [ ! -f "$control/stop-$nonce" ] && [ "$count" -lt 2400 ]; do
  sleep 0.1
  count=$((count + 1))
done
printf '%s\\n' "$nonce" > "$control/exit-$nonce"
''', 0o755),
        'README.txt': (b'Synthetic archive transfer and extraction fixture. No game compatibility claim.\n', 0o644),
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED) as archive:
        for name, (body, mode) in members.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | mode) << 16
            archive.writestr(info, body)
    data = output.getvalue()
    return data, {
        'archive_sha256': hashlib.sha256(data).hexdigest(), 'archive_bytes': len(data),
        'members': {name: {'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body), 'mode': mode}
                    for name, (body, mode) in members.items()},
    }


def write_fixture_archive(games):
    if games != games.resolve(strict=True) or not stat.S_ISDIR(games.lstat().st_mode):
        raise ProbeFailure('linux_fixture_games_directory_not_owned')
    data, manifest = fixture_archive()
    path = games/'synthetic-ci-shared.zip'
    with path.open('xb') as output:
        output.write(data)
    return path, manifest


def _owned_path(raw, root, directory=False):
    if not isinstance(raw, str) or not raw:
        raise ProbeFailure('linux_installed_record_path_invalid')
    path = Path(raw)
    base = root.resolve(strict=True)
    resolved = path.resolve(strict=True)
    if path != resolved or not resolved.is_relative_to(base) or resolved == base:
        raise ProbeFailure('linux_installed_file_not_contained')
    mode = path.lstat().st_mode
    if not (stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)):
        raise ProbeFailure('linux_installed_file_not_regular')
    return path


def verify_install_files(app, record, manifest, require_unix_mode=True):
    """Read only bounded files from the positively owned native profile."""
    _, expected = fixture_archive()
    if manifest != expected:
        raise ProbeFailure('linux_installed_fixture_manifest_changed')
    if not isinstance(record, dict):
        raise ProbeFailure('linux_installed_record_missing')
    archive = _owned_path(record.get('archive_path'), app/'downloads')
    target = _owned_path(record.get('extract_path'), app/'installs', directory=True)
    exe = _owned_path(record.get('exe_path'), target)
    if (archive.parent != (app/'downloads').resolve(strict=True)
            or target.parent != (app/'installs').resolve(strict=True)
            or exe != target/'synthetic-game.sh'):
        raise ProbeFailure('linux_installed_record_layout_changed')
    if (archive.stat().st_size != manifest['archive_bytes']
            or hashlib.sha256(archive.read_bytes()).hexdigest() != manifest['archive_sha256']):
        raise ProbeFailure('linux_installed_archive_hash_mismatch')
    names = {entry.name for entry in itertools.islice(target.iterdir(), 3)}
    if names != set(manifest['members']):
        raise ProbeFailure('linux_installed_members_changed')
    for name, item in manifest['members'].items():
        path = _owned_path(str(target/name), target)
        info = path.stat()
        if (info.st_size != item['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']):
            raise ProbeFailure('linux_installed_member_hash_mismatch')
        if require_unix_mode and stat.S_IMODE(info.st_mode) != item['mode']:
            raise ProbeFailure('linux_installed_member_mode_mismatch')
    return {'archive_hash_verified': True, 'member_hashes_verified': True,
            'selected_executable_verified': True, 'member_count': len(names),
            'unix_modes_verified': require_unix_mode}


INSTALL_STATE_SCRIPT = '''return (() => {
  const card = Array.from(document.querySelectorAll('#library [data-game-uuid]'))
    .find(item => item.dataset.gameUuid === arguments[0]);
  const state = card?.querySelector('.state strong')?.textContent || '';
  const enabled = action => {
    const button = card?.querySelector('[data-action="'+action+'"]');
    return button instanceof HTMLButtonElement && !button.disabled;
  };
  return {card_present: !!card, state_downloaded: state === 'downloaded',
    state_installed: state === 'installed', download_enabled: enabled('download'),
    install_enabled: enabled('install'), play_enabled: enabled('play'),
    reveal_enabled: enabled('reveal_path'),
    cached_shelf_disclosed: !!document.querySelector('#library .offline-banner'),
    status_error: document.querySelector('#status')?.dataset.tone === 'error'};
})();'''
INSTALL_STATE_FIELDS = ('card_present', 'state_downloaded', 'state_installed', 'download_enabled',
                        'install_enabled', 'play_enabled', 'reveal_enabled', 'cached_shelf_disclosed', 'status_error')


def ui_action(native, game_uuid, action, expected, progress):
    if action not in ('download', 'install'):
        raise ProbeFailure('linux_installed_action_not_allowed')
    clicked = native.execute_js('''const card=Array.from(document.querySelectorAll('#library [data-game-uuid]'))
      .find(item=>item.dataset.gameUuid===arguments[0]);
      const button=card?.querySelector('[data-action="'+arguments[1]+'"]');
      if (!(button instanceof HTMLButtonElement) || button.disabled) return false;
      button.click();return true;''', [game_uuid, action])
    if clicked is not True:
        raise ProbeFailure('linux_installed_button_not_available')
    def settled():
        value = native.execute_js(INSTALL_STATE_SCRIPT, [game_uuid])
        snapshot = {key: value.get(key) is True for key in INSTALL_STATE_FIELDS}
        progress['failed_install_ui_snapshot'] = snapshot
        available = snapshot['install_enabled'] if action == 'download' else snapshot['play_enabled'] and snapshot['reveal_enabled']
        return snapshot[expected] and available and not snapshot['status_error']
    wait_for(settled, 45, 'linux_installed_ui_'+action+'_not_verified')
    progress.pop('failed_install_ui_snapshot', None)
    progress.setdefault('installed_archive_checks', {})[action+'_ui_completed'] = True


def check_native_install(native, game_uuid, manifest):
    record = native.execute_async('''const done=arguments[arguments.length-1], id=arguments[0];
      window.__TAURI_INTERNALS__.invoke('load_installs').then(value=>done(value.installs?.[id] ?? null),()=>done(null));''', [game_uuid])
    return verify_install_files(native.app_directory, record, manifest)


def run_installed_journey(native, fixture, progress):
    from linux_connected_journey import STATE_SCRIPT, connect, ui_session
    data = fixture.private_data
    item = data['installed_fixture']
    game_uuid = item['game_uuid']
    if not isinstance(game_uuid, str) or not re.fullmatch(r'[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}', game_uuid):
        raise ProbeFailure('linux_installed_game_id_invalid')
    progress['phase'] = 'linux_installed_archive_journey'
    with ui_session(native, 5):
        wait_for(lambda: native.execute_js(STATE_SCRIPT).get('ready') is True, 30, 'linux_install_hydration_not_ready')
        connect(native, data['base_url'], data['tokens']['adult'], 'online', progress,
                'adult_install_reconnect', private_visible=True)
        ui_action(native, game_uuid, 'download', 'state_downloaded', progress)
        ui_action(native, game_uuid, 'install', 'state_installed', progress)
        progress['installed_archive_file_checks'] = check_native_install(native, game_uuid, item['manifest'])
    with ui_session(native, 6):
        def restored():
            value = native.execute_js(INSTALL_STATE_SCRIPT, [game_uuid])
            return all(value.get(key) is True for key in ('state_installed', 'play_enabled', 'reveal_enabled', 'cached_shelf_disclosed'))
        wait_for(restored, 30, 'linux_installed_cold_shelf_not_verified')
        check_native_install(native, game_uuid, item['manifest'])
        progress.setdefault('installed_archive_checks', {})['cold_reopen_cached_shelf_and_files'] = True
    progress['installed_archive_journey_verified'] = True
    progress['installed_archive_scope'] = ('Synthetic ZIP transfer/extraction and cached shelf before reconnect; '
        'no payload execution, network outage, Play/Reveal, game compatibility or save-retention qualification.')
    from linux_game_journey import run_game_journey
    run_game_journey(native, fixture, progress)
