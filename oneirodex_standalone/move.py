"""Move a standalone Oneirodex to a household server (DESK-05, ADR 0011).

    python -m oneirodex_standalone export --pg-home DIR --to MOVE_DIR [--data-dir DIR] [--root NAME=PATH ...]
    python -m oneirodex_standalone import MOVE_DIR --expect FINGERPRINT [--library-dir DIR] [--root NAME=PATH ...] [--pg-bin DIR]

export runs on the standalone machine while Oneirodex is stopped. It writes a
move folder: the database (pg_dump custom format), your files (artwork, saves,
chat uploads, mods, cheats, assists, uploaded themes) and a manifest of
checksums and per-table digests. It prints the folder's fingerprint. Nothing on
the standalone machine changes.

import runs where the server's database is reachable, normally in the server's
app container. DATABASE_URL must name an EMPTY database and SECRET_KEY must be
the server's own. --expect is the fingerprint export printed: the move folder
may travel over a share, and a restore runs its SQL on the server, so the
folder is trusted only when it matches what you exported. The import checks
the folder, restores the database in one transaction, copies the files into
the server's library, rewrites machine paths (--root NAME=PATH for every folder
named at export), re-encrypts encrypted saves for the server's key, and
verifies the result against the manifest row for row. If anything after the
restore fails, the files it copied are removed; drop the target database to
roll back, and run it again when ready.

The folder holds your saves, members' password hashes and settings, and, when
any saves are encrypted, the key that opens them: keep it private and delete it
afterwards.

Exit status: 0 moved and verified; 1 refused or verification failed (see the
message); 2 usage error.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

FORMAT = 'oneirodex-household-move/1'
#: The server's runtime folder; always a root, filled in on both ends.
LIBRARY_ROOT = 'library'
#: Folders under the library that hold members' own files. Everything else in
#: it (themes, icon packs, fonts, caches) is rebuilt by the server on boot.
USER_FOLDERS = ('images', 'generated', 'saves', 'chat-attachments', 'chat-emoji', 'mods', 'cheats', 'assists')
#: oneirodex/utils/preset_themes.py marks the themes it generates with this key.
PRESET_MARKER_KEY = 'oneirodex_preset'
#: oneirodex/utils/save_crypto.py: encrypted save files start with this.
SAVE_MAGIC = b'GTENC1:'
#: Columns holding machine paths (P05 audit). Any other text column named
#: *path* or *folder* is picked up at run time, so a new one is not missed.
KNOWN_PATH_COLUMNS = {
    ('games', 'full_disk_path'),
    ('libraries', 'last_scan_folder'),
    ('emulator_saves', 'storage_path'),
}
SKIP_TABLES = {'alembic_version'}
#: A path that names a place on one machine: /x, C:\x or C:/x, \\server\share.
ABSOLUTE_PATH_RE = r'^([A-Za-z]:[\\/]|/|\\\\)'
#: The app's own table and column names. Anything else in a restored dump is
#: refused rather than spliced into SQL.
_IDENT = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
#: Shortest fingerprint prefix --expect accepts (64 bits).
MIN_FINGERPRINT = 16
CHUNK = 1 << 20
REPO_ROOT = Path(__file__).resolve().parents[1]


class Refused(Exception):
    """A check failed or the result did not verify. Exit status 1."""


class UsageError(Exception):
    """The command line was wrong. Exit status 2."""


# ---------------------------------------------------------------- helpers

def _norm_root(path: str) -> str:
    """A folder path without a trailing separator, so ``C:\\Games\\`` and
    ``C:\\Games`` match the same rows and a sibling ``C:\\Games2`` matches none."""
    trimmed = path.rstrip('/\\')
    if not trimmed or re.fullmatch(r'[A-Za-z]:', trimmed):
        raise UsageError(f'--root must name a folder, not {path!r}')
    return trimmed


def _pairs(values) -> dict[str, str]:
    out = {}
    for item in values or []:
        name, sep, value = item.partition('=')
        if not sep or not name or not value:
            raise UsageError(f'--root must be NAME=PATH, got {item!r}')
        if name == LIBRARY_ROOT:
            raise UsageError(f'--root {LIBRARY_ROOT}=… is set for you (the Oneirodex library folder)')
        out[name] = _norm_root(value)
    return out


def _sha256(data_or_path) -> str:
    digest = hashlib.sha256()
    if isinstance(data_or_path, bytes):
        digest.update(data_or_path)
    else:
        with open(data_or_path, 'rb') as handle:
            while block := handle.read(CHUNK):
                digest.update(block)
    return digest.hexdigest()


def _quote(name: str) -> str:
    if not _IDENT.match(name or ''):
        raise Refused(f'unexpected table or column name {name!r} in the database')
    return f'"{name}"'


def is_windows_path(path: str) -> bool:
    return bool(re.match(r'^[A-Za-z]:[\\/]', path)) or path.startswith('\\\\')


def save_key_for(secret_key: str) -> str:
    """The Fernet key oneirodex/utils/save_crypto.py derives from SECRET_KEY."""
    return base64.urlsafe_b64encode(hashlib.sha256((secret_key or 'oneirodex').encode('utf-8')).digest()).decode('ascii')


def _fernet(key: str):
    from cryptography.fernet import Fernet
    return Fernet(key.encode('ascii'))


def _plain_save(data: bytes, key: str) -> bytes:
    return _fernet(key).decrypt(data[len(SAVE_MAGIC):]) if data.startswith(SAVE_MAGIC) else data


def _opens_to(path: Path, key: str, plain_sha256: str) -> bool:
    try:
        return _sha256(_plain_save(path.read_bytes(), key)) == plain_sha256
    except Exception:  # noqa: BLE001 — a save that does not open is simply not a match
        return False


# ---------------------------------------------------------------- database

def _engine(url: str):
    from sqlalchemy import create_engine
    from sqlalchemy.dialects import registry

    # As config.keep_psycopg2_for_plain_postgresql_urls (not imported here: it
    # needs the server's environment): SQLAlchemy 2.1 maps a bare postgresql://
    # to psycopg v3, which is not installed.
    registry.register('postgresql', 'sqlalchemy.dialects.postgresql.psycopg2', 'PGDialect_psycopg2')
    return create_engine(url, pool_pre_ping=False)


def _schema(conn) -> dict[str, list[tuple[str, str]]]:
    from sqlalchemy import text
    rows = conn.execute(text(
        "SELECT table_name, column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'public' ORDER BY table_name, ordinal_position"
    )).all()
    tables: dict[str, list[tuple[str, str]]] = {}
    for table, column, data_type in rows:
        if table not in SKIP_TABLES:
            tables.setdefault(table, []).append((column, data_type))
    return tables


def _path_columns(tables) -> set[tuple[str, str]]:
    found = set(KNOWN_PATH_COLUMNS)
    for table, columns in tables.items():
        for column, data_type in columns:
            if data_type in ('text', 'character varying') and ('path' in column or 'folder' in column):
                found.add((table, column))
    return {(t, c) for (t, c) in found if t in tables and any(c == col for col, _ in tables[t])}


def _ordered(roots: dict[str, str]) -> list[tuple[str, str]]:
    return sorted(roots.items(), key=lambda kv: -len(kv[1]))  # a nested root wins over its parent


def _under_sql(col: str, key: str, root: str, params: dict) -> str:
    """SQL true when ``col`` is ``root`` itself or inside it (a whole folder:
    ``C:\\Games2`` is not inside ``C:\\Games``)."""
    params.update({f'{key}r': root, f'{key}f': root + '/', f'{key}b': root + '\\', f'{key}n': len(root) + 1})
    return f'({col} = :{key}r OR left({col}, :{key}n) = :{key}f OR left({col}, :{key}n) = :{key}b)'


def _relative_sql(col: str, roots: dict[str, str], params: dict) -> str:
    """SQL rewriting a path under a named root to ``NAME:/rest`` with ``/`` separators,
    so the same file compares equal on Windows and on the server."""
    whens = []
    params['bs'] = '\\'
    for i, (name, prefix) in enumerate(_ordered(roots)):
        params[f'rn{i}'], params[f'rl{i}'] = f'{name}:', len(prefix)
        whens.append(f"WHEN {_under_sql(col, f'r{i}', prefix, params)} "
                     f"THEN :rn{i} || replace(substr({col}, :rl{i} + 1), :bs, '/')")
    return f"CASE {' '.join(whens)} ELSE {col} END" if whens else col


def snapshot_db(url: str, roots: dict[str, str]) -> dict:
    from sqlalchemy import text
    engine = _engine(url)
    try:
        with engine.connect() as conn:
            revision = conn.execute(text('SELECT version_num FROM alembic_version')).scalar()
            tables = _schema(conn)
            path_cols = _path_columns(tables)
            digests, unrooted = {}, {}
            for table, columns in sorted(tables.items()):
                params: dict = {}
                parts = [_relative_sql(_quote(c), roots, params) if (table, c) in path_cols else _quote(c)
                         for c, _ in columns]
                count, digest = conn.execute(text(
                    # COLLATE "C": the standalone and the server sort text
                    # differently (builtin C.UTF-8 vs en_US), and the digest
                    # must not depend on it.
                    f"SELECT count(*), md5(coalesce(string_agg(x, E'\\n' ORDER BY x COLLATE \"C\"), '')) "
                    f"FROM (SELECT ROW({', '.join(parts)})::text AS x FROM {_quote(table)}) s"
                ), params).one()
                digests[table] = {'rows': count, 'md5': digest}
            for table, column in sorted(path_cols):
                col, params = _quote(column), {'absolute': ABSOLUTE_PATH_RE}
                inside = ' OR '.join(_under_sql(col, f'u{i}', p, params) for i, p in enumerate(roots.values())) or 'false'
                # Only absolute paths are tied to a machine; a folder name
                # ('extras') or a relative path moves as it is.
                unrooted[f'{table}.{column}'] = conn.execute(text(
                    f"SELECT count(*) FROM {_quote(table)} WHERE {col} ~ :absolute AND NOT ({inside})"
                ), params).scalar()
            identity = {
                'game_uuids': conn.execute(text(
                    "SELECT count(*), md5(coalesce(string_agg(uuid, ',' ORDER BY uuid COLLATE \"C\"), '')) "
                    "FROM games")).one()._asdict(),
                'entitlements': conn.execute(text(
                    "SELECT count(*), md5(coalesce(string_agg(concat_ws('|', user_id, store, external_app_id, "
                    "matched_game_uuid, match_revision, match_reviewed), ',' ORDER BY user_id, store COLLATE \"C\", "
                    "external_app_id COLLATE \"C\"), '')) FROM user_owned_titles")).one()._asdict(),
                'match_decisions': conn.execute(text(
                    "SELECT count(*), md5(coalesce(string_agg(concat_ws('|', title_id, revision, before_uuid, after_uuid, "
                    "action), ',' ORDER BY title_id, revision), '')) FROM ownership_match_decisions")).one()._asdict(),
                'saves': conn.execute(text(
                    "SELECT count(*), md5(coalesce(string_agg(concat_ws('|', user_id, game_uuid, slot_name, filename, "
                    "size_bytes, encrypted), ',' ORDER BY user_id, game_uuid COLLATE \"C\", slot_name COLLATE \"C\"), '')) "
                    "FROM emulator_saves")).one()._asdict(),
            }
            behind = {}
            for table, columns in tables.items():
                if not any(c == 'id' for c, _ in columns):
                    continue
                seq = conn.execute(text("SELECT pg_get_serial_sequence(:t, 'id')"), {'t': table}).scalar()
                if seq:
                    max_id = conn.execute(text(f'SELECT coalesce(max(id), 0) FROM {_quote(table)}')).scalar()
                    last = conn.execute(text('SELECT coalesce(pg_sequence_last_value(CAST(:s AS regclass)), 0)'),
                                        {'s': seq}).scalar()
                    if last < max_id:
                        behind[table] = {'max_id': max_id, 'last_value': last}
    finally:
        engine.dispose()
    return {'alembic_revision': revision, 'tables': digests, 'path_columns': sorted(f'{t}.{c}' for t, c in path_cols),
            'unrooted_paths': unrooted, 'identity': identity, 'sequences_behind': behind}


def database_is_empty(url: str) -> bool:
    from sqlalchemy import text
    engine = _engine(url)
    try:
        with engine.connect() as conn:
            return not conn.execute(text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema NOT IN ('pg_catalog', 'information_schema')")).scalar()
    finally:
        engine.dispose()


def remap_paths(url: str, old_roots: dict[str, str], new_roots: dict[str, str]) -> dict[str, int]:
    """Rewrite every rooted path to its new root in one transaction, converting
    separators to the new root's style (a Windows laptop to a Linux server)."""
    from sqlalchemy import text
    changed = {}
    engine = _engine(url)
    try:
        with engine.begin() as conn:  # all rewritten, or none
            for table, column in sorted(_path_columns(_schema(conn))):
                col, params, whens, matches = _quote(column), {}, [], []
                for i, (name, old) in enumerate(_ordered(old_roots)):
                    new = new_roots[name]
                    # Separators change only across operating systems: a Linux
                    # file name may legally contain a backslash.
                    if is_windows_path(old) == is_windows_path(new):
                        sep_from = sep_to = '/'
                    else:
                        sep_from, sep_to = ('/', '\\') if is_windows_path(new) else ('\\', '/')
                    params.update({f'l{i}': len(old), f'n{i}': new, f'f{i}': sep_from, f't{i}': sep_to})
                    under = _under_sql(col, f'm{i}', old, params)
                    whens.append(f'WHEN {under} THEN :n{i} || replace(substr({col}, :l{i} + 1), :f{i}, :t{i})')
                    matches.append(under)
                if not whens:
                    continue
                result = conn.execute(text(
                    f"UPDATE {_quote(table)} SET {col} = CASE {' '.join(whens)} ELSE {col} END WHERE {' OR '.join(matches)}"
                ), params)
                if result.rowcount:
                    changed[f'{table}.{column}'] = result.rowcount
    finally:
        engine.dispose()
    return changed


