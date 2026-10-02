"""The PostgreSQL a standalone install bundles and runs in user space (ADR 0011).

No service, no administrator rights: the cluster lives in the install's data
folder, is created once with ``initdb`` and runs only while the app does. It listens on 127.0.0.1 only, on a port chosen at
first run, with a generated password (scram-sha-256).

The server runs as the launcher's own child process (``postgres -D …``), so
a crash is seen and reaped immediately; ``pg_ctl`` is used only to stop it,
which works the same on Windows, macOS and Linux.

A bundle is found under ``pg_home`` in either layout:

* ``bin/`` — Windows / macOS archives (EDB-style), where the binaries find
  their own libraries;
* ``usr/lib/postgresql/<major>/bin/`` plus ``libs/`` — the relocated Linux
  bundle from the DESK-03 spike, which needs ``LD_LIBRARY_PATH``.

Nothing here prints or logs the password or a connection URL.
"""
from __future__ import annotations

import os
import secrets
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

EXE = '.exe' if os.name == 'nt' else ''
DB_USER = 'oneirodex'
DB_NAME = 'oneirodex'


class BundleError(RuntimeError):
    """The bundled PostgreSQL is missing, broken or refused to start."""


def make_private_dir(path: Path) -> None:
    """``mkdir -p``; a directory this call creates is owner-only (0700) on POSIX.

    An existing directory is left alone: ``--data-dir`` may be a folder the user
    chose and shares for other reasons. The secrets inside are protected by their
    own 0600 files (:func:`write_private_text`) either way. Windows keeps the
    default: the data folder lives under the user's own profile there.
    """
    path = Path(path)
    if os.name == 'nt':
        path.mkdir(parents=True, exist_ok=True)
    else:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)


def write_private_text(path: Path, text: str) -> None:
    """Write *text* to a new file that is owner-only from the first byte.

    ``write_text`` followed by ``chmod`` leaves a window in which the file (the
    database password, the secret key) is world-readable under the default umask,
    and a stale file from a crashed run would keep its old, looser mode. So any
    leftover is removed and the file is created with ``O_EXCL`` and mode 0600 in
    the same call (``O_EXCL`` also refuses to follow a link planted at the name).
    On Windows the mode bits are advisory and the profile directory is private.
    """
    path = Path(path)
    path.unlink(missing_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        handle = os.fdopen(fd, 'w', encoding='utf-8')
    except BaseException:
        os.close(fd)
        raise
    with handle:
        handle.write(text)


def find_bin_dir(pg_home: Path) -> Path:
    """The directory holding ``postgres``/``initdb``/``pg_ctl`` in a bundle."""
    candidates = [pg_home / 'bin']
    lib_root = pg_home / 'usr' / 'lib' / 'postgresql'
    if lib_root.is_dir():
        candidates += sorted((p / 'bin' for p in lib_root.iterdir()), reverse=True)  # newest major first
    for candidate in candidates:
        if all((candidate / f'{tool}{EXE}').is_file() for tool in ('postgres', 'initdb', 'pg_ctl')):
            return candidate
    raise BundleError('No PostgreSQL server binaries found in the bundle')


def free_port(host: str = '127.0.0.1') -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((host, 0))
        return probe.getsockname()[1]


def port_is_free(port: int, host: str = '127.0.0.1') -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host, port))
        except OSError:
            return False
        return True


