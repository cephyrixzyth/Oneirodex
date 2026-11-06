"""Pagination input contract for the Flask activity-feed compatibility route."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from flask_login import login_user

from oneirodex.models import User
from oneirodex.utils.activity_feed import list_now_playing


@pytest.fixture
def member(db_session):
    uid = str(uuid4())
    user = User(
        name=f'activity_{uid[:8]}',
        email=f'activity_{uid[:8]}@example.com',
        role='user',
        user_id=uid,
        state=True,
    )
    user.set_password('activity-test-password')
    db_session.add(user)
    db_session.commit()
    return user


def _login(client, app, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.get_id())
        sess['_fresh'] = True
    with app.test_request_context():
        login_user(user)


def test_child_now_playing_projection_is_empty_without_reading_sessions(monkeypatch):
    def unexpected_session_query(**_kwargs):
        raise AssertionError('child activity must be filtered before querying sessions')

    monkeypatch.setattr(
        'oneirodex.utils.activity_feed.list_recent_activity',
        unexpected_session_query,
    )

    assert list_now_playing(viewer=SimpleNamespace(role='child', id=42)) == []


@pytest.mark.parametrize(('raw_limit', 'expected'), [('many', 25), ('500', 100)])
def test_activity_limit_is_robust_and_bounded(
    client, app, member, monkeypatch, raw_limit, expected,
):
    calls = []
    monkeypatch.setattr(
        'oneirodex.routes_apis.wave8_11.list_recent_activity',
        lambda *, limit, **_kwargs: calls.append(limit) or [],
    )
    monkeypatch.setattr(
        'oneirodex.routes_apis.wave8_11.list_now_playing',
        lambda **_kwargs: [],
    )
    _login(client, app, member)

    response = client.get(f'/api/activity?limit={raw_limit}')

    assert response.status_code == 200
    assert calls == [expected]
