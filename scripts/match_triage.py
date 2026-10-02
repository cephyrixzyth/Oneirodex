#!/usr/bin/env python3
"""Offline triage of folder names the matcher could not place.

Feed it the folder names from Admin -> Scan -> Unmatched (one per line, or a CSV
with a ``folder_path`` / ``folder`` / ``name`` column) and it replays the same
name cleaning the scan uses, then buckets each name by the *residue* still left
in the cleaned label. A name that still carries a scene tag, a version, an
unbalanced bracket or a DLC note is a cleaning gap; a clean name that still did
not match is a catalogue or scoring problem. Counting which bucket is biggest
says where matcher work pays off, without touching the live library.

Read-only and offline: no database, no network. Release-group cleaners that
live in the database can be passed with ``--groups ElAmigos,FitGirl``.

    python scripts/match_triage.py unmatched.csv
    python scripts/match_triage.py unmatched.txt --groups ElAmigos,GOG --csv out.csv
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from collections import Counter
from pathlib import Path

os.environ.setdefault('SECRET_KEY', 'triage-only-not-a-secret-' + 'x' * 40)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

#: Residue buckets, checked on the *cleaned* label. Order is display order.
BUCKETS: tuple[tuple[str, re.Pattern], ...] = (
    ('unbalanced_bracket', re.compile(r'^[^\[]*\[[^\]]*$|^[^(]*\([^)]*$|^[^\[]*\][^\[]*$|^[^(]*\)[^(]*$')),
    ('bracket_or_paren_left', re.compile(r'[\[\](){}]')),
    ('version_left', re.compile(r'\bv\s?\d+(?:[._]\d+)*\b|\b\d+\.\d+\.\d+\b', re.I)),
    ('update_or_build', re.compile(r'\b(?:update|patch|hotfix|build)\b\s*\d*', re.I)),
    ('dlc_or_bonus', re.compile(r'\b(?:dlcs?|bonus|soundtrack|ost|artbook|season pass)\b|\+\s*\d+', re.I)),
    ('language_or_region_tag', re.compile(r'\bmulti\s?-?\d*\b|\bmultilingual\b|\b(?:eng|rus|ger|fre|usa|eur|pal|ntsc)\b', re.I)),
    ('group_tail', re.compile(r'-\s?[A-Za-z0-9]{2,12}$')),
    ('platform_word', re.compile(r'\b(?:gog|steam|epic|win(?:dows)?|x64|x86|linux|mac)\b', re.I)),
    ('year_in_name', re.compile(r'[(\[]?\b(?:19|20)\d{2}\b[)\]]?')),
    ('non_ascii', re.compile(r'[^\x00-\x7f]')),
    ('too_short', re.compile(r'^.{0,2}$')),
)


def _load_names(path: Path) -> list[str]:
    text = path.read_text(encoding='utf-8-sig')
    if path.suffix.lower() == '.csv':
        rows = list(csv.DictReader(text.splitlines()))
        if not rows:
            return []
        keys = {k.lower(): k for k in rows[0]}
        key = next((keys[k] for k in ('folder_path', 'folder', 'path', 'name', 'title') if k in keys), None)
        if key is None:
            raise SystemExit('CSV needs a folder_path, folder, path, name or title column')
        return [os.path.basename(str(r[key]).rstrip('/\\')) for r in rows if r.get(key)]
    return [os.path.basename(line.strip().rstrip('/\\')) for line in text.splitlines() if line.strip()]


def clean(name: str, groups: list[str]) -> str:
    from oneirodex.utils.game_name_parse import parse_game_label
    from oneirodex.utils.gamenames import clean_game_name

    patterns = ['-' + g for g in groups] + ['.' + g for g in groups]
    sensitive = [(p, False) for p in patterns]
    parsed = parse_game_label(name).get('cleaned_name') or name
    return clean_game_name(parsed, patterns, sensitive).strip()


def triage(name: str, groups: list[str]) -> dict:
    cleaned = clean(name, groups)
    hits = [label for label, rx in BUCKETS if rx.search(cleaned)]
    return {'folder': name, 'cleaned': cleaned, 'residue': hits or ['clean']}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('input', type=Path, help='text file (one folder per line) or CSV')
    parser.add_argument('--groups', default='', help='comma-separated release-group names to strip')
    parser.add_argument('--csv', type=Path, help='write every row with its residue buckets')
    parser.add_argument('--examples', type=int, default=3, help='examples shown per bucket')
    args = parser.parse_args(argv)

    groups = [g.strip() for g in args.groups.split(',') if g.strip()]
    names = _load_names(args.input)
    rows = [triage(n, groups) for n in names]

    counts: Counter[str] = Counter()
    examples: dict[str, list[dict]] = {}
    for row in rows:
        for label in row['residue']:
            counts[label] += 1
            examples.setdefault(label, []).append(row)

    print(f'{len(rows)} folders triaged')
    for label, count in counts.most_common():
        print(f'\n{label}: {count} ({count / max(len(rows), 1):.0%})')
        for row in examples[label][: args.examples]:
            print(f'  {row["folder"]!r} -> {row["cleaned"]!r}')
    if args.csv:
        with args.csv.open('w', newline='', encoding='utf-8') as handle:
            writer = csv.writer(handle)
            writer.writerow(['folder', 'cleaned', 'residue'])
            for row in rows:
                writer.writerow([row['folder'], row['cleaned'], ';'.join(row['residue'])])
        print(f'\nwrote {args.csv}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
