#!/usr/bin/env python3
"""Owned macOS descendant/survival experiment; never production tracking."""
import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import signal
import subprocess
import sys
import tempfile
import time
import uuid

spec = importlib.util.spec_from_file_location(
    'coalition_base', Path(__file__).with_name('probe-macos-launch-coalition.py'))
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
SCRIPT = str(Path(__file__).resolve())
MISSING = object()


def validate_request(value, nonce):
    if (not isinstance(value, dict) or set(value) != {'nonce', 'case', 'mode'} or
            value['nonce'] != nonce or not isinstance(value['case'], str) or
            re.fullmatch('[0-9a-f]{32}', value['case']) is None or
            value['mode'] not in ('normal', 'detached')):
        raise RuntimeError('family request invalid')
    return value


def read_json(path, missing=None):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return missing
    except (ValueError, UnicodeError) as error:
        raise RuntimeError('family record invalid') from error


def read_snapshot(path, nonce, case=None):
    data = read_json(path, missing=MISSING)
    if data is MISSING:
        return None
    if not isinstance(data, dict) or data.get('nonce') != nonce:
        raise RuntimeError('family record identity mismatch')
    if 'unavailable' in data:
        raise base.Unsupported('family inspection unavailable')
    fields = ('coalition_id', 'started', 'exited', 'active')
    if (any(type(data.get(k)) is not int or not 0 <= data[k] < (1 << 64) for k in fields)
            or data['coalition_id'] <= 1 or data['started'] < data['exited'] or
            data['active'] != data['started'] - data['exited']):
        raise RuntimeError('family counters invalid')
    if case is not None and (data.get('case') != case or any(
            type(data.get(k)) is not int or data[k] <= 0
            for k in ('heartbeat', 'pid', 'pgid', 'sid'))):
        raise RuntimeError('family leaf identity invalid')
    return data


def held(path):
    import fcntl
    try:
        with path.open('r') as lease:
            try:
                fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
    except FileNotFoundError:
        return False
    return False


def keeper_snapshot(directory, nonce):
    if not held(directory / 'alive.lock'):
        raise base.Unsupported('family inspection unavailable')
    value = read_snapshot(directory / 'state.json', nonce)
    if not held(directory / 'alive.lock'):
        raise base.Unsupported('family inspection unavailable')
    return value


def verify_survival(before, after, keeper_held, leaf_held):
    if (keeper_held or not leaf_held or after['heartbeat'] <= before['heartbeat'] or
            any(before[k] != after[k] for k in ('nonce', 'case', 'coalition_id', 'pid', 'pgid', 'sid'))):
        raise RuntimeError('owned leaf did not prove survival after guardian loss')


def observe_owned(directory, nonce, case, expect_live=True):
    validate_request({'nonce': nonce, 'case': case, 'mode': 'normal'}, nonce)
    if read_json(directory / 'job.json') != {'nonce': nonce}:
        raise RuntimeError('observer job identity mismatch')
    known = read_snapshot(directory / 'coalition.json', nonce)
    target = directory / 'cases' / case
    leaf_info = read_snapshot(target / 'leaf.json', nonce, case)
    if known is None or leaf_info is None:
        raise base.Unsupported('owned coalition binding unavailable')
    if leaf_info['coalition_id'] != known['coalition_id']:
        raise RuntimeError('observer leaf coalition mismatch')
    lease = target / 'leaf.lock'
    if not lease.exists() or held(lease) != expect_live:
        raise base.Unsupported('owned leaf state unavailable')
    api = base.CoalitionAPI()
    own = api.own_snapshot()['coalition_id']
    if type(own) is not int or own <= 1 or own == known['coalition_id']:
        raise RuntimeError('observer is not outside the owned coalition')
    sentinel = (1 << 64) - 1
    counters = (ctypes.c_uint64 * 2)(sentinel, sentinel)
    try:
        result = api.usage(known['coalition_id'], ctypes.byref(counters), ctypes.sizeof(counters))
    except (OSError, AttributeError) as error:
        raise base.Unsupported('owned coalition query unavailable') from error
    started, exited = map(int, counters)
    if result != 0 or sentinel in (started, exited) or started < exited:
        raise base.Unsupported('owned coalition query unavailable')
    if not lease.exists() or held(lease) != expect_live:
        raise base.Unsupported('owned leaf state unavailable')
    return {'nonce': nonce, 'case': case, 'coalition_id': known['coalition_id'],
            'started': started, 'exited': exited, 'active': started - exited,
            'observer_coalition_id': own}


