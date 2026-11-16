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
from oneirodex_standalone.move import _sha256
from oneirodex.utils.save_crypto import maybe_decrypt

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
    encrypted_entries = [entry for entry in MANIFEST['files'] if entry.get('save_key_id')]
    check(len(encrypted_entries) == 3, 'three encrypted saves carried')
    for entry in encrypted_entries:
        path = LIBRARY / entry['path']
        try:
            plaintext = maybe_decrypt(path.read_bytes(), context=entry.get('save_context'))
            check(_sha256(plaintext) == entry['plain_sha256'],
                  f'{path.name} opens with the restored keyring and matches its plaintext digest')
        except Exception:  # noqa: BLE001 - report only the synthetic filename
            check(False, f'{path.name} is not readable with the restored keyring')
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
