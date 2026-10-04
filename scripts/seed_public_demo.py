"""Create a disposable, non-admin account and clearly labeled sample library.

This is only called by the container when ONEIRODEX_PUBLIC_DEMO=true. It never
uses the screenshot-capture admin account, external service keys, ROM files, or
production data. The host's ephemeral database makes the demo resettable.
"""
from __future__ import annotations

import logging
import secrets
from uuid import uuid4

from sqlalchemy import select

from oneirodex import create_app, db
from oneirodex.models import Game, GlobalSettings, Library, LibraryPlatform, User, UserPreference
from oneirodex.utils.setup import mark_setup_complete

logger = logging.getLogger(__name__)


SAMPLE_LIBRARIES = (
    ('Free NES samples', LibraryPlatform.NES, 'nestest'),
    ('Free Game Boy samples', LibraryPlatform.GB, 'dmg-acid2'),
    ('Free GBA samples', LibraryPlatform.GBA, 'CASCADE7'),
    ('Free Genesis samples', LibraryPlatform.SEGA_MD, 'genmddj'),
    ('Free Atari 2600 samples', LibraryPlatform.ATARI_2600, 'paddle-tester'),
)


def seed() -> None:
    app = create_app()
    with app.app_context():
        user = db.session.execute(
            select(User).filter_by(name='demo-visitor')
        ).scalar_one_or_none()
        if user is None:
            user = User(
                name='demo-visitor',
                email='demo-visitor@example.test',
                role='user',
                state=True,
                is_email_verified=True,
                user_id=str(uuid4()),
            )
            user.set_password(secrets.token_urlsafe(48))
            user.preferences = UserPreference(tile_size='78')
            db.session.add(user)

        settings = db.session.execute(select(GlobalSettings)).scalars().first()
        if settings is None:
            settings = GlobalSettings()
            db.session.add(settings)
        settings.smtp_enabled = False
        settings.oidc_enabled = False
        settings.enable_store_ownership_sync = False
        settings.enable_hltb_integration = False
        settings.enable_delete_game_on_disk = False
        settings.enable_arr_module = False
        settings.enable_emulator_save_sync = False

        libraries = {
            library.name: library
            for library in db.session.execute(select(Library)).scalars().all()
        }
        for label, platform, title in SAMPLE_LIBRARIES:
            library = libraries.get(label)
            if library is None:
                library = Library(
                    name=label,
                    platform=platform,
                    scan_depth=1,
                )
                db.session.add(library)
                db.session.flush()
                libraries[label] = library

            exists = db.session.execute(
                select(Game).filter_by(name=title, library_uuid=library.uuid)
            ).scalars().first()
            if exists is None:
                db.session.add(Game(
                    uuid=str(uuid4()),
                    name=title,
                    summary='Sample homebrew test title in the disposable public demo.',
                    library_uuid=library.uuid,
                    full_disk_path=None,
                    size=0,
                    times_downloaded=0,
                ))

        db.session.commit()
        mark_setup_complete()
        logger.info('Public demo seed ready: member-only account and five labeled sample titles.')


if __name__ == '__main__':
    seed()
