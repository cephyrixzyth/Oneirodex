from sqlalchemy import select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import Genre, GameMode, PlayerPerspective


def _get_or_create_perspective(persp_name):
    persp_obj = db.session.execute(
        select(PlayerPerspective).filter_by(name=persp_name)
    ).scalar_one_or_none()
    if not persp_obj:
        persp_obj = PlayerPerspective(name=persp_name)
        db.session.add(persp_obj)
    return persp_obj


def _get_or_create_genre(genre_name):
    genre_obj = db.session.execute(
        select(Genre).filter_by(name=genre_name)
    ).scalar_one_or_none()
    if not genre_obj:
        genre_obj = Genre(name=genre_name)
        db.session.add(genre_obj)
    return genre_obj


def _get_or_create_game_mode(mode_name):
    mode_obj = db.session.execute(
        select(GameMode).filter_by(name=mode_name)
    ).scalar_one_or_none()
    if not mode_obj:
        mode_obj = GameMode(name=mode_name)
        db.session.add(mode_obj)
    return mode_obj


def _append_unique(relation_list, entity):
    if entity is None:
        return
    if entity not in relation_list:
        relation_list.append(entity)


def _attach_named_relations(
    game_obj,
    enriched,
    perspective_factory=None,
    genre_factory=None,
    game_mode_factory=None,
):
    get_perspective = perspective_factory or _get_or_create_perspective
    get_genre = genre_factory or _get_or_create_genre
    get_mode = game_mode_factory or _get_or_create_game_mode

    if enriched.get('player_perspectives'):
        for persp_name in enriched['player_perspectives']:
            if not persp_name:
                continue
            persp_obj = get_perspective(persp_name)
            _append_unique(game_obj.player_perspectives, persp_obj)

    if enriched.get('genres'):
        for genre_name in enriched['genres']:
            if not genre_name:
                continue
            genre_obj = get_genre(genre_name)
            _append_unique(game_obj.genres, genre_obj)

    if enriched.get('game_modes'):
        # Ensure relation list exists on duck-typed test doubles
        if getattr(game_obj, 'game_modes', None) is None:
            game_obj.game_modes = []
        for mode_name in enriched['game_modes']:
            if not mode_name:
                continue
            mode_obj = get_mode(mode_name)
            _append_unique(game_obj.game_modes, mode_obj)


def apply_enriched_metadata(
    game_obj,
    enriched,
    perspective_factory=None,
    genre_factory=None,
    game_mode_factory=None,
):
    """Apply enrichment (already fetched over HTTP) inside a SAVEPOINT.

    Returns False if the savepoint was rolled back due to an error, so
    partially-applied secondary metadata never corrupts the caller's
    outer transaction. The caller remains responsible for the outer
    `db.session.commit()`.
    """
    if not game_obj or not enriched:
        return True
    try:
        with db.session.begin_nested():
            if not game_obj.summary and enriched.get('summary'):
                game_obj.summary = enriched['summary']
            _attach_named_relations(
                game_obj,
                enriched,
                perspective_factory=perspective_factory,
                genre_factory=genre_factory,
                game_mode_factory=game_mode_factory,
            )
        return True
    except Exception as e:
        print(f"Metadata enrichment savepoint rollback: {e}")
        return False
