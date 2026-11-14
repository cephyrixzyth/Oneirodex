"""Admin font upload + batch artwork upload."""

from __future__ import annotations

import io
from uuid import uuid4

import pytest
from flask import json
from sqlalchemy import text

from oneirodex import db
from oneirodex.models import Game, Image, Library, LibraryPlatform, User
from oneirodex.utils.theme_fonts import looks_like_font, store_font_file

TTF_HEAD = b'\x00\x01\x00\x00'
PNG_HEAD = b'\x89PNG\r\n\x1a\n'


@pytest.fixture(scope='function', autouse=True)
def clean(db_session):
    db_session.execute(text('TRUNCATE TABLE images RESTART IDENTITY CASCADE'))
    db_session.execute(text('TRUNCATE TABLE games RESTART IDENTITY CASCADE'))
    db_session.execute(text('TRUNCATE TABLE libraries RESTART IDENTITY CASCADE'))
    db_session.commit()


@pytest.fixture
def admin_user(db_session):
    uid = str(uuid4())
    user = User(
        name=f'admin_{uid[:8]}',
        email=f'admin_{uid[:8]}@example.com',
        password_hash='hashed_password',
        role='admin',
        user_id=uid,
        avatarpath='newstyle/avatar_default.jpg',
        invite_quota=10,
        is_email_verified=True,
    )
    user.set_password('adminpassword123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def game(db_session):
    lib = Library(name='Batch Lib', platform=LibraryPlatform.PCWIN, display_order=1)
    db_session.add(lib)
    db_session.flush()
    row = Game(library_uuid=lib.uuid, name='Batch Game', igdb_id=771177)
    db_session.add(row)
    db_session.commit()
    return row


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


class TestFontUpload:
    def test_accepts_a_real_font(self, client, app, admin_user, tmp_path):
        app.config['FONT_PATH'] = str(tmp_path)
        _login(client, admin_user)
        response = client.post(
            '/admin/api/theme/fonts',
            data={'file': (io.BytesIO(TTF_HEAD + b'\x00' * 64), 'MyFace.ttf')},
            content_type='multipart/form-data',
        )
        assert response.status_code == 201
        assert (tmp_path / 'MyFace.ttf').exists()

    def test_rejects_a_non_font_extension(self, client, app, admin_user, tmp_path):
        app.config['FONT_PATH'] = str(tmp_path)
        _login(client, admin_user)
        response = client.post(
            '/admin/api/theme/fonts',
            data={'file': (io.BytesIO(b'x' * 32), 'payload.exe')},
            content_type='multipart/form-data',
        )
        assert response.status_code == 400

    def test_rejects_a_renamed_non_font(self, client, app, admin_user, tmp_path):
        """Extension is not evidence — this file is served back to browsers."""
        app.config['FONT_PATH'] = str(tmp_path)
        _login(client, admin_user)
        response = client.post(
            '/admin/api/theme/fonts',
            data={'file': (io.BytesIO(b'<html>nope</html>'), 'evil.ttf')},
            content_type='multipart/form-data',
        )
        assert response.status_code == 400
        assert 'does not look like a font' in json.loads(response.data)['error']

    def test_write_failure_does_not_expose_server_path(
        self, client, app, admin_user, tmp_path, monkeypatch,
    ):
        from oneirodex.utils import theme_fonts

        private_path = r'C:\private\oneirodex\fonts\custom.ttf'
        app.config['FONT_PATH'] = str(tmp_path)
        _login(client, admin_user)

        def fail_write(*_args, **_kwargs):
            raise OSError(13, 'Permission denied', private_path)

        monkeypatch.setattr(theme_fonts, 'store_font_file', fail_write)
        response = client.post(
            '/admin/api/theme/fonts',
            data={'file': (io.BytesIO(TTF_HEAD + b'\x00' * 64), 'custom.ttf')},
            content_type='multipart/form-data',
        )

        body = json.loads(response.data)
        assert response.status_code == 503
        assert body['error'] == 'Could not write the font file.'
        assert private_path not in response.get_data(as_text=True)

    def test_magic_check_covers_every_accepted_container(self):
        for sig in (b'\x00\x01\x00\x00', b'OTTO', b'wOFF', b'wOF2', b'true', b'ttcf'):
            assert looks_like_font(sig + b'rest')
        assert not looks_like_font(b'GIF89a')

    def test_builtin_font_cannot_be_deleted(self, client, app, admin_user, tmp_path):
        app.config['FONT_PATH'] = str(tmp_path)
        _login(client, admin_user)
        response = client.delete('/admin/api/theme/fonts/VT323-Regular.ttf')
        assert response.status_code == 400

    def test_empty_upload_is_refused(self, app, tmp_path):
        with app.app_context():
            app.config['FONT_PATH'] = str(tmp_path)

            class _F:
                filename = 'x.ttf'
                stream = io.BytesIO(b'')

            with pytest.raises(ValueError, match='empty'):
                store_font_file(_F())


class TestBatchImageUpload:
    def test_matches_files_to_games_by_uuid(self, client, app, db_session, admin_user, game, tmp_path):
        app.config['IMAGE_SAVE_PATH'] = str(tmp_path)
        _login(client, admin_user)
        response = client.post(
            '/admin/api/images/batch_upload',
            data={
                'files': [
                    (io.BytesIO(PNG_HEAD + b'a' * 32), f'{game.uuid}_cover.png'),
                    (io.BytesIO(PNG_HEAD + b'b' * 32), f'{game.uuid}_logo.png'),
                ],
            },
            content_type='multipart/form-data',
        )
        assert response.status_code == 200
        body = json.loads(response.data)
        assert body['stored'] == 2
        kinds = {row['kind'] for row in body['images']}
        assert kinds == {'cover', 'logo'}

    def test_one_bad_file_does_not_sink_the_batch(self, client, app, db_session, admin_user, game, tmp_path):
        app.config['IMAGE_SAVE_PATH'] = str(tmp_path)
        _login(client, admin_user)
        response = client.post(
            '/admin/api/images/batch_upload',
            data={
                'files': [
                    (io.BytesIO(PNG_HEAD + b'a' * 32), f'{game.uuid}_cover.png'),
                    (io.BytesIO(b'nope'), 'notes.txt'),
                    (io.BytesIO(PNG_HEAD), f'{uuid4()}_cover.png'),
                ],
            },
            content_type='multipart/form-data',
        )
        body = json.loads(response.data)
        assert body['stored'] == 1
        assert body['failed'] == 2
        reasons = ' '.join(e['error'] for e in body['errors'])
        assert 'Unsupported' in reasons
        assert 'No game matched' in reasons

    def test_explicit_target_overrides_filename_parsing(self, client, app, db_session, admin_user, game, tmp_path):
        app.config['IMAGE_SAVE_PATH'] = str(tmp_path)
        _login(client, admin_user)
        response = client.post(
            '/admin/api/images/batch_upload',
            data={
                'game_uuid': game.uuid,
                'image_type': 'screenshot',
                'files': [(io.BytesIO(PNG_HEAD + b'a' * 16), 'anything-at-all.png')],
            },
            content_type='multipart/form-data',
        )
        body = json.loads(response.data)
        assert body['stored'] == 1
        assert body['images'][0]['kind'] == 'screenshot'

    def test_no_files_is_a_clear_error(self, client, app, admin_user):
        _login(client, admin_user)
        response = client.post(
            '/admin/api/images/batch_upload',
            data={},
            content_type='multipart/form-data',
        )
        assert response.status_code == 400
