"""Library visibility ACL (parental / child allow-list).

Rules:
- admin, librarian, user → unrestricted (helper returns None)
- child → allow-list only; empty allow-list means no libraries visible
- child → optional genre/theme deny-list (case-insensitive match)
"""

from __future__ import annotations

from sqlalchemy import delete, func, select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import Game, Genre, Library, Theme, UserContentFilter, UserLibraryAccess
from oneirodex.utils.role_catalog import normalize_role

FILTER_TYPE_GENRE = 'genre'
FILTER_TYPE_THEME = 'theme'


def uses_library_allowlist(user) -> bool:
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    return normalize_role(getattr(user, 'role', None)) == 'child'


uses_content_denylist = uses_library_allowlist


def _normalize_filter_name(name: str) -> str:
    return (name or '').strip().lower()


def allowed_library_uuids(user) -> set[str] | None:
    """Return allowed library UUIDs, or None when unrestricted."""
    if not uses_library_allowlist(user):
        return None
    rows = db.session.execute(
        select(UserLibraryAccess.library_uuid).filter_by(user_id=user.id)
    ).scalars().all()
    return {uuid for uuid in rows if uuid}


def denied_genre_names(user) -> set[str] | None:
    """Return normalized denied genre names, or None when unrestricted."""
    if not uses_content_denylist(user):
        return None
    rows = db.session.execute(
        select(UserContentFilter.name).filter_by(
            user_id=user.id,
            filter_type=FILTER_TYPE_GENRE,
        )
    ).scalars().all()
    return {_normalize_filter_name(name) for name in rows if name}


def denied_theme_names(user) -> set[str] | None:
    """Return normalized denied theme names, or None when unrestricted."""
    if not uses_content_denylist(user):
        return None
    rows = db.session.execute(
        select(UserContentFilter.name).filter_by(
            user_id=user.id,
            filter_type=FILTER_TYPE_THEME,
        )
    ).scalars().all()
    return {_normalize_filter_name(name) for name in rows if name}


def game_matches_content_denylist(user, game: Game | None) -> bool:
    """True when the game is blocked by genre/theme deny-list."""
    if not game or not uses_content_denylist(user):
        return False
    denied_genres = denied_genre_names(user) or set()
    denied_themes = denied_theme_names(user) or set()
    if not denied_genres and not denied_themes:
        return False
    game_genres = {_normalize_filter_name(genre.name) for genre in (game.genres or [])}
    game_themes = {_normalize_filter_name(theme.name) for theme in (game.themes or [])}
    if denied_genres and game_genres & denied_genres:
        return True
    if denied_themes and game_themes & denied_themes:
        return True
    return False


def apply_game_library_acl(query, user):
    """Filter a SQLAlchemy Game query by the user's library allow-list."""
    allowed = allowed_library_uuids(user)
    if allowed is None:
        return query
    if not allowed:
        return query.filter(False)
    return query.filter(Game.library_uuid.in_(allowed))


def apply_game_content_filters(query, user):
    """Exclude games matching the user's genre/theme deny-list."""
    if not uses_content_denylist(user):
        return query
    denied_genres = denied_genre_names(user) or set()
    denied_themes = denied_theme_names(user) or set()
    if denied_genres:
        query = query.filter(
            ~Game.genres.any(func.lower(Genre.name).in_(list(denied_genres)))
        )
    if denied_themes:
        query = query.filter(
            ~Game.themes.any(func.lower(Theme.name).in_(list(denied_themes)))
        )
    return query


def apply_game_access_filters(query, user):
    """Apply library allow-list and content deny-list filters."""
    return apply_game_content_filters(apply_game_library_acl(query, user), user)


def user_can_access_library(user, library_uuid: str | None) -> bool:
    if not library_uuid:
        return False
    allowed = allowed_library_uuids(user)
    if allowed is None:
        return True
    return library_uuid in allowed


def user_can_access_game(user, game: Game | None) -> bool:
    if not game:
        return False
    if not user_can_access_library(user, game.library_uuid):
        return False
    return not game_matches_content_denylist(user, game)


def filter_libraries(libraries, user):
    allowed = allowed_library_uuids(user)
    if allowed is None:
        return list(libraries)
    return [lib for lib in libraries if getattr(lib, 'uuid', None) in allowed]


def get_user_library_allowlist(user_id: int) -> list[str]:
    rows = db.session.execute(
        select(UserLibraryAccess.library_uuid).filter_by(user_id=user_id)
    ).scalars().all()
    return list(rows)


def set_user_library_allowlist(user_id: int, library_uuids: list[str] | None) -> list[str]:
    """Replace allow-list rows for a user. Invalid UUIDs are ignored."""
    db.session.execute(delete(UserLibraryAccess).where(UserLibraryAccess.user_id == user_id))
    cleaned: list[str] = []
    for raw in library_uuids or []:
        uuid = (raw or '').strip()
        if not uuid or uuid in cleaned:
            continue
        exists = db.session.execute(select(Library.uuid).filter_by(uuid=uuid)).scalar_one_or_none()
        if not exists:
            continue
        db.session.add(UserLibraryAccess(user_id=user_id, library_uuid=uuid))
        cleaned.append(uuid)
    db.session.flush()
    return cleaned


def get_user_content_filters(user_id: int) -> dict[str, list[str]]:
    rows = db.session.execute(
        select(UserContentFilter.filter_type, UserContentFilter.name).filter_by(user_id=user_id)
    ).all()
    denied_genres: list[str] = []
    denied_themes: list[str] = []
    for filter_type, name in rows:
        if filter_type == FILTER_TYPE_GENRE:
            denied_genres.append(name)
        elif filter_type == FILTER_TYPE_THEME:
            denied_themes.append(name)
    return {'denied_genres': denied_genres, 'denied_themes': denied_themes}


def set_user_content_filters(
    user_id: int,
    denied_genres: list[str] | None,
    denied_themes: list[str] | None,
) -> dict[str, list[str]]:
    """Replace genre/theme deny-list rows for a user."""
    db.session.execute(delete(UserContentFilter).where(UserContentFilter.user_id == user_id))
    cleaned_genres: list[str] = []
    cleaned_themes: list[str] = []
    seen_genres: set[str] = set()
    seen_themes: set[str] = set()

    for raw in denied_genres or []:
        name = (raw or '').strip()
        if not name:
            continue
        key = _normalize_filter_name(name)
        if key in seen_genres:
            continue
        seen_genres.add(key)
        db.session.add(
            UserContentFilter(user_id=user_id, filter_type=FILTER_TYPE_GENRE, name=name)
        )
        cleaned_genres.append(name)

    for raw in denied_themes or []:
        name = (raw or '').strip()
        if not name:
            continue
        key = _normalize_filter_name(name)
        if key in seen_themes:
            continue
        seen_themes.add(key)
        db.session.add(
            UserContentFilter(user_id=user_id, filter_type=FILTER_TYPE_THEME, name=name)
        )
        cleaned_themes.append(name)

    db.session.flush()
    return {'denied_genres': cleaned_genres, 'denied_themes': cleaned_themes}
