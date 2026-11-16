"""Wave 2c — Report / Notifications / News API honesty for UI overhaul."""

from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest
from flask_login import login_user

from oneirodex.models import Announcement, User


@pytest.fixture
def member_user(db_session):
    uid = str(uuid4())
    user = User(
        name=f'w2c_member_{uid[:8]}',
        email=f'w2c_member_{uid[:8]}@example.com',
        role='user',
        user_id=uid,
        state=True,
    )
    user.set_password('password123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def admin_user(db_session):
    uid = str(uuid4())
    user = User(
        name=f'w2c_admin_{uid[:8]}',
        email=f'w2c_admin_{uid[:8]}@example.com',
        role='admin',
        user_id=uid,
        state=True,
    )
    user.set_password('password123')
    db_session.add(user)
    db_session.commit()
    return user


def _login(client, app, account):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(account.id)
        sess['_fresh'] = True
    with app.test_request_context():
        login_user(account)


def test_support_ticket_title_only_optional_symptom_logs(client, app, db_session, member_user):
    _login(client, app, member_user)
    with patch('oneirodex.routes_apis.support.create_github_issue', return_value={'ok': False, 'skipped': True}):
        created = client.post(
            '/api/support/tickets',
            json={'title': 'Launcher flicker', 'area': 'companion', 'severity': 'P2'},
        )
    assert created.status_code == 201, created.get_data(as_text=True)
    ticket = created.get_json()['ticket']
    assert ticket['title'] == 'Launcher flicker'
    assert ticket['body'] == ''
    assert ticket['logs'] is None
    assert ticket['has_logs'] is False
    assert ticket['github_sync'] == 'local_only'


def test_support_ticket_missing_title_is_422(client, app, db_session, member_user):
    _login(client, app, member_user)
    created = client.post('/api/support/tickets', json={'area': 'companion'})
    assert created.status_code == 422, created.get_data(as_text=True)
    body = created.get_json()
    assert body['error'] == 'Invalid request.'
    assert body['error_code'] == 'unprocessable'
    assert 'title' in body['detail']


def test_support_ticket_truncates_huge_logs_and_list_is_compact(client, app, db_session, member_user):
    _login(client, app, member_user)
    huge = 'L' * 9000
    long_body = 'B' * 3000
    with patch('oneirodex.routes_apis.support.create_github_issue', return_value={'ok': False, 'skipped': True}):
        created = client.post(
            '/api/support/tickets',
            json={
                'title': 'Huge paste',
                'body': long_body,
                'logs': huge,
                'area': 'other',
            },
        )
    assert created.status_code == 201
    detail = created.get_json()['ticket']
    assert len(detail['body']) == 2000
    assert len(detail['logs']) == 4000
    assert detail['has_logs'] is True

    listed = client.get('/api/support/tickets')
    assert listed.status_code == 200
    payload = listed.get_json()
    assert payload['empty'] is False
    row = next(t for t in payload['tickets'] if t['id'] == detail['id'])
    assert row['logs'] is None
    assert row['has_logs'] is True
    assert len(row['body']) <= 280
    assert row['body_truncated'] is True

    full = client.get(f'/api/support/tickets/{detail["id"]}')
    assert full.status_code == 200
    full_ticket = full.get_json()['ticket']
    assert full_ticket['logs'] is not None
    assert len(full_ticket['logs']) == 4000


def test_notifications_empty_and_bad_limit(client, app, db_session, member_user):
    _login(client, app, member_user)
    empty = client.get('/api/notifications')
    assert empty.status_code == 200
    data = empty.get_json()
    assert data['notifications'] == []
    assert data['unread_count'] == 0
    assert data['empty'] is True

    bad_limit = client.get('/api/notifications?limit=nope')
    assert bad_limit.status_code == 200
    assert isinstance(bad_limit.get_json()['notifications'], list)

    prefs = client.get('/api/notifications/preferences')
    assert prefs.status_code == 200
    body = prefs.get_json()
    assert 'notify_chat' in body
    assert 'email_digest_daily' in body

    marked = client.post('/api/notifications/read', json={'all': True})
    assert marked.status_code == 200
    marked_body = marked.get_json()
    assert marked_body['ok'] is True
    assert marked_body['error'] is None
    assert marked_body['marked'] == 0


def test_news_feeds_never_500_on_empty_or_failure(client, app, db_session, member_user, monkeypatch):
    _login(client, app, member_user)

    # Shared test DB may retain announcements from earlier suites — isolate empty-path honesty.
    db_session.query(Announcement).delete()
    db_session.commit()

    announce = client.get('/api/announcements')
    assert announce.status_code == 200
    a = announce.get_json()
    assert a['announcements'] == []
    assert a['empty'] is True

    with patch(
        'oneirodex.utils.gaming_news.fetch_gaming_headlines',
        side_effect=RuntimeError('rss down'),
    ):
        news = client.get('/api/news/gaming?limit=12')
    assert news.status_code == 200
    n = news.get_json()
    assert n['items'] == []
    assert n['empty'] is True

    monkeypatch.setitem(app.config, 'ENABLE_FREE_GAMES', False)
    free = client.get('/api/news/free-games')
    assert free.status_code == 200
    f = free.get_json()
    assert f['items'] == []
    assert f['enabled'] is False
    assert f['empty'] is True


def test_announcement_includes_body_preview(client, app, db_session, admin_user, member_user):
    _login(client, app, admin_user)
    long = 'X' * 400
    created = client.post(
        '/api/announcements',
        json={'title': 'Preview me', 'body': long, 'published': True},
    )
    assert created.status_code == 201
    assert created.get_json()['body_preview'] == long[:280]

    _login(client, app, member_user)
    listed = client.get('/api/announcements')
    assert listed.status_code == 200
    row = listed.get_json()['announcements'][0]
    assert row['body_preview'] == long[:280]
    assert row['body'] == long
