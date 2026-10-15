"""Pagination input contract for the Flask activity-feed compatibility route."""

from __future__ import annotations

from uuid import uuid4

import pytest
from flask_login import login_user

from oneirodex.models import User


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
