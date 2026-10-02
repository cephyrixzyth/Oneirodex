"""Atomic, owner-scoped decisions with optimistic concurrency and append-only undo."""
from sqlalchemy import func, select, update

from oneirodex import db
from oneirodex.models import Game, Library, OwnershipMatchDecision, UserOwnedTitle
from oneirodex.utils.library_acl import apply_game_access_filters


class ReviewError(ValueError):
    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


def decide_match(user, title_id, expected_revision, game_uuid=None, *, undo=False):
    if type(expected_revision) is not int or expected_revision < 0:
        raise ReviewError('expected_revision must be a nonnegative integer', 'bad_request')
    if game_uuid is not None and (not isinstance(game_uuid, str) or len(game_uuid) != 36):
        raise ReviewError('game_uuid must be a UUID or null', 'bad_request')
    row = db.session.execute(select(UserOwnedTitle).where(
        UserOwnedTitle.id == title_id, UserOwnedTitle.user_id == user.id,
    ).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
    if row is None:
        raise ReviewError('Ownership record not found', 'not_found')
    if row.match_revision != expected_revision:
        raise ReviewError('Ownership decision changed; refresh before retrying', 'conflict')
    reviewed = True
    if undo:
        prior = db.session.execute(select(OwnershipMatchDecision).where(
            OwnershipMatchDecision.title_id == row.id,
            OwnershipMatchDecision.revision == expected_revision,
        )).scalar_one_or_none()
        if prior is None or prior.action == 'undo':
            raise ReviewError('No latest decision available to undo', 'conflict')
        game_uuid, reviewed = prior.before_uuid, prior.before_reviewed
    if game_uuid is not None:
        visible = db.session.execute(apply_game_access_filters(
            select(Game.uuid).where(Game.uuid == game_uuid), user,
        )).scalar_one_or_none()
        if visible is None:
            raise ReviewError('Library game not available', 'not_found')
    before, before_reviewed = row.matched_game_uuid, row.match_reviewed
    result = db.session.execute(update(UserOwnedTitle).where(
        UserOwnedTitle.id == row.id, UserOwnedTitle.user_id == user.id,
        UserOwnedTitle.match_revision == expected_revision,
    ).values(matched_game_uuid=game_uuid, match_reviewed=reviewed, match_revision=expected_revision + 1))
    if result.rowcount != 1:
        raise ReviewError('Ownership decision changed; refresh before retrying', 'conflict')
    db.session.add(OwnershipMatchDecision(
        title_id=row.id, revision=expected_revision + 1, actor_id=user.id,
        before_uuid=before, after_uuid=game_uuid, before_reviewed=before_reviewed,
        action='undo' if undo else 'review',
    ))
    db.session.commit()
    return {'title_id': row.id, 'matched_game_uuid': game_uuid,
            'match_reviewed': reviewed, 'match_revision': expected_revision + 1}


REVIEW_FILTERS = ('needs_review', 'matched')


def list_review_titles(user, after_id=0, status=None):
    """Owner-scoped page of recorded titles. ``status='needs_review'`` keeps
    unmatched titles with no decision yet; ``'matched'`` keeps linked ones."""
    query = select(UserOwnedTitle).where(
        UserOwnedTitle.user_id == user.id, UserOwnedTitle.id > after_id,
    )
    if status == 'needs_review':
        query = query.where(UserOwnedTitle.matched_game_uuid.is_(None), UserOwnedTitle.match_reviewed.is_(False))
    elif status == 'matched':
        query = query.where(UserOwnedTitle.matched_game_uuid.isnot(None))
    rows = db.session.execute(query.order_by(UserOwnedTitle.id).limit(51)).scalars().all()
    page = rows[:50]
    ids = {r.matched_game_uuid for r in page if r.matched_game_uuid}
    # Name and platform of the current match, for games this member can see;
    # an inaccessible match stays redacted exactly as before.
    games = {row.uuid: row for row in db.session.execute(apply_game_access_filters(
        select(Game.uuid, Game.name, Library.platform).outerjoin(Library, Game.library_uuid == Library.uuid)
        .where(Game.uuid.in_(ids)), user,
    ))} if ids else {}

    def matched_game(uuid):
        game = games.get(uuid)
        if game is None:
            return None
        return {'name': game.name, 'platform': game.platform.name if game.platform else None}

    return {'titles': [{
        **r.to_dict(), 'id': r.id,
        'matched_game_uuid': r.matched_game_uuid if r.matched_game_uuid in games else None,
        'match_available': bool(r.matched_game_uuid and r.matched_game_uuid in games),
        # Linked to a game in a library this member cannot open: still a match
        # (it counts as matched), just not one to name or link to.
        'match_hidden': bool(r.matched_game_uuid and r.matched_game_uuid not in games),
        'matched_game': matched_game(r.matched_game_uuid),
    } for r in page], 'next_after_id': page[-1].id if len(rows) > 50 else None}


def match_candidates(user, title_id):
    title = db.session.execute(select(UserOwnedTitle).where(
        UserOwnedTitle.id == title_id, UserOwnedTitle.user_id == user.id,
    )).scalar_one_or_none()
    if title is None:
        raise ReviewError('Ownership record not found', 'not_found')
    query = select(Game.uuid, Game.name, Game.library_uuid, Library.platform).join(
        Library, Game.library_uuid == Library.uuid,
    ).where(func.lower(func.trim(Game.name)) == (title.name or '').strip().lower())
    rows = db.session.execute(apply_game_access_filters(query, user).order_by(Game.uuid).limit(21)).all() if title.name else []
    return {'title_id': title.id, 'match_revision': title.match_revision,
            'source': {'store': title.store, 'external_app_id': title.external_app_id},
            'candidates': [{'game_uuid': r.uuid, 'name': r.name, 'library_uuid': r.library_uuid,
                            'platform': r.platform.name if r.platform else None,
                            'basis': 'title_only', 'requires_review': True} for r in rows[:20]],
            'truncated': len(rows) > 20,
            'guidance': 'Confirm edition, remaster, DLC and platform using game details before choosing a match. No game rows are merged.'}
