"""DESK-04 proof W: the standalone launcher's database half, natively on Windows.

Runs the real launcher and BundledPostgres against EDB's PostgreSQL 17 Windows
binaries, as the signed-in (non-administrator) user, in a throwaway data
folder: first-run cluster creation with the OS-independent collation, a
password-protected server on 127.0.0.1 only, crash detection and restart by
the supervisor, clean stop, and a second start that reuses the data.

    python scripts/spikes/desk03/run_proof_w.py --pg-home <EDB zip>/pgsql

The app server half is identical Python on every OS and is covered by proof D.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from oneirodex_standalone import launcher  # noqa: E402
from oneirodex_standalone.postgres import BundledPostgres  # noqa: E402

FAILS = []


def check(ok, what):
    print(('PASS ' if ok else 'FAIL ') + what)
    if not ok:
        FAILS.append(what)


def query(pg, sql):
    import psycopg2
    conn = psycopg2.connect(host='127.0.0.1', port=pg.port, user='oneirodex', password=pg.password,
                            dbname='oneirodex', connect_timeout=5)
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            return cur.fetchone()[0]
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--pg-home', required=True, type=Path)
    args = parser.parse_args()
    data = Path(tempfile.mkdtemp(prefix='oneirodex-proof-w-'))
    print(f'data folder: {data}')
    try:
        t0 = time.monotonic()
        first = subprocess.run([sys.executable, '-m', 'oneirodex_standalone', '--pg-home', str(args.pg_home),
                                '--data-dir', str(data), '--init-only'], cwd=REPO, capture_output=True, text=True)
        print(first.stdout.strip())
        check(first.returncode == 0, f'first run creates the cluster ({time.monotonic() - t0:.1f} s), exit {first.returncode}')
        if first.returncode:
            print(first.stderr[-2000:])
            return 1
        check((data / 'pgdata' / 'PG_VERSION').read_text().strip() == '17', 'cluster is PostgreSQL 17')
        check('(created)' in first.stdout, 'first run reports a new data folder')
        state = json.loads((data / 'standalone.json').read_text(encoding='utf-8'))
        check(len(state['db_password']) >= 24 and len(state['secret_key']) >= 48, 'generated secrets in standalone.json')

        pg = BundledPostgres(pg_home=args.pg_home.resolve(), data_dir=data / 'pgdata',
                             log_file=data / 'logs' / 'postgres.log', port=int(state['db_port']),
                             password=state['db_password'])
        pg.start()
        check(pg.running(), 'server starts as a child of the launcher')
        check(query(pg, "SELECT datlocprovider::text || ' ' || coalesce(datlocale, '-') FROM pg_database "
                        "WHERE datname = 'oneirodex'") == 'b C.UTF-8', 'builtin C.UTF-8 collation (portable dumps)')
        check(query(pg, 'SHOW listen_addresses') == '127.0.0.1', 'listens on 127.0.0.1 only')
        check(query(pg, 'SHOW password_encryption') == 'scram-sha-256', 'scram-sha-256 passwords')
        check(query(pg, 'SELECT version()').startswith('PostgreSQL 17'), 'server reports PostgreSQL 17')

        # A crash: the postmaster is killed outright, as Task Manager would.
        pg._proc.kill()
        pg._proc.wait(timeout=30)
        check(not pg.running(), 'a killed server is noticed at once')
        sup = launcher.Supervisor(pg, type('Up', (), {'poll': staticmethod(lambda: None)})())
        t1 = time.monotonic()
        check(sup.tick() is None and pg.running(), f'the supervisor restarts it ({time.monotonic() - t1:.1f} s)')
        check(query(pg, 'SELECT 1') == 1, 'and it answers again')

        pg.stop()
        check(not pg.running(), 'clean stop')
        log = (data / 'logs' / 'postgres.log').read_text(encoding='utf-8', errors='replace')
        check('database system is shut down' in log, 'postgres.log records the clean shutdown')

        second = subprocess.run([sys.executable, '-m', 'oneirodex_standalone', '--pg-home', str(args.pg_home),
                                 '--data-dir', str(data), '--init-only'], cwd=REPO, capture_output=True, text=True)
        check(second.returncode == 0 and '(created)' not in second.stdout, 'second start reuses the data folder')
        check(state['db_password'] not in log and state['secret_key'] not in (first.stdout + second.stdout + log),
              'no secret in the logs')
    finally:
        shutil.rmtree(data, ignore_errors=True)
    print(f"\nproof W: {'ALL CHECKS PASSED' if not FAILS else f'{len(FAILS)} CHECK(S) FAILED'}")
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