def verify_observation(data, nonce, case, coalition, active, observation=None):
    if (not isinstance(data, dict) or data.get('nonce') != nonce or data.get('case') != case or
            data.get('coalition_id') != coalition or data.get('active') != active or
            type(data.get('observer_coalition_id')) is not int or
            data['observer_coalition_id'] <= 1 or data['observer_coalition_id'] == coalition or
            (observation is not None and data.get('observation') != observation)):
        raise RuntimeError('owned observation identity or count mismatch')


def observe_case(job, case, active, expect_live=True):
    directory, nonce = job['directory'], job['nonce']
    coalition = job['initial']['coalition_id']
    controller = observe_owned(directory, nonce, case, expect_live)
    verify_observation(controller, nonce, case, coalition, active)
    observation = uuid.uuid4().hex
    path = directory / 'cases' / case / ('observer-' + observation + '.json')
    if path.exists():
        raise RuntimeError('fresh observer output already exists')
    result = subprocess.run(role_command('observer', directory, nonce, case,
        observation=observation, expect_state='live' if expect_live else 'retired'),
        close_fds=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15, check=False)
    fresh = read_snapshot(path, nonce)
    if result.returncode != 0 or fresh is None:
        raise RuntimeError('fresh owned observer failed to return a valid result')
    verify_observation(fresh, nonce, case, coalition, active, observation)
    return {'controller': controller, 'fresh_process': fresh}


def wait_until(predicate, reason, seconds=12):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise RuntimeError(reason)


def role_command(role, directory, nonce, case=None, mode='normal', observation=None, expect_state='live'):
    args = [sys.executable, SCRIPT, '--role', role, '--directory', str(directory),
            '--nonce', nonce, '--mode', mode]
    if case is not None:
        args += ['--case', case]
    if observation is not None:
        args += ['--observation', observation, '--expect-state', expect_state]
    return args


