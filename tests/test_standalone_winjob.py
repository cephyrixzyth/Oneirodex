"""The standalone launcher's children end with it on Windows, even on a hard kill.

Ending the launcher from Task Manager used to leave PostgreSQL and the web
server running (found on a real Windows 11 run, 2026-10-02).
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def test_is_a_no_op_off_windows(monkeypatch):
    from oneirodex_standalone import winjob

    monkeypatch.setattr(winjob.sys, 'platform', 'linux')
    monkeypatch.setattr(winjob, '_JOB', None)
    assert winjob.tie_children_to_this_process() is False


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows job objects')
def test_a_hard_kill_of_the_launcher_ends_its_children(tmp_path):
    pid_file = tmp_path / 'child.pid'
    parent_code = (
        'import subprocess, sys, time\n'
        'from oneirodex_standalone.winjob import tie_children_to_this_process\n'
        'assert tie_children_to_this_process()\n'
        'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])\n'
        f'open({str(pid_file)!r}, "w").write(str(child.pid))\n'
        'time.sleep(120)\n'
    )
    parent = subprocess.Popen([sys.executable, '-c', parent_code], cwd=REPO)
    try:
        deadline = time.monotonic() + 30
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.2)
        child_pid = int(pid_file.read_text())
        parent.kill()  # TerminateProcess: no shutdown handlers run
        parent.wait(timeout=10)
        deadline = time.monotonic() + 10
        while _alive(child_pid) and time.monotonic() < deadline:
            time.sleep(0.2)
        assert not _alive(child_pid), 'the child outlived a hard-killed launcher'
    finally:
        if parent.poll() is None:
            parent.kill()


def _alive(pid: int) -> bool:
    out = subprocess.run(['tasklist', '/FI', f'PID eq {pid}', '/NH'], capture_output=True, text=True).stdout
    return str(pid) in out
