from datetime import datetime, timedelta, timezone
from uuid import uuid4

from oneirodex.models import Game, Library, PlaySession, User, UserGameProgress
from oneirodex.platform import LibraryPlatform


def test_orphan_playtime_duration_caps_at_last_heartbeat_ttl(
    db_session, monkeypatch,
):
    from oneirodex.utils import playtime

    user_key = str(uuid4())
    user = User(
        name=f'playtime-ttl-{user_key[:8]}',
        email=f'playtime-ttl-{user_key[:8]}@example.test',
        password_hash='unused',
        role='user',
        user_id=user_key,
        avatarpath='newstyle/avatar_default.jpg',
        state=True,
    )
    library = Library(
        name=f'Playtime TTL {user_key[:8]}',
        platform=LibraryPlatform.PCWIN,
    )
    game = Game(
        name=f'Playtime TTL Game {user_key[:8]}',
        slug=f'playtime-ttl-{user_key[:8]}',
        summary='Disposable playtime parity fixture.',
        library=library,
    )
    started_at = datetime(2025, 1, 1)
    session = PlaySession(
        user=user,
        game=game,
        started_at=started_at,
        last_heartbeat_at=started_at + timedelta(seconds=30),
        duration_seconds=0,
        client='parity-test',
        status='active',
    )
    db_session.add_all([user, library, game, session])
    db_session.commit()

    monkeypatch.setattr(
        playtime,
        '_utcnow',
        lambda: started_at.replace(tzinfo=timezone.utc) + timedelta(days=5),
    )
    monkeypatch.setattr(playtime.event_bus, 'publish', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        playtime,
        'notify_play_session_stopped',
        lambda **_kwargs: None,
    )

    ended = playtime.end_session(session, orphan=True, config={})

    expected_end = started_at + timedelta(seconds=30 + playtime.HEARTBEAT_TTL_SECONDS)
    progress = db_session.query(UserGameProgress).filter_by(
        user_id=user.id,
        game_uuid=game.uuid,
    ).one()
    assert ended.status == 'orphaned'
    assert ended.ended_at.replace(tzinfo=None) == expected_end
    assert ended.duration_seconds == 150
    assert progress.total_seconds == 150
    assert progress.session_count == 1
    assert progress.last_played_at.replace(tzinfo=None) == expected_end
