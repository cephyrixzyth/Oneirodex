"""DESK-03 spike: move a standalone Oneirodex to a household server, verifiably.

Spike code, not product code: nothing in ``oneirodex/`` imports it. It proves
the move primitive the P05 ADR recommends for a PostgreSQL-backed standalone:

* the database travels as ``pg_dump -Fc`` / ``pg_restore --single-transaction``
  (run by the orchestrating script, not here);
* this tool adds what those tools cannot know: an identity manifest (per-table
  content digests with machine-specific paths made relative to named roots),
  file checksums for saves/artwork, a bundle integrity check, a single-
  transaction path remap on the target, and a verification that the target
  matches the source row for row.

Commands (the database URL comes from ``$DATABASE_URL`` unless ``--db`` is
given; it is never printed). Exit status 1 is a verified refusal or mismatch;
anything else (2 = usage error, a traceback) is a broken run, not a refusal::

    snapshot     --db URL --root NAME=PREFIX ... [--files NAME=DIR ...] --out FILE
    pack         --snapshot FILE --bundle DIR [--files NAME=DIR ...]
    check-bundle --bundle DIR
    unpack-files --bundle DIR --files NAME=DIR ...
    remap        --db URL --bundle DIR --root NAME=NEWPREFIX ...
    verify       --db URL --bundle DIR --root NAME=NEWPREFIX ... [--files NAME=DIR ...]

Exit status is non-zero on any mismatch, so a script can stop before a
half-verified move is called done.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

#: Columns holding machine-specific filesystem paths (from the P05 audit).
#: Any other text column whose name contains ``path`` or ``folder`` is added
#: at runtime and reported, so a new path column cannot be missed silently.
KNOWN_PATH_COLUMNS = {
    ('games', 'full_disk_path'),
    ('libraries', 'last_scan_folder'),
    ('emulator_saves', 'storage_path'),
}
SKIP_TABLES = {'alembic_version'}
CHUNK = 1 << 20


def _pairs(values, what):
    out = {}
    for item in values or []:
        name, sep, value = item.partition('=')
        if not sep or not name or not value:
            raise SystemExit(f'{what} must be NAME=VALUE, got {item!r}')
        out[name] = value
    return out


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        while block := handle.read(CHUNK):
            digest.update(block)
    return digest.hexdigest()


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _schema(conn):
    rows = conn.execute(text(
        "SELECT table_name, column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = 'public' ORDER BY table_name, ordinal_position"
    )).all()
    tables: dict[str, list[tuple[str, str]]] = {}
    for table, column, data_type in rows:
        if table not in SKIP_TABLES:
            tables.setdefault(table, []).append((column, data_type))
    return tables


def _path_columns(tables):
    found = set(KNOWN_PATH_COLUMNS)
    for table, columns in tables.items():
        for column, data_type in columns:
            if data_type in ('text', 'character varying') and ('path' in column or 'folder' in column):
                found.add((table, column))
    return {(t, c) for (t, c) in found if t in tables and any(c == col for col, _ in tables[t])}


def _relative(column_sql: str, roots: dict[str, str]) -> str:
    """SQL that rewrites a path under a named root to ``NAME:rest``."""
    expr = column_sql
    # Longest prefix first, so a nested root wins over its parent.
    for name, prefix in sorted(roots.items(), key=lambda kv: -len(kv[1])):
        expr = (f"CASE WHEN left({column_sql}, {len(prefix)}) = {_sql_str(prefix)} "
                f"THEN {_sql_str(name + ':')} || substr({column_sql}, {len(prefix) + 1}) ELSE {expr} END")
    return expr


def snapshot_db(url: str, roots: dict[str, str]) -> dict:
    engine = create_engine(url)
    with engine.connect() as conn:
        revision = conn.execute(text('SELECT version_num FROM alembic_version')).scalar()
        tables = _schema(conn)
        path_cols = _path_columns(tables)
        digests, unrooted = {}, {}
        for table, columns in sorted(tables.items()):
            parts = []
            for column, _ in columns:
                col = _quote(column)
                parts.append(_relative(col, roots) if (table, column) in path_cols else col)
            row = f"ROW({', '.join(parts)})::text"
            count, digest = conn.execute(text(
                f"SELECT count(*), md5(coalesce(string_agg(x, E'\\n' ORDER BY x), '')) "
                f"FROM (SELECT {row} AS x FROM {_quote(table)}) s"
            )).one()
            digests[table] = {'rows': count, 'md5': digest}
        for table, column in sorted(path_cols):
            col = _quote(column)
            conditions = ' AND '.join(
                f"left({col}, {len(p)}) <> {_sql_str(p)}" for p in roots.values()
            ) or 'true'
            n = conn.execute(text(
                f"SELECT count(*) FROM {_quote(table)} WHERE {col} IS NOT NULL AND {col} <> '' AND {conditions}"
            )).scalar()
            unrooted[f'{table}.{column}'] = n
        identity = {
            'game_uuids': conn.execute(text(
                "SELECT count(*), md5(coalesce(string_agg(uuid, ',' ORDER BY uuid), '')) FROM games")).one()._asdict(),
            'entitlements': conn.execute(text(
                "SELECT count(*), md5(coalesce(string_agg(concat_ws('|', user_id, store, external_app_id, "
                "matched_game_uuid, match_revision, match_reviewed), ',' ORDER BY user_id, store, external_app_id), '')) "
                "FROM user_owned_titles")).one()._asdict(),
            'match_decisions': conn.execute(text(
                "SELECT count(*), md5(coalesce(string_agg(concat_ws('|', title_id, revision, before_uuid, after_uuid, action), "
                "',' ORDER BY title_id, revision), '')) FROM ownership_match_decisions")).one()._asdict(),
            'saves': conn.execute(text(
                "SELECT count(*), md5(coalesce(string_agg(concat_ws('|', user_id, game_uuid, slot_name, filename, size_bytes), "
                "',' ORDER BY user_id, game_uuid, slot_name), '')) FROM emulator_saves")).one()._asdict(),
        }
        sequences = {}
        for table, columns in tables.items():
            if not any(c == 'id' for c, _ in columns):
                continue
            seq = conn.execute(text("SELECT pg_get_serial_sequence(:t, 'id')"), {'t': table}).scalar()
            if seq:
                max_id = conn.execute(text(f"SELECT coalesce(max(id), 0) FROM {_quote(table)}")).scalar()
                last = conn.execute(text(f"SELECT last_value FROM {seq}")).scalar()
                sequences[table] = {'max_id': max_id, 'last_value': last, 'ok': last >= max_id}
    engine.dispose()
    return {
        'alembic_revision': revision,
        'tables': digests,
        'path_columns': sorted(f'{t}.{c}' for t, c in path_cols),
        'unrooted_paths': unrooted,
        'identity': identity,
        'sequences_ok': all(s['ok'] for s in sequences.values()),
        'sequence_problems': {t: s for t, s in sequences.items() if not s['ok']},
    }


def snapshot_files(files: dict[str, str]) -> dict:
    out = {}
    for name, root in sorted(files.items()):
        base = Path(root)
        entries = []
        for path in sorted(p for p in base.rglob('*') if p.is_file()):
            entries.append({'path': path.relative_to(base).as_posix(), 'size': path.stat().st_size, 'sha256': _sha256(path)})
        out[name] = entries
    return out


def _load_manifest(bundle: Path) -> dict:
    return json.loads((bundle / 'manifest.json').read_text(encoding='utf-8'))


def cmd_snapshot(args):
    roots = _pairs(args.root, '--root')
    snap = {'roots': roots, 'db': snapshot_db(args.db, roots), 'files': snapshot_files(_pairs(args.files, '--files'))}
    Path(args.out).write_text(json.dumps(snap, indent=2, sort_keys=True), encoding='utf-8')
    print(f"snapshot: {len(snap['db']['tables'])} tables, revision {snap['db']['alembic_revision']}, "
          f"{sum(len(v) for v in snap['files'].values())} files")
    return 0


def cmd_pack(args):
    bundle = Path(args.bundle)
    dump = bundle / 'db.dump'
    if not dump.is_file():
        raise SystemExit('db.dump missing: run pg_dump -Fc into the bundle first')
    snap = json.loads(Path(args.snapshot).read_text(encoding='utf-8'))
    for name, root in _pairs(args.files, '--files').items():
        for entry in snap['files'].get(name, []):
            target = bundle / 'files' / name / entry['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path(root) / entry['path'], target)
    manifest = {'format': 'oneirodex-household-move/0-spike', 'snapshot': snap,
                'db_dump': {'size': dump.stat().st_size, 'sha256': _sha256(dump)}}
    text_ = json.dumps(manifest, indent=2, sort_keys=True)
    (bundle / 'manifest.json').write_text(text_, encoding='utf-8')
    (bundle / 'manifest.sha256').write_text(hashlib.sha256(text_.encode('utf-8')).hexdigest() + '\n', encoding='utf-8')
    print(f"packed: db.dump {manifest['db_dump']['size']} bytes, "
          f"{sum(len(v) for v in snap['files'].values())} files")
    return 0


def cmd_check_bundle(args):
    bundle = Path(args.bundle)
    problems = []
    raw = (bundle / 'manifest.json').read_text(encoding='utf-8')
    if hashlib.sha256(raw.encode('utf-8')).hexdigest() != (bundle / 'manifest.sha256').read_text().strip():
        problems.append('manifest.json does not match manifest.sha256')
    manifest = json.loads(raw)
    if _sha256(bundle / 'db.dump') != manifest['db_dump']['sha256']:
        problems.append('db.dump checksum mismatch')
    for name, entries in manifest['snapshot']['files'].items():
        for entry in entries:
            path = bundle / 'files' / name / entry['path']
            if not path.is_file() or _sha256(path) != entry['sha256']:
                problems.append(f'file {name}:{entry["path"]} missing or changed')
    for p in problems:
        print('BUNDLE FAIL:', p)
    print('bundle: OK' if not problems else f'bundle: {len(problems)} problem(s)')
    return 1 if problems else 0


def cmd_unpack_files(args):
    bundle = Path(args.bundle)
    manifest = _load_manifest(bundle)
    problems = 0
    for name, root in _pairs(args.files, '--files').items():
        for entry in manifest['snapshot']['files'].get(name, []):
            source = bundle / 'files' / name / entry['path']
            target = Path(root) / entry['path']
            if target.exists() and _sha256(target) != entry['sha256']:
                print(f'REFUSED: {name}:{entry["path"]} exists on the target with different content')
                problems += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            if _sha256(target) != entry['sha256']:
                print(f'COPY FAIL: {name}:{entry["path"]}')
                problems += 1
    print('files: OK' if not problems else f'files: {problems} problem(s)')
    return 1 if problems else 0


def cmd_remap(args):
    bundle = Path(args.bundle)
    manifest = _load_manifest(bundle)
    old_roots = manifest['snapshot']['roots']
    new_roots = _pairs(args.root, '--root')
    if set(new_roots) != set(old_roots):
        print(f'REFUSED: --root names must match the bundle roots {sorted(old_roots)}; nothing changed')
        return 1
    engine = create_engine(args.db)
    changed = {}
    ordered = sorted(old_roots.items(), key=lambda kv: -len(kv[1]))  # nested root wins
    with engine.begin() as conn:  # one transaction: all rewritten, or none
        tables = _schema(conn)
        for table, column in sorted(_path_columns(tables)):
            col = _quote(column)
            # One UPDATE per column, each row rewritten once by its longest
            # matching root, so a new prefix can never be matched again.
            cases = ' '.join(
                f"WHEN left({col}, {len(old)}) = {_sql_str(old)} "
                f"THEN {_sql_str(new_roots[name])} || substr({col}, {len(old) + 1})"
                for name, old in ordered
            )
            matches = ' OR '.join(f"left({col}, {len(old)}) = {_sql_str(old)}" for _, old in ordered)
            result = conn.execute(text(
                f"UPDATE {_quote(table)} SET {col} = CASE {cases} ELSE {col} END WHERE {matches}"
            ))
            if result.rowcount:
                changed[f'{table}.{column}'] = result.rowcount
    engine.dispose()
    print('remapped:', json.dumps(changed, sort_keys=True))
    return 0


def cmd_verify(args):
    bundle = Path(args.bundle)
    manifest = _load_manifest(bundle)
    expected = manifest['snapshot']
    roots = _pairs(args.root, '--root')
    actual_db = snapshot_db(args.db, roots)
    problems = []
    if actual_db['alembic_revision'] != expected['db']['alembic_revision']:
        problems.append(f"alembic {actual_db['alembic_revision']} != {expected['db']['alembic_revision']}")
    for table, want in expected['db']['tables'].items():
        got = actual_db['tables'].get(table)
        if got != want:
            problems.append(f'table {table}: expected {want}, got {got}')
    for table in set(actual_db['tables']) - set(expected['db']['tables']):
        problems.append(f'unexpected table {table}')
    if actual_db['identity'] != expected['db']['identity']:
        problems.append('identity digests differ (game UUIDs / entitlements / decisions / saves)')
    if actual_db['unrooted_paths'] != expected['db']['unrooted_paths']:
        problems.append(f"paths outside the named roots differ: {actual_db['unrooted_paths']}")
    if not actual_db['sequences_ok']:
        problems.append(f"sequences behind their tables: {actual_db['sequence_problems']}")
    files = _pairs(args.files, '--files')
    if files:
        actual_files = snapshot_files(files)
        for name in files:
            if actual_files.get(name) != expected['files'].get(name):
                problems.append(f'files under {name} differ from the bundle')
    for p in problems:
        print('VERIFY FAIL:', p)
    tables = len(expected['db']['tables'])
    rows = sum(t['rows'] for t in expected['db']['tables'].values())
    print(f'verify: OK ({tables} tables, {rows} rows, identity + files + sequences match)' if not problems
          else f'verify: {len(problems)} problem(s)')
    return 1 if problems else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('snapshot'); p.add_argument('--db', default=os.environ.get('DATABASE_URL')); p.add_argument('--root', action='append')
    p.add_argument('--files', action='append'); p.add_argument('--out', required=True); p.set_defaults(fn=cmd_snapshot)
    p = sub.add_parser('pack'); p.add_argument('--snapshot', required=True); p.add_argument('--bundle', required=True)
    p.add_argument('--files', action='append'); p.set_defaults(fn=cmd_pack)
    p = sub.add_parser('check-bundle'); p.add_argument('--bundle', required=True); p.set_defaults(fn=cmd_check_bundle)
    p = sub.add_parser('unpack-files'); p.add_argument('--bundle', required=True); p.add_argument('--files', action='append', required=True)
    p.set_defaults(fn=cmd_unpack_files)
    p = sub.add_parser('remap'); p.add_argument('--db', default=os.environ.get('DATABASE_URL')); p.add_argument('--bundle', required=True)
    p.add_argument('--root', action='append', required=True); p.set_defaults(fn=cmd_remap)
    p = sub.add_parser('verify'); p.add_argument('--db', default=os.environ.get('DATABASE_URL')); p.add_argument('--bundle', required=True)
    p.add_argument('--root', action='append', required=True); p.add_argument('--files', action='append')
    p.set_defaults(fn=cmd_verify)
    args = parser.parse_args(argv)
    if hasattr(args, 'db') and not args.db:
        parser.error('no database: set DATABASE_URL or pass --db')
    return args.fn(args)


if __name__ == '__main__':
    sys.exit(main())