def _libpq_env(url: str) -> dict:
    """Connection settings for pg_restore through the environment, so the
    password never appears on a command line. Query settings (host, port,
    sslmode, certificates) are carried too, so pg_restore reaches the same
    server as the rest of the import."""
    parsed = urlparse(url)
    query = {k: v[0] for k, v in parse_qs(parsed.query).items() if v}
    env = {key: value for key, value in os.environ.items() if not key.startswith('PG')}
    env.update({
        'PGHOST': parsed.hostname or query.get('host', ''),
        'PGPORT': str(parsed.port or query.get('port') or 5432),
        'PGUSER': unquote(parsed.username or query.get('user', '')),
        'PGPASSWORD': unquote(parsed.password or query.get('password', '')),
        'PGDATABASE': unquote(parsed.path.lstrip('/') or query.get('dbname', '')),
    })
    for key, var in (('sslmode', 'PGSSLMODE'), ('sslrootcert', 'PGSSLROOTCERT'), ('sslcert', 'PGSSLCERT'),
                     ('sslkey', 'PGSSLKEY'), ('options', 'PGOPTIONS')):
        if query.get(key):
            env[var] = query[key]
    return {k: v for k, v in env.items() if v != ''}


def _tool(name: str, pg_bin: str | None) -> str:
    exe = name + ('.exe' if os.name == 'nt' else '')
    found = str(Path(pg_bin) / exe) if pg_bin else shutil.which(exe)
    if not found or not Path(found).is_file():
        raise Refused(f'{name} not found: install the PostgreSQL 17 client tools or pass --pg-bin')
    return found