@dataclass
class BundledPostgres:
    pg_home: Path
    data_dir: Path
    log_file: Path
    port: int
    password: str
    _proc: subprocess.Popen | None = field(default=None, repr=False)

    @property
    def bin_dir(self) -> Path:
        return find_bin_dir(self.pg_home)

    def env(self) -> dict:
        env = dict(os.environ)
        libs = self.pg_home / 'libs'
        if sys.platform.startswith('linux') and libs.is_dir():
            env['LD_LIBRARY_PATH'] = os.pathsep.join(filter(None, [str(libs), env.get('LD_LIBRARY_PATH')]))
        # pg_ctl and friends must never pick up a stray server from the environment.
        for key in ('PGHOST', 'PGPORT', 'PGDATA', 'PGUSER', 'PGPASSWORD', 'PGDATABASE', 'PGSERVICE'):
            env.pop(key, None)
        return env

    def _run(self, args, **kwargs) -> subprocess.CompletedProcess:
        return subprocess.run(args, env=self.env(), capture_output=True, text=True, **kwargs)

    def initialized(self) -> bool:
        return (self.data_dir / 'PG_VERSION').is_file()

    def init(self) -> None:
        """Create the cluster once. The locale is OS-independent so a later
        move to a household server does not depend on this machine's C library
        collation (ADR 0011)."""
        if self.initialized():
            return
        make_private_dir(self.data_dir.parent)
        pwfile = self.data_dir.parent / f'.pw-{secrets.token_hex(4)}'
        write_private_text(pwfile, self.password + '\n')
        try:
            result = self._run([
                str(self.bin_dir / f'initdb{EXE}'), '-D', str(self.data_dir), '-U', DB_USER,
                f'--pwfile={pwfile}', '--auth=scram-sha-256', '-E', 'UTF8',
                '--locale-provider=builtin', '--builtin-locale=C.UTF-8', '--locale=C',
            ], timeout=300)
        finally:
            pwfile.unlink(missing_ok=True)
        if result.returncode != 0:
            raise BundleError('initdb failed: ' + _last_line(result.stderr or result.stdout))

    def server_args(self) -> list[str]:
        opts = [
            'listen_addresses=127.0.0.1', f'port={self.port}',
            'max_connections=40', 'shared_buffers=32MB', 'jit=off',
        ]
        if os.name != 'nt':
            # TCP only: one connection story on every OS, and no socket files
            # to clean up in /tmp.
            opts.append('unix_socket_directories=')
        args = [str(self.bin_dir / f'postgres{EXE}'), '-D', str(self.data_dir)]
        for opt in opts:
            args += ['-c', opt]
        return args

    def _pg_ctl(self, *args, timeout=120) -> subprocess.CompletedProcess:
        return self._run([str(self.bin_dir / f'pg_ctl{EXE}'), *args, '-D', str(self.data_dir)], timeout=timeout)

    def _leftover_running(self) -> bool:
        """A server from an earlier launcher that is still up (the launcher crashed)."""
        return self.initialized() and self._pg_ctl('status', timeout=30).returncode == 0

    def in_use(self) -> bool:
        """Another process (a running launcher) has this cluster up."""
        return self._leftover_running()

    def running(self) -> bool:
        # The server is our own child process, so a crash shows up here at
        # once and is reaped by us. Asking pg_ctl instead was fooled by an
        # unreaped (zombie) server that it still reported as running.
        return self._proc is not None and self._proc.poll() is None

    def start(self, timeout: float = 60) -> None:
        if self.running():
            return
        if self._leftover_running():
            self._pg_ctl('stop', '-m', 'fast', '-w', '-t', '60')
        make_private_dir(self.log_file.parent)
        log = open(self.log_file, 'ab')
        try:
            self._proc = subprocess.Popen(self.server_args(), env=self.env(), stdout=log, stderr=subprocess.STDOUT,
                                          stdin=subprocess.DEVNULL)
        finally:
            log.close()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                raise BundleError('PostgreSQL exited during start-up; see ' + str(self.log_file))
            if self._accepts_connections():
                return
            time.sleep(0.25)
        raise BundleError('PostgreSQL did not become ready in time; see ' + str(self.log_file))

    def _accepts_connections(self) -> bool:
        import psycopg2
        try:
            psycopg2.connect(host='127.0.0.1', port=self.port, user=DB_USER, password=self.password,
                             dbname='postgres', connect_timeout=2).close()
        except psycopg2.OperationalError:
            return False
        return True

    def stop(self, mode: str = 'fast') -> None:
        """Stop the server; pg_ctl delivers the shutdown request on every OS."""
        if self.running() or self._leftover_running():
            self._pg_ctl('stop', '-m', mode, '-w', '-t', '60')
        if self._proc is not None:
            try:
                self._proc.wait(timeout=60)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
            self._proc = None

    def url(self, database: str = DB_NAME) -> str:
        from urllib.parse import quote
        return f'postgresql://{DB_USER}:{quote(self.password, safe="")}@127.0.0.1:{self.port}/{database}'

    def ensure_database(self) -> None:
        import psycopg2
        conn = psycopg2.connect(host='127.0.0.1', port=self.port, user=DB_USER, password=self.password,
                                dbname='postgres', connect_timeout=10)
        try:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute('SELECT 1 FROM pg_database WHERE datname = %s', (DB_NAME,))
                if cur.fetchone() is None:
                    cur.execute(f'CREATE DATABASE {DB_NAME}')
        finally:
            conn.close()


def _last_line(text: str) -> str:
    lines = [line for line in (text or '').splitlines() if line.strip()]
    return lines[-1][:300] if lines else 'no output'
