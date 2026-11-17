"""Tests for IGDB cover provider registration and health summary shape."""

from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest
from flask_login import login_user

from oneirodex.models import Game, Library, User
from oneirodex.platform import LibraryPlatform
from oneirodex.utils.library_health import score_game, summarize_library_health
from oneirodex.utils.providers import IgdbCoverProvider, get_provider, list_providers, reset_provider_cache


@pytest.fixture(autouse=True)
def _reset_providers():
    reset_provider_cache()
    yield
    reset_provider_cache()


@pytest.fixture
def admin(db_session):
    uid = str(uuid4())
    row = User(
        name=f'hadmin_{uid[:8]}',
        email=f'hadmin_{uid[:8]}@example.com',
        role='admin',
        user_id=uid,
        state=True,
    )
    row.set_password('password123')
    db_session.add(row)
    db_session.commit()
    return row


def _login(client, app, account):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(account.get_id())
        sess['_fresh'] = True
    with app.test_request_context():
        login_user(account)


def test_igdb_provider_registered(app):
    with app.app_context():
        ids = {p['id'] for p in list_providers()}
        assert 'igdb' in ids
        assert 'steamgriddb' in ids
        assert isinstance(get_provider('igdb'), IgdbCoverProvider)


def test_igdb_search_requires_credentials(client, app, admin):
    _login(client, app, admin)
    with patch('oneirodex.utils.providers.igdb.igdb_credentials_configured', return_value=False):
        reset_provider_cache()
        resp = client.get('/api/providers/igdb/search?q=Celeste')
        assert resp.status_code == 503


def test_library_health_summary_shape(db_session):
    lib = Library(name=f'HLib_{uuid4().hex[:6]}', platform=LibraryPlatform.PCWIN)
    db_session.add(lib)
    db_session.flush()
    game = Game(
        uuid=str(uuid4()),
        name=f'Health Game {uuid4().hex[:6]}',
        library_uuid=lib.uuid,
        full_disk_path='',
        summary='',
    )
    db_session.add(game)
    db_session.commit()

    scored = score_game(game)
    assert 'score' in scored and 'issues' in scored
    summary = summarize_library_health(limit=50, library_uuid=lib.uuid)
    assert summary['count'] >= 1
    assert 'average_score' in summary
    assert 'worst' in summary


def test_health_api_admin_only(client, app, admin, db_session):
    _login(client, app, admin)
    resp = client.get('/api/health/library?limit=10')
    assert resp.status_code == 200
    body = resp.get_json()
    assert 'average_score' in body
