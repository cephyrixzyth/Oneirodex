"""Give store-identified games a 2:3 Steam cover instead of the 231x87 search capsule.

Games created from a Steam store match before 1.3.1 kept the tiny landscape
capsule that store search returns, so 2:3 tiles (library, Latest, News) had no
image to show. For each such game this asks Steam for the 600x900 library
capsule and falls back to the full-size header. Nothing else about the game
changes.

Dry run by default; ``--apply`` writes. Take an appdata backup first.

    python scripts/refresh_steam_covers.py            # report only
    python scripts/refresh_steam_covers.py --apply    # update covers
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys
import time

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import create_engine, select, update  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from oneirodex.models import Game  # noqa: E402
from oneirodex.utils.steam_lookup import steam_cover_for_app  # noqa: E402
from scripts.migrate_store_credentials import resolve_database_url  # noqa: E402

SMALL_CAPSULE_MARKERS = ('capsule_231x87', 'capsule_sm_120', 'capsule_184x69')


def needs_refresh(cover: str | None) -> bool:
    return not cover or any(marker in cover for marker in SMALL_CAPSULE_MARKERS)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--apply', action='store_true', help='write the new covers')
    parser.add_argument('--delay', type=float, default=0.15, help='seconds between Steam checks')
    args = parser.parse_args(argv)

    engine = create_engine(resolve_database_url())
    outcome: Counter[str] = Counter()
    with Session(engine) as session:
        rows = session.execute(
            select(Game.uuid, Game.steam_app_id, Game.cover).where(Game.steam_app_id.isnot(None))
        ).all()
        for uuid, app_id, cover in rows:
            if not needs_refresh(cover):
                outcome['already_full_size'] += 1
                continue
            new_cover = steam_cover_for_app(app_id, cover)
            kind = 'portrait' if new_cover and new_cover.endswith('library_600x900.jpg') else 'header'
            outcome[kind] += 1
            if args.apply and new_cover and new_cover != cover:
                session.execute(update(Game).where(Game.uuid == uuid).values(cover=new_cover))
            time.sleep(max(0.0, args.delay))
        if args.apply:
            session.commit()

    mode = 'applied' if args.apply else 'dry run (nothing written)'
    print(f'Steam cover refresh - {mode}')
    for key in ('portrait', 'header', 'already_full_size'):
        print(f'  {key}: {outcome[key]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
