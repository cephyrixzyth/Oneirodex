"""React preferences use the existing preference choices and account session."""
from uuid import uuid4
import re

from oneirodex.models import User


def csrf_header(client):
    page = client.get('/library').get_data(as_text=True)
    token = re.search(r'<meta name="csrf-token" content="([^"]+)"', page)
    assert token is not None
    return {'X-CSRFToken': token.group(1)}


def test_preferences_get_exposes_choices_and_current_values(client, db_session):
    user = User(
        name=f'prefs_{uuid4().hex[:8]}', email=f'{uuid4().hex[:8]}@example.com',
        password_hash='x', role='user', user_id=str(uuid4()),
    )
    db_session.add(user)
    db_session.commit()
    with client.session_transaction() as session:
        session['_user_id'] = user.get_id()
        session['_fresh'] = True

    response = client.get('/api/account/preferences')

    assert response.status_code == 200
    body = response.get_json()
    assert body['preferences']['theme'] == 'default'
    assert body['preferences']['tile_size'] == '50'
    assert body['choices']['themes']
    assert body['choices']['icon_packs']
    assert body['is_admin'] is False


def test_preferences_put_validates_and_persists(client, db_session):
    user = User(
        name=f'prefs_{uuid4().hex[:8]}', email=f'{uuid4().hex[:8]}@example.com',
        password_hash='x', role='user', user_id=str(uuid4()),
    )
    db_session.add(user)
    db_session.commit()
    with client.session_transaction() as session:
        session['_user_id'] = user.get_id()
        session['_fresh'] = True
    headers = csrf_header(client)

    response = client.put('/api/account/preferences', json={
        'items_per_page': 100,
        'default_sort': 'rating',
        'default_sort_order': 'desc',
        'theme': 'default',
        'icon_pack': 'outline',
        'font': 'system-ui',
        'tile_size': '72',
        'show_tile_titles': False,
        'browser_player_engine': '',
        'preferred_game_locale': 'ja-JP',
    }, headers=headers)

    assert response.status_code == 200
    assert response.get_json()['ok'] is True
    db_session.refresh(user)
    assert user.preferences.items_per_page == 100
    assert user.preferences.tile_size == '72'
    assert user.preferences.show_tile_titles is False
    assert user.preferences.preferred_game_locale == 'ja-JP'


def test_preferences_put_rejects_invalid_select_choice(client, db_session):
    user = User(
        name=f'prefs_{uuid4().hex[:8]}', email=f'{uuid4().hex[:8]}@example.com',
        password_hash='x', role='user', user_id=str(uuid4()),
    )
    db_session.add(user)
    db_session.commit()
    with client.session_transaction() as session:
        session['_user_id'] = user.get_id()
        session['_fresh'] = True
    headers = csrf_header(client)

    response = client.put('/api/account/preferences', json={'default_sort': 'arbitrary-column'}, headers=headers)

    assert response.status_code == 400
    assert response.get_json()['error_code'] == 'bad_request'

    malformed = client.put('/api/account/preferences', json={'unrecognized': 'value'}, headers=headers)
    assert malformed.status_code == 422
    assert malformed.get_json()['error_code'] == 'unprocessable'
