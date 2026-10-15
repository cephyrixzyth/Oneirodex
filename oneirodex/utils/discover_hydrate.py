"""Batched hydration for Discover shelves.

Selection and serialization used to be one loop. For every game on the page that
loop ran a cover-image ``SELECT``, lazy-loaded three relationships, stat'd the
game folder twice, and re-asked whether the member had a companion client
connected — the last of which is the same answer for every tile on the page.

That was affordable at 8 tiles across a handful of shelves. At the depth the
Discover rework targets — 40 tiles across up to 20 rows — the same loop is on the
order of 800 cover queries, 800 companion-presence queries and up to 1,600
filesystem stats per page load, on a box whose library commonly lives on a NAS
mount.

So the halves are split. Callers select :class:`~oneirodex.models.Game` rows
however they like, then hand the whole feed here once: each per-game query
collapses into one query for the entire feed, and the filesystem checks are
memoised per folder, since one folder can back several rows.

This module deliberately knows nothing about card *shape* — it is the batch, and
``routes_discover.serialize_discover_game`` remains the single place that decides
what a Discover tile looks like.
"""

from __future__ import annotations

from typing import Any, Iterable, Iterator, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import Game, GameUpdate, GlobalSettings, Image
from oneirodex.utils.client_lifecycle import load_lifecycle_map
from oneirodex.utils.client_presence import user_client_connected
from oneirodex.utils.local_metadata import has_local_images, has_local_metadata
from oneirodex.utils.store_ownership import get_matched_owned_game_uuids

DEFAULT_METADATA_FILENAME = 'oneirodex.json'

# Postgres caps bound parameters per statement. Feeds never approach that, but
# chunking keeps the module safe for a caller that primes an entire library.
_CHUNK_SIZE = 500

#: Relationships the card serializer touches for every tile — ``genres`` and
#: ``player_perspectives`` feed the card flags, ``library`` feeds the play-URL
#: and the platform badge. Priming these in one round trip is the point.
#:
#: Held as names, not attributes: ``Game.library`` is a backref declared on
#: ``Library.games``, so it does not exist on the class until the mappers
#: configure. Resolving at import time raises; resolving per call cannot.
_CARD_RELATIONSHIP_NAMES = ('genres', 'player_perspectives', 'library')


def _chunked(values: Sequence[str]) -> Iterator[Sequence[str]]:
    for start in range(0, len(values), _CHUNK_SIZE):
        yield values[start:start + _CHUNK_SIZE]


