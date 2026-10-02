"""DESK-03 spike: seed a throwaway standalone database with representative data.

Synthetic rows only (no real accounts, no tokens): two users, one library, games
with two artwork kinds each, emulator saves with real files on disk, store
entitlements with match decisions, and a store account without a credential.
Run after ``alembic upgrade head`` against a database whose name contains
``test`` or ``standalone`` — anything else is refused, unless
``SEED_THROWAWAY_CLUSTER=1`` says it is proof E's throwaway standalone cluster
(whose database is always called ``oneirodex``). ``GAMES_ROOT`` overrides the
game folder, e.g. a Windows path to rehearse a cross-OS move.

    DATABASE_URL=postgresql://... SAVES_ROOT=/standalone/saves python seed_standalone.py
"""
from __future__ import annotations

import os
import random
import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from oneirodex.models import (  # noqa: E402
    EmulatorSave, Game, Image, Library, OwnershipMatchDecision, StoreAccount, User, UserOwnedTitle,
)
from oneirodex.platform import LibraryPlatform  # noqa: E402

GAMES_ROOT = os.environ.get('GAMES_ROOT') or '/mnt/standalone/games/PC'
GAMES = 30


def main() -> int:
    url = make_url(os.environ['DATABASE_URL'])
    throwaway = os.environ.get('SEED_THROWAWAY_CLUSTER') == '1'
    if not throwaway and not any(word in (url.database or '') for word in ('test', 'standalone')):
        raise SystemExit('refusing: database name must contain "test" or "standalone"')
    saves_root = Path(os.environ['SAVES_ROOT'])
    rng = random.Random(3)  # deterministic content, so reruns compare
    engine = create_engine(url)
    with Session(engine) as session:
        admin = User(name='StandaloneAdmin', email='admin@standalone.test', role='admin',
                     user_id=str(UUID(int=rng.getrandbits(128), version=4)))
        member = User(name='StandaloneMember', email='member@standalone.test', role='user',
                      user_id=str(UUID(int=rng.getrandbits(128), version=4)))
        for user in (admin, member):
            user.set_password('spike-only-not-a-real-password')
            user.is_email_verified = True
        session.add_all([admin, member])
        library = Library(uuid=str(UUID(int=rng.getrandbits(128), version=4)), name='PC Games',
                          platform=LibraryPlatform.PCWIN, last_scan_folder=GAMES_ROOT)
        session.add(library)
        session.flush()
        games = []
        for n in range(GAMES):
            uuid = str(UUID(int=rng.getrandbits(128), version=4))
            sep = '\\' if '\\' in GAMES_ROOT else '/'
            game = Game(uuid=uuid, name=f'Spike Game {n:02d}', slug=f'spike-game-{n:02d}',
                        library_uuid=library.uuid, full_disk_path=f'{GAMES_ROOT}{sep}Spike Game {n:02d}')
            games.append(game)
            session.add(game)
        session.flush()
        for game in games:
            # Two artwork kinds per game: the partial unique indexes must allow it.
            session.add(Image(game_uuid=game.uuid, image_type='cover', url=f'/static/library/images/{game.uuid}_cover.jpg'))
            session.add(Image(game_uuid=game.uuid, image_type='screenshot', url=f'/static/library/images/{game.uuid}_shot1.jpg'))
        for game in games[:10]:
            folder = saves_root / str(member.id) / game.uuid
            folder.mkdir(parents=True, exist_ok=True)
            data = rng.randbytes(4096)
            (folder / 'slot1.sav').write_bytes(data)
            session.add(EmulatorSave(user_id=member.id, game_uuid=game.uuid, slot_name='slot1', filename='slot1.sav',
                                     size_bytes=len(data), storage_path=str(folder / 'slot1.sav')))
        session.add(StoreAccount(user_id=member.id, store='steam', external_account_id='76561190000000000'))
        for n, game in enumerate(games[:20]):
            title = UserOwnedTitle(user_id=member.id, store='steam', external_app_id=str(1000 + n),
                                   name=game.name, matched_game_uuid=game.uuid if n % 2 == 0 else None,
                                   match_revision=1 if n % 4 == 0 else 0, match_reviewed=n % 4 == 0)
            session.add(title)
            session.flush()
            if n % 4 == 0:
                session.add(OwnershipMatchDecision(title_id=title.id, revision=1, actor_id=member.id,
                                                   before_uuid=None, after_uuid=game.uuid,
                                                   before_reviewed=False, action='match'))
        session.commit()
    engine.dispose()
    print(f'seeded: 2 users, 1 library, {GAMES} games, {GAMES * 2} images, 10 saves, 20 entitlements, 5 decisions')
    return 0


if __name__ == '__main__':
    sys.exit(main())
