"""Proof E, server side: what the move left in the server database and library.

    python check_server.py moved     # after a successful import
    python check_server.py untouched # after a refusal: nothing written

DATABASE_URL names the target database, SECRET_KEY is the server's, the move
folder is /move/bundle and the server library /srv/library. Exit 1 on any
failed check.
"""
import json
import os
import sys
from pathlib import Path

import psycopg2
from cryptography.fernet import Fernet, InvalidToken

from oneirodex_standalone.move import SAVE_MAGIC, save_key_for

LIBRARY = Path('/srv/library')
MANIFEST = json.loads(Path('/move/bundle/manifest.json').read_text(encoding='utf-8'))
FAILS = []


def check(ok, what):
    print(('ok   ' if ok else 'FAIL ') + what)
    if not ok:
        FAILS.append(what)


def untouched(cur):
    cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")
    check(cur.fetchone()[0] == 0, 'target database still has no tables')
    files = [p for p in LIBRARY.rglob('*') if p.is_file()] if LIBRARY.is_dir() else []
    check(not files, f'server library still empty ({len(files)} files)')


def moved(cur):
    cur.execute('SELECT version_num FROM alembic_version')
    check(cur.fetchone()[0] == MANIFEST['db']['alembic_revision'], 'schema revision carried')
    cur.execute('SELECT full_disk_path FROM games ORDER BY full_disk_path')
    paths = [r[0] for r in cur.fetchall()]
    check(len(paths) == 30 and all(p.startswith('/mnt/user/games/PC/Spike Game ') for p in paths),
          'game paths moved from C:\\Games to /mnt/user/games with / separators')
    check(not any('\\' in p for p in paths), 'no backslash left in game paths')
    cur.execute('SELECT last_scan_folder FROM libraries')
    check([r[0] for r in cur.fetchall()] == ['/mnt/user/games/PC'], 'library folder moved')
    cur.execute('SELECT storage_path, encrypted FROM emulator_saves ORDER BY id')
    saves = cur.fetchall()
    check(len(saves) == 10 and all(p.startswith(str(LIBRARY / 'saves') + '/') and Path(p).is_file() for p, _ in saves),
          'every save points into the server library and exists')
    server = Fernet(save_key_for(os.environ['SECRET_KEY']).encode('ascii'))
    standalone = Fernet(MANIFEST['save_key'].encode('ascii'))
    encrypted = [Path(p) for p, enc in saves if enc]
    check(len(encrypted) == 3, 'three encrypted saves carried')
    for path in encrypted:
        token = path.read_bytes()[len(SAVE_MAGIC):]
        server.decrypt(token)
        try:
            standalone.decrypt(token)
            check(False, f'{path.name} still opens with the standalone key')
        except InvalidToken:
            pass
    check(True, 'encrypted saves open with the server key and no longer with the standalone key')
    wanted = {e['path'] for e in MANIFEST['files']}
    check(any(p.startswith('themes/proof-upload/') for p in wanted), 'uploaded theme carried')
    check(not any(p.startswith(('themes/default/', 'icon-themes/', 'fonts/')) for p in wanted),
          'rebuilt-on-boot folders (default theme, presets, icon packs, fonts) not carried')
    check(all((LIBRARY / p).is_file() for p in wanted), f'all {len(wanted)} carried files present in the server library')


def main():
    conn = psycopg2.connect(os.environ['DATABASE_URL'])
    with conn, conn.cursor() as cur:
        {'moved': moved, 'untouched': untouched}[sys.argv[1]](cur)
    conn.close()
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