def fixture_role(role, directory, nonce, case, mode, observation=None, expect_state='live'):
    if read_json(directory / 'job.json') != {'nonce': nonce}:
        raise RuntimeError('owned job metadata mismatch')
    if role == 'guardian':
        return guardian(directory, nonce)
    validate_request({'nonce': nonce, 'case': case, 'mode': mode}, nonce)
    target = directory / 'cases' / case
    if target.is_symlink() or not target.is_dir():
        raise RuntimeError('owned case directory invalid')
    if role == 'observer':
        if not isinstance(observation, str) or re.fullmatch('[0-9a-f]{32}', observation) is None:
            raise RuntimeError('observer request identity invalid')
        try:
            data = observe_owned(directory, nonce, case, expect_state == 'live')
        except base.Unsupported:
            base.atomic_json(target / ('observer-' + observation + '.json'),
                {'nonce': nonce, 'case': case, 'observation': observation, 'unavailable': True})
            return 2
        base.atomic_json(target / ('observer-' + observation + '.json'), {**data, 'observation': observation})
        return 0
    if role in ('wrapper', 'middle'):
        next_role = 'middle' if role == 'wrapper' else 'leaf'
        subprocess.Popen(role_command(next_role, directory, nonce, case, mode),
                         close_fds=True, start_new_session=(role == 'middle' and mode == 'detached'),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        (target / (role + '-spawned')).touch()
        os._exit(0)
    return leaf(target, nonce, case)


def leaf(directory, nonce, case):
    import fcntl
    # Never explicitly close this raw fd: lease retirement proves kernel exit.
    try:
        lease_fd = os.open(directory / 'leaf.lock', os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        os.set_inheritable(lease_fd, False)
        fcntl.flock(lease_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        api = base.CoalitionAPI()
        heartbeat = 0
        deadline = time.monotonic() + 90
        while not (directory / 'stop').exists() and time.monotonic() < deadline:
            if (directory / 'crash').exists():
                os.kill(os.getpid(), signal.SIGKILL)  # This owned role signals itself only.
            heartbeat += 1
            base.atomic_json(directory / 'leaf.json', {'nonce': nonce, 'case': case,
                **api.own_snapshot(), 'heartbeat': heartbeat, 'pid': os.getpid(),
                'pgid': os.getpgid(0), 'sid': os.getsid(0)})
            time.sleep(0.05)
    except (OSError, AttributeError, base.Unsupported):
        base.atomic_json(directory / 'leaf.json', {'nonce': nonce, 'case': case,
                                                  'unavailable': True})
        os._exit(2)
    os._exit(0)


def guardian(directory, nonce):
    import fcntl
    roots = {}
    with (directory / 'alive.lock').open('w') as lease:
        os.set_inheritable(lease.fileno(), False)
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            api = base.CoalitionAPI()
            initial = {'nonce': nonce, **api.own_snapshot(), 'pgid': os.getpgid(0)}
            base.atomic_json(directory / 'ready.json', initial)
            deadline = time.monotonic() + 120
            while not (directory / 'stop').exists() and time.monotonic() < deadline:
                request_path = directory / 'request.json'
                if request_path.exists():
                    try:
                        request = validate_request(read_json(request_path), nonce)
                        case, mode = request['case'], request['mode']
                        target = directory / 'cases' / case
                        if case in roots or target.is_symlink() or not target.is_dir():
                            raise RuntimeError('owned case reused or unavailable')
                        roots[case] = subprocess.Popen(role_command('wrapper', directory, nonce, case, mode),
                            close_fds=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    except RuntimeError:
                        base.atomic_json(directory / 'request-result.json', {'nonce': nonce, 'status': 'rejected'})
                    request_path.unlink(missing_ok=True)
                for case, process in roots.items():
                    if process.poll() is not None:
                        (directory / 'cases' / case / 'root-reaped').touch()
                try:
                    if (directory / 'inject-api-unavailable').exists():
                        raise base.Unsupported('injected API unavailability')
                    base.atomic_json(directory / 'state.json', {'nonce': nonce,
                        **api.own_snapshot(), 'pgid': os.getpgid(0)})
                except (OSError, AttributeError, base.Unsupported):
                    base.atomic_json(directory / 'state.json', {'nonce': nonce, 'unavailable': True})
                time.sleep(0.05)
        except (OSError, AttributeError, base.Unsupported):
            base.atomic_json(directory / 'ready.json', {'nonce': nonce, 'unavailable': True})
            return 2
        finally:
            for case, process in roots.items():
                (directory / 'cases' / case / 'stop').touch()
                process.wait(timeout=5)
            for case in roots:
                wait_until(lambda: not held(directory / 'cases' / case / 'leaf.lock'),
                           'owned leaf did not retire on guardian stop', seconds=5)
    return 0


def cleanup_jobs(jobs, errors):
    for job in reversed(jobs):
        directory = job['directory']
        try:
            for case in (directory / 'cases').glob('*'):
                (case / 'stop').touch()
            (directory / 'stop').touch()
            wait_until(lambda: not held(directory / 'alive.lock'), 'guardian lease did not retire', seconds=6)
            for case in (directory / 'cases').glob('*'):
                wait_until(lambda: not held(case / 'leaf.lock'), 'leaf lease did not retire', seconds=6)
        except (OSError, RuntimeError):
            errors.append('owned fixture leases did not retire normally')
        try:
            removed = base.launchctl('bootout', job['target'])
            observed = base.launchctl('print', job['target'])
            absent = observed.returncode != 0 and 'could not find service' in observed.stderr.lower()
            if observed.returncode == 0 or (removed.returncode != 0 and not absent):
                errors.append('exact owned job cleanup not confirmed')
        except (OSError, subprocess.TimeoutExpired):
            errors.append('exact owned job cleanup unavailable')


def make_directory(parent, nonce):
    directory = parent / nonce
    directory.mkdir(mode=0o700)
    (directory / 'cases').mkdir(mode=0o700)
    base.atomic_json(directory / 'job.json', {'nonce': nonce})
    return directory


def create_job(root, jobs, report):
    nonce = uuid.uuid4().hex
    directory = make_directory(root, nonce)
    label = 'com.oneirodex.fixture.' + nonce
    target = f'gui/{os.geteuid()}/{label}'
    plist = directory / 'job.plist'
    plist.write_bytes(plistlib.dumps({'Label': label, 'RunAtLoad': True, 'KeepAlive': False,
        'AbandonProcessGroup': True, 'ProgramArguments': role_command('guardian', directory, nonce),
        'StandardOutPath': str(directory / 'stdout'), 'StandardErrorPath': str(directory / 'stderr')}))
    job = {'target': target, 'directory': directory, 'nonce': nonce}
    jobs.append(job)  # Register before bootstrap, including partial-admission failures.
    result = base.launchctl('bootstrap', f'gui/{os.geteuid()}', str(plist))
    report.setdefault('bootstrap', []).append({'exit_code': result.returncode,
        'stderr': base.command_diagnostic(result.stderr, root)})
    if result.returncode != 0:
        raise base.Unsupported('owned GUI family job unavailable')
    initial = base.ready(directory, nonce)
    if initial['active'] != 1:
        raise RuntimeError('family job lacks keeper-only baseline')
    job['initial'] = initial
    base.atomic_json(directory / 'coalition.json', initial)
    return job


def count_is(job, count):
    value = keeper_snapshot(job['directory'], job['nonce'])
    if value and value['coalition_id'] != job['initial']['coalition_id']:
        raise RuntimeError('keeper coalition identity changed')
    return value if value and value['active'] == count else None


def start_case(job, mode, report):
    case = uuid.uuid4().hex
    directory = job['directory'] / 'cases' / case
    directory.mkdir(mode=0o700)
    entry = {'case': case, 'mode': mode, 'verified': False}
    report.setdefault('cases', []).append(entry)
    base.atomic_json(job['directory'] / 'request.json', {'nonce': job['nonce'], 'case': case, 'mode': mode})
    wait_until(lambda: all((directory / name).exists() for name in
        ('wrapper-spawned', 'middle-spawned', 'root-reaped')), 'fast ancestors did not complete')
    snapshot = wait_until(lambda: leaf_state(job, case), 'owned leaf did not become ready')
    wait_until(lambda: count_is(job, 2), 'keeper/leaf counter did not settle to two')
    if mode == 'normal' and snapshot['pgid'] != job['initial']['pgid']:
        raise RuntimeError('normal leaf changed process group')
    if mode == 'detached' and not snapshot['pid'] == snapshot['pgid'] == snapshot['sid']:
        raise RuntimeError('detached leaf lacks new session')
    entry.update({'verified': True, 'snapshot': snapshot, 'ancestors_reaped_and_count_two': True})
    entry['observations_with_guardian'] = observe_case(job, case, 2)
    return case, directory, entry


def leaf_state(job, case):
    directory = job['directory'] / 'cases' / case
    value = read_snapshot(directory / 'leaf.json', job['nonce'], case)
    if value and value['coalition_id'] != job['initial']['coalition_id']:
        raise RuntimeError('leaf escaped its owned coalition')
    return value if value and held(directory / 'leaf.lock') else None


def end_case(job, case, directory, crash=False):
    if not held(directory / 'leaf.lock'):
        raise RuntimeError('owned leaf not alive before requested exit')
    (directory / ('crash' if crash else 'stop')).touch()
    wait_until(lambda: not held(directory / 'leaf.lock'), 'owned leaf exit lease did not retire')
    wait_until(lambda: count_is(job, 1), 'keeper counter did not return to one')


def loss_case(job, mode, report):
    case, directory, entry = start_case(job, mode, report)
    result = base.launchctl('kill', 'SIGKILL', job['target'])
    if result.returncode != 0:
        raise RuntimeError('owned guardian termination failed')
    wait_until(lambda: not held(job['directory'] / 'alive.lock'), 'guardian death lease did not retire')
    before = wait_until(lambda: leaf_state(job, case), 'leaf absent after guardian death')
    def later():
        value = leaf_state(job, case)
        return value if value and value['heartbeat'] > before['heartbeat'] else None
    after = wait_until(later, 'leaf heartbeat stopped after guardian death')
    verify_survival(before, after, held(job['directory'] / 'alive.lock'), held(directory / 'leaf.lock'))
    entry.update({'survived_guardian_loss_before_bootout': True, 'after_loss_snapshot': after})
    entry['observations_after_guardian_loss'] = observe_case(job, case, 1)
    (directory / 'stop').touch()
    wait_until(lambda: not held(directory / 'leaf.lock'), 'surviving leaf exit lease did not retire')
    entry['observations_after_all_exit'] = observe_case(job, case, 0, expect_live=False)


def negative_controls(job, expected_count):
    directory, nonce = job['directory'], job['nonce']
    unbound = uuid.uuid4().hex
    (directory / 'cases' / unbound).mkdir(mode=0o700)
    base.atomic_json(directory / 'request.json', {'nonce': '0'*32, 'case': unbound, 'mode': 'normal'})
    wait_until(lambda: read_json(directory / 'request-result.json') == {'nonce': nonce, 'status': 'rejected'},
               'unbound request not rejected')
    wait_until(lambda: count_is(job, expected_count), 'unbound request changed family membership')
    marker = directory / 'inject-api-unavailable'
    marker.touch()
    def unavailable():
        try:
            keeper_snapshot(directory, nonce)
        except base.Unsupported:
            return True
        return False
    wait_until(unavailable, 'injected API failure was not unavailable')
    marker.unlink()
    def recovered():
        try:
            return count_is(job, expected_count)
        except base.Unsupported:
            if not held(directory / 'alive.lock'):
                raise
            return None
    wait_until(recovered, 'inspection did not recover after injected failure')


def probe(report):
    if sys.platform != 'darwin' or os.geteuid() == 0:
        raise base.Unsupported('ordinary-user macOS runtime required')
    controller = base.CoalitionAPI().own_snapshot()
    report['controller'] = controller
    jobs, errors = [], []
    outside_process = None
    with tempfile.TemporaryDirectory(prefix='oneirodex-family-') as temp:
        root = Path(temp)
        try:
            outside_nonce = uuid.uuid4().hex
            outside = make_directory(root, outside_nonce)
            outside_process = subprocess.Popen(role_command('guardian', outside, outside_nonce),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
            outside_info = base.ready(outside, outside_nonce)
            report['outside'] = outside_info
            a, b = create_job(root, jobs, report), create_job(root, jobs, report)
            excluded = {0, 1, controller['coalition_id'], outside_info['coalition_id']}
            ids = {j['initial']['coalition_id'] for j in jobs}
            if len(ids) != 2 or ids & excluded:
                raise RuntimeError('family guardian jobs are not isolated')
            report['keepers'] = [j['initial'] for j in jobs]
            case_a, dir_a, entry_a = start_case(a, 'normal', report)
            case_b, dir_b, entry_b = start_case(b, 'detached', report)
            before_control = wait_until(lambda: leaf_state(a, case_a), 'leaf absent before negative controls')
            negative_controls(a, 2)
            wait_until(lambda: (leaf_state(a, case_a) or {}).get('heartbeat', 0) > before_control['heartbeat'],
                       'family heartbeat stopped during negative controls')
            report['unbound_request_rejected'] = True
            report['injected_api_failure_classified_unavailable_with_live_family'] = True
            before = wait_until(lambda: leaf_state(b, case_b), 'other leaf absent before independent exit')
            end_case(a, case_a, dir_a)
            entry_a['observations_after_leaf_exit'] = observe_case(a, case_a, 1, expect_live=False)
            wait_until(lambda: count_is(b, 2), 'other family changed after independent exit')
            wait_until(lambda: (leaf_state(b, case_b) or {}).get('heartbeat', 0) > before['heartbeat'],
                       'independent other-family heartbeat stopped')
            report['independent_family_exit_passed'] = True
            end_case(b, case_b, dir_b, crash=True)
            entry_b['observations_after_leaf_exit'] = observe_case(b, case_b, 1, expect_live=False)
            report['self_crash_retired_leaf_and_counter'] = True
            loss_case(a, 'normal', report)
            loss_case(b, 'detached', report)
            fresh = create_job(root, jobs, report)
            if fresh['initial']['coalition_id'] in ids | excluded:
                raise RuntimeError('successive fresh job reused a coalition')
            report['fresh_successive_keeper'] = fresh['initial']
            if not held(outside / 'alive.lock'):
                raise RuntimeError('outside control did not remain alive')
            report['fixture_family_lifetime_passed'] = True
            report['outside_fresh_observation_passed'] = True
        finally:
            cleanup_jobs(jobs, errors)
            if outside_process is not None:
                (outside / 'stop').touch()
                try:
                    outside_process.wait(timeout=6)
                except subprocess.TimeoutExpired:
                    outside_process.kill()
                    outside_process.wait(timeout=6)
                    errors.append('owned outsider required forced termination')
            report['cleanup'] = {'attempted_jobs': len(jobs), 'errors': errors}
            if errors:
                report['fixture_family_lifetime_passed'] = False
                raise RuntimeError('owned family fixture cleanup failed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--role', choices=('guardian', 'wrapper', 'middle', 'leaf', 'observer'))
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--nonce')
    parser.add_argument('--case')
    parser.add_argument('--mode', choices=('normal', 'detached'), default='normal')
    parser.add_argument('--observation')
    parser.add_argument('--expect-state', choices=('live', 'retired'), default='live')
    args = parser.parse_args()
    if args.role:
        if sys.platform != 'darwin' or os.geteuid() == 0:
            return 2
        if args.directory is None or args.nonce is None:
            parser.error('owned directory and nonce required')
        return fixture_role(args.role, args.directory, args.nonce, args.case, args.mode,
                            args.observation, args.expect_state)
    if args.output is None:
        parser.error('--output required')
    report = {'phase': 'owned-native-family-and-guardian-loss', 'platform': platform.system(),
        'release': platform.release(), 'architecture': platform.machine(),
        'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'base_source_sha256': hashlib.sha256(Path(base.__file__).read_bytes()).hexdigest(),
        'fixture_family_lifetime_passed': False, 'outside_fresh_observation_passed': False,
        'family_recovery_acceptance': False,
        'remaining': ['production Rust/Tauri integration', 'fresh account/ACL and packaged restart',
                      'older/Intel Mac runtimes', 'external launcher/service handoffs', 'all original gates']}
    try:
        probe(report)
        report['status'], code = 'phase_passed', 0
    except (OSError, AttributeError, base.Unsupported) as error:
        report['status'], code = 'unsupported', 2
        report['reason'] = str(error) if isinstance(error, base.Unsupported) else type(error).__name__
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        report['status'], code = 'failed', 1
        report['reason'] = str(error) if isinstance(error, RuntimeError) else type(error).__name__
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
