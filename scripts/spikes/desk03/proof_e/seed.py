"""Proof E, standalone side: fill a stopped standalone install with data worth moving.

Runs inside the throwaway standalone container (user nobody, no network) after
its first start. Starts the bundled PostgreSQL from the install's own state
file, runs the DESK-03 seed (Windows-style game paths), then adds files the
move must carry: artwork, a generated pack, an uploaded theme, and three saves
encrypted with this install's key. Stops the database again.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import psycopg2
from cryptography.fernet import Fernet

from oneirodex_standalone.move import SAVE_MAGIC, save_key_for
from oneirodex_standalone.postgres import BundledPostgres

DATA = Path('/data')
LIBRARY = DATA / 'library'


def main() -> int:
    state = json.loads((DATA / 'standalone.json').read_text(encoding='utf-8'))
    pg = BundledPostgres(pg_home=Path('/opt/oneirodex-postgres'), data_dir=DATA / 'pgdata',
                         log_file=DATA / 'logs' / 'postgres.log', port=int(state['db_port']),
                         password=state['db_password'])
    pg.start()
    try:
        env = dict(os.environ, DATABASE_URL=pg.url(), SAVES_ROOT=str(LIBRARY / 'saves'),
                   GAMES_ROOT='C:\\Games\\PC', SEED_THROWAWAY_CLUSTER='1')
        if subprocess.run([sys.executable, 'scripts/spikes/desk03/seed_standalone.py'], env=env).returncode:
            return 1
        conn = psycopg2.connect(pg.url())
        with conn, conn.cursor() as cur:
            cur.execute('SELECT uuid FROM games ORDER BY uuid LIMIT 5')
            for (uuid,) in cur.fetchall():
                (LIBRARY / 'images').mkdir(parents=True, exist_ok=True)
                (LIBRARY / 'images' / f'{uuid}_cover.jpg').write_bytes(os.urandom(2048))
            pack = LIBRARY / 'generated' / 'proof-pack'
            pack.mkdir(parents=True, exist_ok=True)
            (pack / 'tile_400x600.webp').write_bytes(os.urandom(1024))
            theme = LIBRARY / 'themes' / 'proof-upload'
            (theme / 'css').mkdir(parents=True, exist_ok=True)
            (theme / 'theme.json').write_text('{"name": "Proof upload"}', encoding='utf-8')
            (theme / 'css' / 'base.css').write_text(':root { --x: 1; }\n', encoding='utf-8')
            fernet = Fernet(save_key_for(state['secret_key']).encode('ascii'))
            cur.execute('SELECT id, storage_path FROM emulator_saves ORDER BY id LIMIT 3')
            for save_id, path in cur.fetchall():
                raw = Path(path).read_bytes()
                Path(path).write_bytes(SAVE_MAGIC + fernet.encrypt(raw))
                cur.execute('UPDATE emulator_saves SET encrypted = true WHERE id = %s', (save_id,))
        conn.close()
    finally:
        pg.stop()
    print('seed extras: 5 artwork files, 1 generated pack, 1 uploaded theme, 3 encrypted saves')
    return 0


if __name__ == '__main__':
    sys.exit(main())