def _bundle_libs(tool: Path) -> Path | None:
    """The shared libraries of a Linux standalone bundle the tool came from, so
    a server without the PostgreSQL 17 client can use a copy of the bundle."""
    if not sys.platform.startswith('linux'):
        return None
    for parent in list(tool.resolve().parents)[:6]:
        if (parent / 'libs').is_dir() and any((parent / 'libs').glob('libpq.so*')):
            return parent / 'libs'
    return None


def _major(version_output: str) -> int:
    match = re.search(r'(\d+)(?:\.\d+)?', version_output or '')
    return int(match.group(1)) if match else 0


def restore(url: str, dump: Path, pg_bin: str | None, dump_major: int) -> None:
    pg_restore = _tool('pg_restore', pg_bin)
    env = _libpq_env(url)
    libs = _bundle_libs(Path(pg_restore))
    if libs:
        env['LD_LIBRARY_PATH'] = os.pathsep.join(filter(None, [str(libs), env.get('LD_LIBRARY_PATH')]))
    probe = subprocess.run([pg_restore, '--version'], env=env, capture_output=True, text=True)
    have = _major(probe.stdout)
    if probe.returncode != 0 or not have:
        last = [line for line in probe.stderr.splitlines() if line.strip()][-1:] or ['no output']
        raise Refused(f'pg_restore did not run: {last[0][:300]}')
    if have < dump_major:
        raise Refused(f'pg_restore {have} cannot read a PostgreSQL {dump_major} dump; use the PostgreSQL {dump_major} client')
    result = subprocess.run(
        [pg_restore, '--single-transaction', '--exit-on-error', '--no-owner', '--no-privileges',
         '-d', env.get('PGDATABASE', ''), str(dump)],
        env=env, capture_output=True, text=True)
    if result.returncode != 0:
        last = [line for line in result.stderr.splitlines() if line.strip()][-1:] or ['no output']
        raise Refused(f'restore failed and was rolled back: {last[0][:300]}')


