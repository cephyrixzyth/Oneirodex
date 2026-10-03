"""Run Oneirodex standalone: bundled PostgreSQL + the normal server (ADR 0011).

    python -m oneirodex_standalone --pg-home <bundle> [--data-dir DIR] [--port 5006]

First run creates the data folder, a PostgreSQL cluster in it and a small
``standalone.json`` holding the generated database password, secret key and
database port (owner-readable only). Every run then starts the database, runs
``uvicorn asgi:asgi_app`` on 127.0.0.1 against it, restarts the database if it
dies, and stops both cleanly on Ctrl+C / SIGTERM or when the server exits.

The server itself is unchanged: this supplies ``DATABASE_URL`` and
``SECRET_KEY`` the way the Compose stack and the native installer do, plus
``ONEIRODEX_LIBRARY_DIR`` so everything the server writes lands in the data
folder and the install folder can stay read-only.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import signal
import subprocess
import sys
import time
from pathlib import Path

from oneirodex_standalone.postgres import (
    BundleError,
    BundledPostgres,
    free_port,
    make_private_dir,
    port_is_free,
    write_private_text,
)
from oneirodex_standalone.winjob import tie_children_to_this_process

logger = logging.getLogger('oneirodex_standalone')
REPO_ROOT = Path(__file__).resolve().parents[1]  # where asgi.py lives
STATE_FILE = 'standalone.json'
#: Give up restarting a database that keeps dying: more than this many
#: restarts inside the window means something is wrong that a restart won't fix.
MAX_RESTARTS, RESTART_WINDOW = 5, 600


def default_data_dir() -> Path:
    if os.name == 'nt':
        return Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local') / 'Oneirodex'
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'Oneirodex'
    return Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share') / 'oneirodex'


def load_state(root: Path) -> dict:
    """Read or create the standalone secrets. Never printed."""
    path = root / STATE_FILE
    if path.is_file():
        state = json.loads(path.read_text(encoding='utf-8'))
    else:
        state = {}
    changed = False
    if not state.get('db_password'):
        state['db_password'] = secrets.token_urlsafe(24)
        changed = True
    if not state.get('secret_key'):
        state['secret_key'] = secrets.token_urlsafe(48)
        changed = True
    port = state.get('db_port')
    if not port or (not port_is_free(int(port)) and not _cluster_owns_port(root, state)):
        state['db_port'] = free_port()
        changed = True
    if changed:
        save_state(root, state)
    return state


def _cluster_owns_port(root: Path, state: dict) -> bool:
    """The saved port is busy because our own cluster is already running on it."""
    pid_file = root / 'pgdata' / 'postmaster.pid'
    if not pid_file.is_file():
        return False
    lines = pid_file.read_text(encoding='utf-8', errors='replace').splitlines()
    return len(lines) > 3 and lines[3].strip() == str(state.get('db_port'))


def save_state(root: Path, state: dict) -> None:
    make_private_dir(root)
    path = root / STATE_FILE
    tmp = path.with_suffix('.tmp')
    # Owner-only from creation, not chmod-ed afterwards: the file holds the
    # database password and the secret key.
    write_private_text(tmp, json.dumps(state, indent=2))
    os.replace(tmp, path)


def server_env(pg: BundledPostgres, state: dict, root: Path) -> dict:
    env = dict(os.environ)
    env.update({
        'DATABASE_URL': pg.url(),
        'SECRET_KEY': state['secret_key'],
        # Themes, artwork, saves, caches: into the data folder, never the
        # install folder (oneirodex/utils/library_paths.py).
        'ONEIRODEX_LIBRARY_DIR': str(root / 'library'),
        # Served on 127.0.0.1 over plain HTTP: secure-only cookies would never be sent.
        'SESSION_COOKIE_SECURE': 'false',
        'REMEMBER_COOKIE_SECURE': 'false',
    })
    return env


#: The same one-time startup step the start scripts run before the server:
#: schema, migrations, setup state (``startweb.sh`` / ``startweb-docker.sh``).
INIT_SCRIPT = '; '.join([
    'import sys',
    'from oneirodex.init_manager import run_complete_startup_initialization',
    'sys.exit(0 if run_complete_startup_initialization() else 1)',
])


def init_command() -> list[str]:
    return [sys.executable, '-c', INIT_SCRIPT]


def server_command(port: int) -> list[str]:
    return [sys.executable, '-m', 'uvicorn', 'asgi:asgi_app', '--host', '127.0.0.1', '--port', str(port), '--workers', '1', '--timeout-graceful-shutdown', os.environ.get('UVICORN_GRACEFUL_TIMEOUT', '5')]


class Supervisor:
    """Keeps the database up while the server runs; stops both together."""

    def __init__(self, pg: BundledPostgres, server: subprocess.Popen, clock=time.monotonic):
        self.pg, self.server, self.clock = pg, server, clock
        self.restarts: list[float] = []
        self.stopping = False

    def tick(self) -> int | None:
        """One supervision step. Returns an exit code when it is time to stop."""
        code = self.server.poll()
        if code is not None:
            return code
        if not self.pg.running():
            now = self.clock()
            self.restarts = [t for t in self.restarts if now - t < RESTART_WINDOW] + [now]
            if len(self.restarts) > MAX_RESTARTS:
                logger.error('database keeps stopping; shutting down')
                return 1
            logger.warning('database stopped unexpectedly; restarting it')
            try:
                self.pg.start()
            except BundleError as exc:
                logger.error('%s', exc)
        return None

    def shutdown(self, timeout: float = 20) -> None:
        self.stopping = True
        if self.server.poll() is None:
            self.server.terminate()
            try:
                self.server.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.server.kill()
                self.server.wait()
        self.pg.stop()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='python -m oneirodex_standalone', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--pg-home', required=True, type=Path, help='root of the bundled PostgreSQL')
    parser.add_argument('--data-dir', type=Path, default=None, help=f'default: {default_data_dir()}')
    parser.add_argument('--port', type=int, default=int(os.environ.get('PORT') or 5006), help='web port on 127.0.0.1')
    parser.add_argument('--init-only', action='store_true', help='create the data folder and database, then stop')
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='[standalone] %(message)s', stream=sys.stdout)

    # Before anything is started: on Windows the database and web server then
    # end with the launcher even when it is killed outright (winjob.py).
    tie_children_to_this_process()
    root = (args.data_dir or default_data_dir()).resolve()
    state = load_state(root)
    pg = BundledPostgres(pg_home=args.pg_home.resolve(), data_dir=root / 'pgdata', log_file=root / 'logs' / 'postgres.log',
                         port=int(state['db_port']), password=state['db_password'])
    try:
        first_run = not pg.initialized()
        pg.init()
        pg.start()
        pg.ensure_database()
    except BundleError as exc:
        logger.error('%s', exc)
        return 2
    logger.info('data folder: %s%s', root, ' (created)' if first_run else '')
    if args.init_only:
        pg.stop()
        return 0

    env = server_env(pg, state, root)
    logger.info('preparing the database (first start takes longer)')
    if subprocess.run(init_command(), cwd=REPO_ROOT, env=env).returncode != 0:
        logger.error('startup initialization failed; not starting the server')
        pg.stop()
        return 3
    # As startweb.sh does after the same step: the server's readiness probe
    # and background workers read this to know initialization ran.
    env['ONEIRODEX_INITIALIZATION_COMPLETE'] = 'true'
    server = subprocess.Popen(server_command(args.port), cwd=REPO_ROOT, env=env)
    supervisor = Supervisor(pg, server)
    logger.info('Oneirodex on http://127.0.0.1:%s', args.port)

    def _stop(signum, _frame):
        raise KeyboardInterrupt

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _stop)
    code = 0
    try:
        while True:
            result = supervisor.tick()
            if result is not None:
                code = result
                break
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        supervisor.shutdown()
        logger.info('stopped')
    return code


if __name__ == '__main__':
    sys.exit(main())
