from unittest.mock import patch
from uuid import uuid4

from oneirodex.models import User


def _user(db_session, role):
    token = uuid4().hex[:10]
    user = User(name=f'stats_{role}_{token}', email=f'stats_{token}@example.test', role=role, user_id=str(uuid4()), state=True, is_email_verified=True)
    user.set_password('review-only-password')
    db_session.add(user)
    db_session.commit()
    return user


def _login(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
        session['_fresh'] = True


def test_statistics_requires_login(client):
    assert client.get('/api/admin/statistics').status_code == 302


def test_statistics_requires_admin(client, db_session):
    _login(client, _user(db_session, 'user'))
    assert client.get('/api/admin/statistics').status_code == 302


def test_statistics_returns_existing_aggregates_in_shared_envelope(client, db_session):
    _login(client, _user(db_session, 'admin'))
    payload = {'totals': {'games': 2}, 'top_games_table': [], 'top_games': {'labels': [], 'data': []}}
    with patch('oneirodex.routes_apis.admin_statistics.get_download_statistics', return_value=payload):
        response = client.get('/api/admin/statistics')
    assert response.status_code == 200
    body = response.get_json()
    assert body['ok'] is True
    assert body['totals'] == payload['totals']
    assert body['top_games_table'] == []