def check_schema_known(revision: str | None) -> None:
    """Refuse a move folder from a newer Oneirodex than this server: its schema
    revision must be one the server's own migrations know."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    ini = REPO_ROOT / 'alembic.ini'
    if not ini.is_file():
        raise Refused('cannot check the schema version: alembic.ini is missing from this install')
    try:
        known = ScriptDirectory.from_config(Config(str(ini))).get_revision(revision) is not None
    except Exception:  # noqa: BLE001 — an unknown revision raises
        known = False
    if not known:
        raise Refused(f'the move folder comes from a newer Oneirodex (schema {revision}); update the server first')


# ---------------------------------------------------------------- files

def carried_files(library: Path) -> list[Path]:
    """Members' own files under the library, relative to it."""
    out = []
    for folder in USER_FOLDERS:
        base = library / folder
        if base.is_dir():
            out.extend(p.relative_to(library) for p in base.rglob('*') if p.is_file() and not p.is_symlink())
    themes = library / 'themes'
    if themes.is_dir():
        for theme in sorted(p for p in themes.iterdir() if p.is_dir() and p.name != 'default'):
            try:
                data = json.loads((theme / 'theme.json').read_text(encoding='utf-8'))
            except (OSError, ValueError):
                data = {}
            if PRESET_MARKER_KEY in data:
                continue  # regenerated by the server
            out.extend(p.relative_to(library) for p in theme.rglob('*') if p.is_file() and not p.is_symlink())
    return sorted(out, key=lambda p: p.as_posix())


