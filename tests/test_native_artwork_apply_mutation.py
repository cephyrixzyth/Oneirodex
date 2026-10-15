from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.artwork_apply_mutation import create_artwork_apply_router
from oneirodex.runtime_native.session_compat import dump_session_cookie


def make_client(*, data=None, role='admin'):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-artwork-apply-secret', WTF_CSRF_ENABLED=False)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=7, role=role, is_active=True, state=True, is_authenticated=True,
        session_fingerprint=lambda: 'fp',
    )
    manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={}, login_message='Please log in.',
        login_message_category='message', localize_callback=None, session_protection='basic',
    )
    app = FastAPI()
    app.include_router(create_artwork_apply_router(
        flask_app, find_user=lambda value: user if value == 7 else None,
        find_token=lambda _prefix: None, commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.startswith('7:') else None,
        login_manager=manager, data_access=data or SimpleNamespace(
            game_exists=lambda _uuid: True,
            apply=lambda game_uuid, url, *, provider_id, image_type: {
                'game_uuid': game_uuid, 'url': url,
                'provider': provider_id, 'image_type': image_type,
            },
        ),
    ))
    client = TestClient(app)
    client.cookies.set('session', dump_session_cookie(
        {'_user_id': '7:fp', '_fresh': True}, 'native-artwork-apply-secret',
    ))
    return client


def test_apply_artwork_preserves_provider_and_kind_alias():
    response = make_client().post(
        '/api/games/game-1/artwork/steamgriddb',
        json={'url': 'https://images.invalid/game.jpg', 'provider': 'igdb', 'kind': 'cover'},
    )

    assert response.status_code == 200
    assert response.json() == {
        'game_uuid': 'game-1', 'url': 'https://images.invalid/game.jpg',
        'provider': 'igdb', 'image_type': 'cover',
    }


def test_apply_artwork_validation_and_game_not_found_do_not_apply():
    calls = []
    data = SimpleNamespace(
        game_exists=lambda _uuid: False,
        apply=lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    client = make_client(data=data)
    invalid = client.post('/api/games/game-1/artwork/steamgriddb', json={'url': ''})
    missing = client.post('/api/games/game-1/artwork/steamgriddb', json={'url': 'https://images.invalid/a.jpg'})

    assert invalid.status_code == 422
    assert invalid.json()['error_code'] == 'unprocessable'
    assert missing.status_code == 404
    assert calls == []


def test_apply_artwork_rejects_unsupported_provider_and_image_kind():
    client = make_client()
    provider = client.post('/api/games/game-1/artwork/steamgriddb', json={
        'url': 'https://images.invalid/a.jpg', 'provider': 'other',
    })
    igdb_kind = client.post('/api/games/game-1/artwork/steamgriddb', json={
        'url': 'https://images.invalid/a.jpg', 'provider': 'igdb', 'image_type': 'logo',
    })

    assert provider.status_code == 400
    assert igdb_kind.status_code == 400


def test_apply_artwork_provider_failure_keeps_legacy_unavailable_status():
    def fail(*_args, **_kwargs):
        raise RuntimeError('provider is unavailable')

    client = make_client(data=SimpleNamespace(game_exists=lambda _uuid: True, apply=fail))
    response = client.post('/api/games/game-1/artwork/steamgriddb', json={
        'url': 'https://images.invalid/a.jpg',
    })

    assert response.status_code == 503
    assert response.json()['error_code'] == 'unavailable'
