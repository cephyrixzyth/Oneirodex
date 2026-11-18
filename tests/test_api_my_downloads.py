"""Tests for GET /api/my_downloads."""

from uuid import uuid4

import pytest
from flask_login import login_user

from oneirodex.models import DownloadRequest, Game, Library, User
from oneirodex.platform import LibraryPlatform


@pytest.fixture
def member_user(db_session):
    uid = str(uuid4())
    user = User(
        name=f'dluser_{uid[:8]}',
        email=f'dluser_{uid[:8]}@example.com',
        role='user',
        user_id=uid,
        state=True,
    )
    user.set_password('password123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def sample_library(db_session):
    library = Library(name=f'DlLib_{uuid4().hex[:6]}', platform=LibraryPlatform.PCWIN)
    db_session.add(library)
    db_session.commit()
    return library


@pytest.fixture
def sample_game(db_session, sample_library):
    game = Game(
        name='Downloadable Game',
        full_disk_path='/tmp/downloadable_game',
        library_uuid=sample_library.uuid,
        size=2048.0,
    )
    db_session.add(game)
    db_session.commit()
    return game


@pytest.fixture
def auth_client(client, app, member_user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(member_user.get_id())
        sess['_fresh'] = True
    with app.test_request_context():
        login_user(member_user)
    return client


@pytest.fixture
def download_request_factory(db_session, member_user, sample_game):
    def _factory(status='pending', zip_file_path='/tmp/zips/game_file.zip'):
        request = DownloadRequest(
            user_id=member_user.id,
            game_uuid=sample_game.uuid,
            status=status,
            zip_file_path=zip_file_path,
            download_size=1024.0,
        )
        db_session.add(request)
        db_session.commit()
        return request

    return _factory


def test_my_downloads_requires_login(client):
    assert client.get('/api/my_downloads').status_code in (401, 302)




def test_my_downloads_lists_current_user_requests(auth_client, download_request_factory):
    download_request_factory(status='pending')
    response = auth_client.get('/api/my_downloads')
    assert response.status_code == 200
    data = response.get_json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert data[0]['id']
    assert data[0]['game_name'] == 'Downloadable Game'
    assert data[0]['status'] == 'pending'
    assert data[0]['file_name'] == 'game_file.zip'
    assert data[0]['download_url'] is None


def test_my_downloads_includes_download_url_when_available(auth_client, download_request_factory):
    created = download_request_factory(status='available')
    data = auth_client.get('/api/my_downloads').get_json()
    row = next(item for item in data if item['id'] == created.id)
    assert row['download_url'] == f'/download_zip/{created.id}'