def is_carried_path(rel: str) -> bool:
    """The import accepts only what export carries (see carried_files)."""
    parts = rel.split('/')
    if parts[0] in USER_FOLDERS:
        return len(parts) > 1
    return parts[0] == 'themes' and len(parts) > 2 and parts[1] != 'default'


def snapshot_files(library: Path, save_key: str | None) -> list[dict]:
    from cryptography.fernet import InvalidToken

    entries = []
    for rel in carried_files(library):
        path = library / rel
        entry = {'path': rel.as_posix(), 'size': path.stat().st_size, 'sha256': _sha256(path)}
        if rel.parts[0] == 'saves' and save_key:
            data = path.read_bytes()
            if data.startswith(SAVE_MAGIC):
                try:
                    entry['plain_sha256'] = _sha256(_plain_save(data, save_key))
                except InvalidToken:
                    raise Refused(f'{rel.as_posix()} is marked encrypted but does not open with this install\'s key; '
                                  'remove or replace that save, then export again') from None
        entries.append(entry)
    return entries


def _safe_join(base: Path, rel: str, where: str) -> Path:
    parts = re.split(r'[\\/]', rel or '')
    if (not rel or rel.startswith(('/', '\\')) or re.match(r'^[A-Za-z]:', rel)
            or '..' in parts or '' in parts):
        raise Refused(f'unsafe path in the manifest: {rel!r}')
    target = (base / rel).resolve()
    if not target.is_relative_to(base.resolve()):
        raise Refused(f'{where}: {rel!r} resolves outside {base} (a symbolic link?)')
    return target


def _copy_checked(src: Path, dest: Path, sha256: str) -> None:
    """Copy one bundle file, hashing what is actually read, so a file swapped
    after the bundle check cannot land in the library."""
    if src.is_symlink():
        raise Refused(f'{src.name} in the move folder is a symbolic link')
    # O_NONBLOCK keeps a FIFO swapped in after check_bundle from blocking the
    # open until some writer shows up; the descriptor must be a regular file.
    flags = (os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
             | getattr(os, 'O_NONBLOCK', 0))
    digest = hashlib.sha256()
    tmp = dest.with_name(dest.name + '.moving')
    fd = os.open(src, flags)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise Refused(f'{src.name} in the move folder is not a regular file')
        fin = os.fdopen(fd, 'rb')
    except BaseException:
        os.close(fd)
        raise
    try:
        with fin, open(tmp, 'wb') as fout:
            while block := fin.read(CHUNK):
                digest.update(block)
                fout.write(block)
        if digest.hexdigest() != sha256:
            raise Refused(f'{src.name} changed in the move folder while it was being copied')
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------- export

