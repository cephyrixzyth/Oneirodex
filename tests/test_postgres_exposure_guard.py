"""The Compose Postgres publication guard preserves loopback legacy stacks."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "docker" / "postgres" / "guard-policy.sh"
SHELL = shutil.which("sh")
if SHELL is None and os.name == "nt":
    git_shell = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git" / "usr" / "bin" / "sh.exe"
    SHELL = str(git_shell) if git_shell.is_file() else None
if SHELL is None and os.name != "nt":
    SHELL = shutil.which("bash")


@pytest.mark.skipif(SHELL is None, reason="POSIX sh is required to exercise the container guard")
@pytest.mark.parametrize(
    ("bind", "password", "expected"),
    [
        ("127.0.0.1", "postgres", 0),
        ("127.0.0.2", "postgres", 0),
        ("::1", "postgres", 0),
        ("0.0.0.0", "postgres", 1),
        ("192.168.50.116", "postgres", 1),
        ("0.0.0.0", "", 1),
        ("0.0.0.0", "CHANGE_ME_replace_this", 1),
        ("0.0.0.0", "strong-password-value", 0),
        ("192.168.50.116", "strong-password-value", 0),
    ],
)
def test_publication_guard_requires_configured_password_for_non_loopback(bind, password, expected):
    env = os.environ.copy()
    env["POSTGRES_HOST_BIND"] = bind
    env["POSTGRES_PASSWORD"] = password
    result = subprocess.run(
        [SHELL, "-c", '. "$1" && oneirodex_guard_postgres_publication', "guard-test", str(POLICY)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == expected
    if expected:
        assert "refuses non-loopback publication" in result.stderr


@pytest.mark.skipif(SHELL is None, reason="POSIX sh is required to exercise the container guard")
def test_default_password_never_allows_non_loopback_publication():
    env = os.environ.copy()
    env["POSTGRES_HOST_BIND"] = "0.0.0.0"
    env["POSTGRES_PASSWORD"] = "postgres"
    result = subprocess.run(
        [SHELL, "-c", '. "$1" && oneirodex_guard_postgres_publication', "guard-test", str(POLICY)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "default" in result.stderr


def _run_persisted_password_probe(
    tmp_path,
    *,
    expected_password,
    actual_password,
    role_result="t",
    pg_ctl_start_result=0,
    pg_ctl_stop_result=0,
):
    pgdata = tmp_path / "pgdata"
    pgdata.mkdir()
    (pgdata / "PG_VERSION").write_text("17\n", encoding="ascii")
    log = tmp_path / "pg-ctl.log"
    env = os.environ.copy()
    env.update(
        PGDATA=str(pgdata),
        PG_CTL_LOG=str(log),
        EXPECTED_PASSWORD=actual_password,
        ROLE_RESULT=role_result,
        PG_CTL_START_RESULT=str(pg_ctl_start_result),
        PG_CTL_STOP_RESULT=str(pg_ctl_stop_result),
        POSTGRES_PASSWORD=expected_password,
        POSTGRES_USER="postgres",
        POSTGRES_DB="oneirodex",
    )
    command = r'''
. "$1"
gosu() { shift; "$@"; }
pg_ctl() {
    printf '%s\n' "$*" >> "$PG_CTL_LOG"
    case "$*" in
        *start) return "$PG_CTL_START_RESULT" ;;
        *stop) return "$PG_CTL_STOP_RESULT" ;;
        *) return 0 ;;
    esac
}
psql() {
    case "$*" in
        *--host=/var/run/postgresql*--port=55432*) printf '%s\n' "$ROLE_RESULT" ;;
        *--host=127.0.0.1*--port=55432*--username=postgres*--dbname=oneirodex*)
            [ "$PGPASSWORD" = "$EXPECTED_PASSWORD" ]
            ;;
        *) return 7 ;;
    esac
}
oneirodex_verify_persisted_postgres_password
'''
    return subprocess.run(
        [SHELL, "-c", command, "verify-probe", str(POLICY)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    ), log


@pytest.mark.skipif(SHELL is None, reason="POSIX sh is required to exercise the container guard")
def test_existing_volume_is_checked_with_a_private_loopback_listener(tmp_path):
    secret = "strong-password-value"
    result, log = _run_persisted_password_probe(
        tmp_path,
        expected_password=secret,
        actual_password=secret,
    )

    assert result.returncode == 0, result.stderr
    assert secret not in result.stdout + result.stderr
    calls = log.read_text(encoding="utf-8")
    assert "-c listen_addresses=127.0.0.1" in calls
    assert "-c port=55432" in calls
    assert "start" in calls and "stop" in calls


@pytest.mark.skipif(SHELL is None, reason="POSIX sh is required to exercise the container guard")
def test_existing_volume_with_stale_password_fails_closed_without_leaking_values(tmp_path):
    secret = "strong-password-value"
    result, log = _run_persisted_password_probe(
        tmp_path,
        expected_password=secret,
        actual_password="old-password",
    )

    assert result.returncode != 0
    assert "does not authenticate" in result.stderr
    assert secret not in result.stdout + result.stderr
    calls = log.read_text(encoding="utf-8")
    assert "-c listen_addresses=127.0.0.1" in calls
    assert "stop" in calls


@pytest.mark.skipif(SHELL is None, reason="POSIX sh is required to exercise the container guard")
def test_existing_volume_with_non_superuser_configured_account_fails_closed(tmp_path):
    secret = "strong-password-value"
    result, log = _run_persisted_password_probe(
        tmp_path,
        expected_password=secret,
        actual_password=secret,
        role_result="f",
    )

    assert result.returncode != 0
    assert "not the sole login-capable superuser" in result.stderr
    assert secret not in result.stdout + result.stderr
    assert "stop" in log.read_text(encoding="utf-8")


@pytest.mark.skipif(SHELL is None, reason="POSIX sh is required to exercise the container guard")
def test_fresh_volume_needs_no_preflight_database_process(tmp_path):
    pgdata = tmp_path / "new-pgdata"
    pgdata.mkdir()
    env = os.environ.copy()
    env.update(PGDATA=str(pgdata), POSTGRES_PASSWORD="new-strong-password")
    result = subprocess.run(
        [SHELL, "-c", '. "$1" && oneirodex_verify_persisted_postgres_password', "verify-fresh", str(POLICY)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(SHELL is None, reason="POSIX sh is required to exercise the container guard")
def test_probe_server_stop_failure_refuses_publication_and_retries_cleanup(tmp_path):
    secret = "strong-password-value"
    result, log = _run_persisted_password_probe(
        tmp_path,
        expected_password=secret,
        actual_password=secret,
        pg_ctl_stop_result=1,
    )

    assert result.returncode != 0
    assert "did not stop cleanly" in result.stderr
    assert secret not in result.stdout + result.stderr
    assert sum(line.endswith("stop") for line in log.read_text(encoding="utf-8").splitlines()) == 2

