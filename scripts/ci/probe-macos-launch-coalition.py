#!/usr/bin/env python3
"""Owned ordinary-user capability fixture; never production launch tracking.

This phase verifies API access and per-job isolation only. It does not qualify
descendants, guardian-loss game survival, recovery, or packaged behavior.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import subprocess
import sys
import tempfile
import time
import uuid


class Unsupported(RuntimeError):
    """The required ordinary-user platform capability was unavailable."""


class CoalitionAPI:
    def __init__(self):
        self.proc = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
        self.system = ctypes.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True)
        self.pidinfo = self.proc.proc_pidinfo
        self.pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64,
                                ctypes.c_void_p, ctypes.c_int]
        self.pidinfo.restype = ctypes.c_int
        self.usage = self.system.coalition_info_resource_usage
        self.usage.argtypes = [ctypes.c_uint64, ctypes.c_void_p, ctypes.c_size_t]
        self.usage.restype = ctypes.c_int

    def own_snapshot(self):
        # XNU source pin and ABI rationale are recorded in the probe README.
        ids = (ctypes.c_uint64 * 5)()
        got = self.pidinfo(os.getpid(), 20, 0, ctypes.byref(ids), ctypes.sizeof(ids))
        if got != ctypes.sizeof(ids) or ids[0] == 0:
            raise Unsupported('own coalition query incomplete or unavailable')
        sentinel = (1 << 64) - 1
        counters = (ctypes.c_uint64 * 2)(sentinel, sentinel)
        result = self.usage(ids[0], ctypes.byref(counters), ctypes.sizeof(counters))
        started, exited = map(int, counters)
        if result != 0 or sentinel in (started, exited) or started < exited:
            raise Unsupported('resource counter prefix unavailable or invalid')
        return {'coalition_id': int(ids[0]), 'started': started, 'exited': exited,
                'active': started - exited}


def atomic_json(path, value):
    pending = path.with_suffix('.pending')
    pending.write_text(json.dumps(value), encoding='utf-8')
    pending.replace(path)


def guardian(directory, nonce):
    import fcntl
    with (directory / 'alive.lock').open('w') as lease:
        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            snapshot = CoalitionAPI().own_snapshot()
            atomic_json(directory / 'ready.json', {'nonce': nonce, **snapshot})
            deadline = time.monotonic() + 75
            while not (directory / 'stop').exists() and time.monotonic() < deadline:
                time.sleep(0.05)
        except (OSError, AttributeError, Unsupported) as error:
            atomic_json(directory / 'ready.json', {'nonce': nonce,
                        'unavailable': type(error).__name__})
            return 2
    return 0


def ready(directory, nonce):
    import fcntl
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        path = directory / 'ready.json'
        if path.exists():
            data = json.loads(path.read_text(encoding='utf-8'))
            if data.get('nonce') != nonce:
                raise RuntimeError('fixture identity mismatch')
            if 'unavailable' in data:
                raise Unsupported('guardian API unavailable: ' + data['unavailable'])
            # Readiness alone cannot stand in for an actual live guardian.
            with (directory / 'alive.lock').open('r') as lease:
                try:
                    fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return data
            raise RuntimeError('guardian readiness without held alive lease')
        time.sleep(0.05)
    raise Unsupported('temporary user job did not become ready')


def launchctl(*args):
    return subprocess.run(['/bin/launchctl', *args], capture_output=True,
                          text=True, timeout=15, check=False)


def probe(report):
    if sys.platform != 'darwin':
        raise Unsupported('macOS runtime required; no native capability tested')
    if os.geteuid() == 0:
        raise Unsupported('ordinary-user probe refuses root execution')
    controller = CoalitionAPI().own_snapshot()
    report['controller'] = controller
    loaded = []
    outsider = None
    cleanup_errors = []
    with tempfile.TemporaryDirectory(prefix='oneirodex-coalition-') as temp:
        root = Path(temp)
        try:
            outside = root / 'outside'
            outside.mkdir()
            outside_nonce = uuid.uuid4().hex
            outsider = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                                         '--guardian', str(outside), outside_nonce],
                                        stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL)
            outside_info = ready(outside, outside_nonce)
            report['outside'] = outside_info
            jobs = []
            for _ in range(2):
                nonce = uuid.uuid4().hex
                directory = root / nonce
                directory.mkdir()
                label = 'com.oneirodex.fixture.' + nonce
                target = f'user/{os.geteuid()}/{label}'
                config = {'Label': label, 'RunAtLoad': True, 'KeepAlive': False,
                          'AbandonProcessGroup': True,
                          'ProgramArguments': [sys.executable, str(Path(__file__).resolve()),
                                               '--guardian', str(directory), nonce],
                          'StandardOutPath': str(directory / 'stdout'),
                          'StandardErrorPath': str(directory / 'stderr')}
                plist = directory / (label + '.plist')
                plist.write_bytes(plistlib.dumps(config))
                # Bootstrap can admit a job before returning an error/timeout.
                # Retain its exact owned label before the side effect starts.
                loaded.append((target, directory))
                result = launchctl('bootstrap', f'user/{os.geteuid()}', str(plist))
                if result.returncode != 0:
                    raise Unsupported(f'user-domain bootstrap failed ({result.returncode})')
                snapshot = ready(directory, nonce)
                if snapshot['active'] != 1:
                    raise RuntimeError('temporary job lacks guardian-only baseline')
                jobs.append(snapshot)
            report['jobs'] = jobs
            job_ids = [job['coalition_id'] for job in jobs]
            excluded = {controller['coalition_id'], outside_info['coalition_id'], 0, 1}
            if len(set(job_ids)) != 2 or any(cid in excluded for cid in job_ids):
                raise RuntimeError('temporary user jobs do not isolate resource coalitions')
            report['api_and_job_isolation_passed'] = True
        finally:
            for target, directory in reversed(loaded):
                (directory / 'stop').touch()
                try:
                    removed = launchctl('bootout', target)
                    observed = launchctl('print', target)
                    absent = (observed.returncode != 0 and
                              'could not find service' in observed.stderr.lower())
                    if observed.returncode == 0:
                        cleanup_errors.append('temporary job remains loaded after bootout')
                    elif removed.returncode != 0 and not absent:
                        cleanup_errors.append('temporary job bootout failed')
                except (OSError, subprocess.TimeoutExpired):
                    cleanup_errors.append('temporary job bootout unavailable')
            if outsider is not None:
                (root / 'outside' / 'stop').touch()
                try:
                    outsider.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    outsider.kill()
                    outsider.wait(timeout=5)
                    cleanup_errors.append('owned outsider required forced termination')
            report['cleanup'] = {'attempted_jobs': len(loaded),
                                 'errors': cleanup_errors}
            if cleanup_errors:
                raise RuntimeError('owned fixture cleanup did not complete normally')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--guardian', nargs=2, metavar=('DIRECTORY', 'NONCE'))
    args = parser.parse_args()
    if args.guardian:
        if sys.platform != 'darwin' or os.geteuid() == 0:
            return 2
        return guardian(Path(args.guardian[0]), args.guardian[1])
    if args.output is None:
        parser.error('--output is required for the controller')
    report = {'phase': 'ordinary-user-api-and-job-isolation',
              'platform': platform.system(), 'release': platform.release(),
              'architecture': platform.machine(),
              'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'api_and_job_isolation_passed': False,
              'family_recovery_acceptance': False,
              'remaining': ['detached descendants', 'exec/crash/API-denial controls',
                            'guardian-loss game survival', 'successive-launch isolation',
                            'production integration and account/package acceptance']}
    try:
        probe(report)
        report['status'] = 'phase_passed'
        code = 0
    except (OSError, AttributeError, Unsupported) as error:
        report['status'] = 'unsupported'
        report['reason'] = str(error) if isinstance(error, Unsupported) else type(error).__name__
        code = 2
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        report['status'] = 'failed'
        report['reason'] = str(error) if isinstance(error, RuntimeError) else type(error).__name__
        code = 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