def export(args) -> int:
    from oneirodex_standalone.launcher import STATE_FILE, default_data_dir, load_state
    from oneirodex_standalone.postgres import DB_NAME, DB_USER, EXE, BundleError, BundledPostgres

    root = (args.data_dir or default_data_dir()).resolve()
    if not (root / STATE_FILE).is_file():
        raise Refused(f'no standalone install in {root}')
    out = Path(args.to).resolve()
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise Refused('the move folder must be new or empty')
    operator_roots = _pairs(args.root)
    state = load_state(root)
    pg = BundledPostgres(pg_home=args.pg_home.resolve(), data_dir=root / 'pgdata', log_file=root / 'logs' / 'postgres.log',
                         port=int(state['db_port']), password=state['db_password'])
    if not pg.initialized():
        raise Refused(f'no database in {root}')
    if pg.in_use():
        raise Refused('Oneirodex is running: stop it, then export')
    library = root / 'library'
    roots = {LIBRARY_ROOT: _norm_root(str(library)), **operator_roots}

    # Written into a private (0700) folder beside the target and renamed at the
    # end, so a failed export leaves nothing half-written behind.
    out.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='.oneirodex-move-', dir=out.parent))
    try:
        try:
            pg.start()
        except BundleError as exc:
            raise Refused(str(exc)) from None
        try:
            db = snapshot_db(pg.url(), roots)
            pg_dump = pg.bin_dir / f'pg_dump{EXE}'
            dump_major = _major(subprocess.run([str(pg_dump), '--version'], env=pg.env(),
                                               capture_output=True, text=True).stdout)
            result = subprocess.run(
                [str(pg_dump), '-Fc', '-h', '127.0.0.1', '-p', str(pg.port), '-U', DB_USER,
                 '-f', str(work / 'db.dump'), DB_NAME],
                env={**pg.env(), 'PGPASSWORD': pg.password}, capture_output=True, text=True)
            if result.returncode != 0:
                raise Refused(f'pg_dump failed: {(result.stderr.strip().splitlines() or ["no output"])[-1][:300]}')
        finally:
            pg.stop()

        save_key = save_key_for(state['secret_key'])
        files = snapshot_files(library, save_key)
        for entry in files:
            target = work / 'files' / entry['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(library / entry['path'], target)
        encrypted = any('plain_sha256' in e for e in files)
        manifest = {
            'format': FORMAT, 'roots': roots, 'db': db, 'files': files,
            'db_dump': {'size': (work / 'db.dump').stat().st_size, 'sha256': _sha256(work / 'db.dump'),
                        'pg_major': dump_major},
            # Only when there is something it opens. See the module docstring.
            'save_key': save_key if encrypted else None,
        }
        raw = json.dumps(manifest, indent=2, sort_keys=True)
        (work / 'manifest.json').write_text(raw, encoding='utf-8')
        fingerprint = _sha256(raw.encode('utf-8'))
        (work / 'manifest.sha256').write_text(fingerprint + '\n', encoding='utf-8')
        if out.exists():
            out.rmdir()
        os.replace(work, out)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise

    rows = sum(t['rows'] for t in db['tables'].values())
    print(f'exported: {len(db["tables"])} tables, {rows} rows, {len(files)} files'
          f'{", encrypted saves (key included)" if encrypted else ""} -> {out}')
    print(f'fingerprint: {fingerprint}')
    print('  Keep this line: the import asks for it (--expect) to prove the folder arrived unchanged.')
    outside = {k: v for k, v in db['unrooted_paths'].items() if v}
    if outside:
        print(f'note: paths outside the named folders keep their old value on the server: {outside}. '
              'Name their folders with --root NAME=PATH to move them too.')
    bios = library / 'bios'
    if bios.is_dir() and any(p.is_file() for p in bios.rglob('*')):
        print('note: BIOS files are not carried; copy them to the server yourself (docs/runbooks/emulator-bios.md).')
    return 0


# ---------------------------------------------------------------- import

def check_bundle(bundle: Path, expect: str) -> dict:
    """The manifest, after proving the folder is the one exported (fingerprint)
    and is complete and unchanged (checksums)."""
    try:
        raw = (bundle / 'manifest.json').read_text(encoding='utf-8')
    except OSError:
        raise Refused(f'{bundle} is not a move folder (manifest missing)') from None
    fingerprint = _sha256(raw.encode('utf-8'))
    expect = (expect or '').strip().lower()
    if len(expect) < MIN_FINGERPRINT or not re.fullmatch(r'[0-9a-f]+', expect):
        raise UsageError(f'--expect needs the fingerprint export printed (at least {MIN_FINGERPRINT} hex characters)')
    if not fingerprint.startswith(expect):
        raise Refused('the move folder does not match the fingerprint from export: it was changed or is a different folder')
    manifest = json.loads(raw)
    if manifest.get('format') != FORMAT:
        raise Refused(f'unsupported move folder format {manifest.get("format")!r}')
    problems = []
    dump = bundle / 'db.dump'
    if dump.is_symlink() or not dump.is_file() or _sha256(dump) != manifest['db_dump']['sha256']:
        problems.append('db.dump missing or changed')
    for entry in manifest['files']:
        if not is_carried_path(entry['path']):
            raise Refused(f'the manifest lists {entry["path"]!r}, which export never carries')
        path = _safe_join(bundle / 'files', entry['path'], 'move folder')
        if path.is_symlink() or not path.is_file() or _sha256(path) != entry['sha256']:
            problems.append(f'files/{entry["path"]} missing or changed')
    if problems:
        raise Refused(f'move folder incomplete or altered ({len(problems)}): ' + '; '.join(problems[:5]))
    return manifest


def default_server_library() -> Path:
    """The server's library folder: the same rule as oneirodex/utils/library_paths.py."""
    explicit = (os.environ.get('ONEIRODEX_LIBRARY_DIR') or '').strip()
    return Path(explicit) if explicit else REPO_ROOT / 'oneirodex' / 'static' / 'library'


def _file_conflicts(manifest: dict, library: Path, target_key: str | None = None) -> list[str]:
    conflicts = []
    for entry in manifest['files']:
        target = _safe_join(library, entry['path'], 'server library')
        if not target.exists():
            continue
        if target.is_file() and _sha256(target) == entry['sha256']:
            continue
        if (target.is_file() and 'plain_sha256' in entry and target_key
                and _opens_to(target, target_key, entry['plain_sha256'])):
            continue  # this save, already re-encrypted for this server by an earlier import
        conflicts.append(entry['path'])
    return conflicts


def rekey_saves(library: Path, manifest: dict, target_key: str) -> int:
    source_key = manifest.get('save_key')
    if not source_key or source_key == target_key:
        return 0
    changed = 0
    for entry in manifest['files']:
        if 'plain_sha256' not in entry:
            continue
        path = _safe_join(library, entry['path'], 'server library')
        plain = _plain_save(path.read_bytes(), source_key)
        tmp = path.with_name(path.name + '.rekey')
        tmp.write_bytes(SAVE_MAGIC + _fernet(target_key).encrypt(plain))
        os.replace(tmp, path)
        changed += 1
    return changed


def verify(url: str, manifest: dict, new_roots: dict[str, str], library: Path, target_key: str | None) -> list[str]:
    expected, problems = manifest['db'], []
    actual = snapshot_db(url, new_roots)
    if actual['alembic_revision'] != expected['alembic_revision']:
        problems.append(f"schema revision {actual['alembic_revision']} != {expected['alembic_revision']}")
    for table, want in expected['tables'].items():
        if actual['tables'].get(table) != want:
            problems.append(f'table {table}: expected {want}, got {actual["tables"].get(table)}')
    for table in sorted(set(actual['tables']) - set(expected['tables'])):
        problems.append(f'unexpected table {table}')
    if actual['identity'] != expected['identity']:
        problems.append('identity digests differ (game UUIDs / entitlements / decisions / saves)')
    if actual['unrooted_paths'] != expected['unrooted_paths']:
        problems.append(f"paths outside the named folders differ: {actual['unrooted_paths']}")
    if actual['sequences_behind']:
        problems.append(f"sequences behind their tables: {actual['sequences_behind']}")
    for entry in manifest['files']:
        path = _safe_join(library, entry['path'], 'server library')
        if not path.is_file():
            problems.append(f'missing file {entry["path"]}')
        elif 'plain_sha256' in entry and target_key and manifest.get('save_key'):
            if not _opens_to(path, target_key, entry['plain_sha256']):
                problems.append(f'save {entry["path"]} does not open with the server key')
        elif 'plain_sha256' not in entry and _sha256(path) != entry['sha256']:
            problems.append(f'file {entry["path"]} differs')
    return problems


def import_(args) -> int:
    bundle = Path(args.bundle).resolve()
    manifest = check_bundle(bundle, args.expect)
    url = os.environ.get('DATABASE_URL')
    if not url:
        raise UsageError('no target database: set DATABASE_URL to a new, empty database')
    library = Path(args.library_dir).resolve() if args.library_dir else default_server_library().resolve()
    new_roots = {LIBRARY_ROOT: _norm_root(str(library)), **_pairs(args.root)}
    old_roots = manifest['roots']
    if set(new_roots) != set(old_roots):
        missing = sorted(set(old_roots) - set(new_roots))
        extra = sorted(set(new_roots) - set(old_roots))
        raise Refused(f'--root must name exactly the folders named at export: missing {missing}, unknown {extra}')
    target_key = None
    if manifest.get('save_key'):
        secret = os.environ.get('SECRET_KEY')
        if not secret:
            raise Refused("encrypted saves need the server's SECRET_KEY in the environment to re-encrypt them")
        target_key = save_key_for(secret)
    check_schema_known(manifest['db']['alembic_revision'])
    if not database_is_empty(url):
        raise Refused('the target database is not empty: import only into a new, empty database')
    conflicts = _file_conflicts(manifest, library, target_key)
    if conflicts:
        raise Refused(f'{len(conflicts)} file(s) already exist in the server library with other content, '
                      f'e.g. {conflicts[0]}; nothing was changed')

    # check_bundle hashed db.dump minutes ago (and every file after it); on a
    # share, someone with write access could have swapped it since, and
    # pg_restore runs the dump's SQL. So pg_restore reads a private copy that
    # was hashed as it was written, never the path on the share.
    scratch = Path(tempfile.mkdtemp(prefix='oneirodex-restore-'))
    try:
        dump = scratch / 'db.dump'
        _copy_checked(bundle / 'db.dump', dump, manifest['db_dump']['sha256'])
        restore(url, dump, args.pg_bin, int(manifest['db_dump'].get('pg_major') or 0))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    created: list[Path] = []
    try:
        for entry in manifest['files']:
            target = _safe_join(library, entry['path'], 'server library')
            existed = target.exists()
            target.parent.mkdir(parents=True, exist_ok=True)
            _copy_checked(_safe_join(bundle / 'files', entry['path'], 'move folder'), target, entry['sha256'])
            if not existed:
                created.append(target)
        changed = remap_paths(url, old_roots, new_roots)
        rekeyed = rekey_saves(library, manifest, target_key) if target_key else 0
        problems = verify(url, manifest, new_roots, library, target_key)
        for problem in problems:
            print('VERIFY FAIL:', problem)
        if problems:
            raise Refused(f'{len(problems)} verification problem(s)')
    except Exception as exc:
        for path in created:
            path.unlink(missing_ok=True)
        raise Refused(f'{exc}. The database was restored: drop the target database to roll back. '
                      'Files this import added were removed; the standalone install is unchanged') from exc
    rows = sum(t['rows'] for t in manifest['db']['tables'].values())
    print(f'imported and verified: {len(manifest["db"]["tables"])} tables, {rows} rows, {len(manifest["files"])} files; '
          f'paths rewritten {changed or "none"}; saves re-encrypted {rekeyed}')
    print('next: point the server at this database and start it. Delete the move folder once you are happy.')
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='python -m oneirodex_standalone', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('export', help='write a move folder from this standalone install (Oneirodex stopped)')
    p.add_argument('--pg-home', required=True, type=Path, help='root of the bundled PostgreSQL')
    p.add_argument('--data-dir', type=Path, default=None, help='standalone data folder (default: the usual one)')
    p.add_argument('--to', required=True, help='new or empty folder to write')
    p.add_argument('--root', action='append', help='NAME=PATH: a folder of games whose paths move too (repeatable)')
    p.set_defaults(fn=export)
    p = sub.add_parser('import', help='restore a move folder into an empty server database ($DATABASE_URL)')
    p.add_argument('bundle', help='the move folder')
    p.add_argument('--expect', required=True, help='the fingerprint export printed')
    p.add_argument('--library-dir', default=None, help="the server's library folder (default: the server's own)")
    p.add_argument('--root', action='append', help='NAME=PATH: where each folder named at export lives now')
    p.add_argument('--pg-bin', default=None, help='folder holding pg_restore (default: PATH)')
    p.set_defaults(fn=import_)
    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except UsageError as exc:
        print(f'usage: {exc}', file=sys.stderr)
        return 2
    except Refused as exc:
        print(f'REFUSED: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