class DiscoverHydration:
    """Everything the Discover card serializer needs, fetched in bulk.

    Build one per feed, :meth:`prime` it with the games that feed will show, then
    read the per-game lookups. Priming is incremental and idempotent — a uuid
    already seen is not re-fetched — so a lazily windowed row can prime its next
    page against the same instance rather than starting a second batch.
    """

    def __init__(self, user):
        self.user = user
        self.user_id = getattr(user, 'id', None)
        self.favorite_game_uuids = {game.uuid for game in user.favorites}
        self.owned_game_uuids = get_matched_owned_game_uuids(self.user_id)
        self.lifecycle_map = load_lifecycle_map(self.user_id)
        self.settings = db.session.execute(
            select(GlobalSettings).order_by(GlobalSettings.id).limit(1)
        ).scalars().first()
        # Constant for the whole page: it depends on the member, not the game.
        # Asking per tile was one full ClientDevice query per tile.
        self.client_connected = user_client_connected(self.user_id)

        self._covers: dict[str, Image] = {}
        self._update_counts: dict[str, int] = {}
        self._local_override: dict[str, bool] = {}
        self._primed: set[str] = set()

    # ------------------------------------------------------------------
    # batch loading
    # ------------------------------------------------------------------

    def prime(self, games: Iterable[Game]) -> None:
        """Fetch in bulk everything ``games`` will need to serialize."""
        pending: list[str] = []
        for game in games:
            uuid = getattr(game, 'uuid', None)
            if uuid and uuid not in self._primed:
                pending.append(uuid)
        if not pending:
            return
        # A title legitimately appears in several rows; ask for it once.
        pending = list(dict.fromkeys(pending))
        self._primed.update(pending)

        self._prime_relationships(pending)
        self._prime_covers(pending)
        self._prime_update_counts(pending)

    def _prime_relationships(self, uuids: Sequence[str]) -> None:
        """Populate card relationships on instances the caller already holds.

        Re-selecting by uuid returns the *same* objects out of the session
        identity map, so the eager-load options land on the instances the caller
        is about to serialize. That keeps the loader options in one place here,
        rather than requiring every shelf query in every provider to remember to
        add them.
        """
        options = [
            selectinload(getattr(Game, name)) for name in _CARD_RELATIONSHIP_NAMES
        ]
        for chunk in _chunked(uuids):
            db.session.execute(
                select(Game).where(Game.uuid.in_(chunk)).options(*options)
            ).scalars().all()

    def _prime_covers(self, uuids: Sequence[str]) -> None:
        for chunk in _chunked(uuids):
            images = db.session.execute(
                select(Image)
                .where(Image.game_uuid.in_(chunk), Image.image_type == 'cover')
                # The per-game query took an unordered `.first()`, so a game with
                # several covers got an arbitrary one that could change between
                # loads. Lowest id is just as valid and at least stays put.
                .order_by(Image.id)
            ).scalars().all()
            for image in images:
                self._covers.setdefault(image.game_uuid, image)

    def _prime_update_counts(self, uuids: Sequence[str]) -> None:
        for chunk in _chunked(uuids):
            rows = db.session.execute(
                select(GameUpdate.game_uuid, func.count(GameUpdate.id))
                .where(GameUpdate.game_uuid.in_(chunk))
                .group_by(GameUpdate.game_uuid)
            ).all()
            for game_uuid, count in rows:
                self._update_counts[game_uuid] = int(count or 0)

    # ------------------------------------------------------------------
    # per-game lookups
    # ------------------------------------------------------------------

    def cover_for(self, game) -> Image | None:
        return self._covers.get(getattr(game, 'uuid', None))

    def update_count_for(self, game) -> int:
        return self._update_counts.get(getattr(game, 'uuid', None), 0)

    def is_favorite(self, game) -> bool:
        return getattr(game, 'uuid', None) in self.favorite_game_uuids

    def client_state_for(self, game) -> Any:
        return self.lifecycle_map.get(getattr(game, 'uuid', None))

    def local_override_for(self, game) -> bool:
        """Whether on-disk metadata or images override the scraped record.

        Memoised by folder rather than by game: the answer is a property of the
        path, and the same path can back more than one row on the page. The two
        checks underneath are filesystem stats, which is what makes them worth
        caching at all.
        """
        settings = self.settings
        if settings is None:
            return False
        path = getattr(game, 'full_disk_path', None)
        if not path:
            return False

        cached = self._local_override.get(path)
        if cached is not None:
            return cached

        result = bool(
            (
                settings.use_local_metadata
                and has_local_metadata(
                    path,
                    settings.local_metadata_filename or DEFAULT_METADATA_FILENAME,
                )
            )
            or (settings.use_local_images and has_local_images(path))
        )
        self._local_override[path] = result
        return result

    # ------------------------------------------------------------------
    # serializer plumbing
    # ------------------------------------------------------------------

    def serializer_kwargs(self, game) -> dict[str, Any]:
        """Keyword arguments ``serialize_discover_game`` needs for ``game``."""
        return {
            'is_favorite': self.is_favorite(game),
            'has_local_override': self.local_override_for(game),
            'owned_game_uuids': self.owned_game_uuids,
            'user_id': self.user_id,
            'client_state': self.client_state_for(game),
            'client_connected': self.client_connected,
            'updates_count': self.update_count_for(game),
        }
