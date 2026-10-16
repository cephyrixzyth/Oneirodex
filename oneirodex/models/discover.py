"""Discover domain: storefront sections/zones and the on-box recommender's
materialised signal (taste facets, similarity, impression damping)."""
from datetime import datetime, timezone

from oneirodex.models.orm import db
from oneirodex.models._base import JSONEncodedDict

class DiscoverySection(db.Model):
    __tablename__ = 'discovery_sections'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    identifier = db.Column(db.String(50), unique=True, nullable=False)
    is_visible = db.Column(db.Boolean, default=True)
    display_order = db.Column(db.Integer, default=0)
    # 'seed' = built-in shelf (libraries, latest_games, ...); 'custom' = admin-created zone
    section_type = db.Column(db.String(20), default='seed', nullable=False)
    # Custom zone config, e.g. {"mode": "manual", "game_uuids": [...]}
    # or {"mode": "filter", "filter_type": "library|platform|genre", "filter_value": "..."}
    config = db.Column(JSONEncodedDict, nullable=True)
    # W25-STORE-1: a shelf with a window is an "event" — it only renders inside it.
    starts_at = db.Column(db.DateTime, nullable=True)
    ends_at = db.Column(db.DateTime, nullable=True)
    # Storefront treatment: shelf (default) | hero | carousel
    layout = db.Column(db.String(20), default='shelf', nullable=False)
    # Admin-forced position. NULL means "wherever display_order puts it"; a
    # number pins the shelf into the reserved block at the top of every
    # member's feed, lowest first. Capped at three shelves in assembly so a
    # member's own pins can never be pushed below the fold.
    pin_rank = db.Column(db.Integer, nullable=True)

    def is_live(self, now=None):
        """True when the shelf is visible and inside its schedule window."""
        if not self.is_visible:
            return False
        moment = now or datetime.now(timezone.utc)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)

        def _aware(value):
            if value is None:
                return None
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

        starts = _aware(self.starts_at)
        ends = _aware(self.ends_at)
        if starts and moment < starts:
            return False
        if ends and moment > ends:
            return False
        return True

    def __repr__(self):
        return f"<DiscoverySection {self.name}>"

class UserTasteFacet(db.Model):
    """A member's affinity for one facet of a game, rebuilt on a schedule.

    The on-box recommender is content-based: it scores a title by how much its
    facets overlap what the member already reaches for. Collaborative signal —
    "people who played this also played that" — needs a population a self-hosted
    box does not have, so this table, not co-occurrence, is the primary engine.

    Materialised rather than computed per request. The feed only ever SELECTs.
    """

    __tablename__ = 'user_taste_facets'
    __table_args__ = (
        db.UniqueConstraint(
            'user_id', 'facet_type', 'facet_id', name='uq_user_taste_facet'
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    # genre | theme | perspective | developer
    facet_type = db.Column(db.String(16), nullable=False)
    facet_id = db.Column(db.Integer, nullable=False)
    weight = db.Column(db.Float, default=0.0, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

class GameSimilarity(db.Model):
    """Neighbours of a title, and how the neighbourhood was worked out.

    ``method`` is ``content`` (facet overlap — works with one member and a cold
    library) or ``collab`` (co-occurrence across members, written only when the
    install has enough people for it to mean anything). Both can exist for a
    pair; the reader blends them.
    """

    __tablename__ = 'game_similarity'
    __table_args__ = (
        db.UniqueConstraint(
            'game_uuid', 'neighbour_uuid', 'method', name='uq_game_similarity'
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    game_uuid = db.Column(
        db.String(36), db.ForeignKey('games.uuid', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    neighbour_uuid = db.Column(
        db.String(36), db.ForeignKey('games.uuid', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    score = db.Column(db.Float, default=0.0, nullable=False)
    method = db.Column(db.String(16), default='content', nullable=False)
    computed_at = db.Column(
        db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

class UserDiscoverImpression(db.Model):
    """How often Discover has put a title in front of a member.

    Freshness is a rotation property, not a model property: the reason the same
    eight tiles greet somebody every morning is that nothing remembers having
    shown them. A title shown repeatedly and never opened is damped down.
    """

    __tablename__ = 'user_discover_impressions'
    __table_args__ = (
        db.UniqueConstraint('user_id', 'game_uuid', name='uq_user_discover_impression'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    game_uuid = db.Column(
        db.String(36), db.ForeignKey('games.uuid', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    shown_count = db.Column(db.Integer, default=0, nullable=False)
    last_shown_at = db.Column(db.DateTime, nullable=True)
    # Set when the member actually opened the title. A tile that gets clicked
    # has earned its place and stops being damped.
    clicked_at = db.Column(db.DateTime, nullable=True)


__all__ = [
    "DiscoverySection",
    "UserTasteFacet",
    "GameSimilarity",
    "UserDiscoverImpression",
]
