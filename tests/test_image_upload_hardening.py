"""Phase 3 of the security/legal playbook — image upload limits (S3, S4).

Three things were wrong on this route at once, and the middle one is the reason
the other two mattered:

* the size check read ``file.content_length``, which is 0 for an ordinary
  multipart upload, so it never fired;
* ``img.thumbnail()`` mutated a local and the route then wrote the *original*
  bytes, so the resize was dead code and oversized covers were stored whole;
* nothing bounded pixel count, so the resize was where a decompression bomb
  would have landed.

The resize assertion below is the one that would have caught the dead code:
it reads the file back off disk rather than trusting the 200.

See docs/strategy/security-legal-playbook.md (S3, S4).
"""

from __future__ import annotations

import io
import os
from uuid import uuid4
from urllib.parse import quote

import pytest
from PIL import Image as PILImage
from sqlalchemy import text

from oneirodex.models import Game, Library, LibraryPlatform, User
from oneirodex.routes_admin_ext.game_images import MAX_IMAGE_PIXELS, MAX_IMAGE_UPLOAD_BYTES


@pytest.fixture(scope='function', autouse=True)
def clean_database(db_session):
    db_session.execute(text('TRUNCATE TABLE images RESTART IDENTITY CASCADE'))
    db_session.execute(text('TRUNCATE TABLE games RESTART IDENTITY CASCADE'))
    db_session.execute(text('TRUNCATE TABLE libraries RESTART IDENTITY CASCADE'))
    db_session.commit()


@pytest.fixture
def admin_user(db_session):
    user_uuid = str(uuid4())
    user = User(
        name=f'admin_{user_uuid[:8]}',
        email=f'admin_{user_uuid[:8]}@example.com',
        password_hash='hashed_password',
        role='admin',
        user_id=user_uuid,
        avatarpath='newstyle/avatar_default.jpg',
        invite_quota=10,
    )
    user.set_password('adminpassword123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def sample_game(db_session):
    library = Library(name='Upload Lib', platform=LibraryPlatform.PCWIN, display_order=1)
    db_session.add(library)
    db_session.flush()
    game = Game(library_uuid=library.uuid, name='Upload Game', igdb_id=515151)
    db_session.add(game)
    db_session.commit()
    return game


@pytest.fixture
def image_dir(app, tmp_path):
    """Point the route at a directory the test can read back."""
    target = tmp_path / 'images'
    target.mkdir()
    app.config['IMAGE_SAVE_PATH'] = str(target)
    return target


def _png(width: int, height: int, *, colour=(20, 140, 90)) -> bytes:
    buf = io.BytesIO()
    PILImage.new('RGB', (width, height), colour).save(buf, format='PNG')
    return buf.getvalue()


def _upload(
    client, admin_user, game, payload: bytes, *, kind='cover', name='art.png',
    game_uuid=None,
):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_user.id)
    return client.post(
        f"/upload_image/{game_uuid or game.uuid}",
        data={'file': (io.BytesIO(payload), name), 'image_type': kind},
        content_type='multipart/form-data',
    )


class TestUploadCeiling:
    def test_encoded_windows_traversal_is_rejected_before_writing(
        self, client, admin_user, sample_game, image_dir, tmp_path,
    ):
        malicious_uuid = quote(r'..\..\outside', safe='')
        response = _upload(
            client, admin_user, sample_game, _png(64, 64),
            game_uuid=malicious_uuid,
        )

        assert response.status_code == 404
        assert response.get_json()['error_code'] == 'not_found'
        assert list(image_dir.iterdir()) == []
        assert list(tmp_path.parent.glob('outside_cover_*.png')) == []

    def test_oversize_upload_is_rejected(self, client, admin_user, sample_game, image_dir):
        payload = b'\x89PNG\r\n\x1a\n' + os.urandom(MAX_IMAGE_UPLOAD_BYTES + 1024)
        response = _upload(client, admin_user, sample_game, payload)

        assert response.status_code == 400
        assert b'limit' in response.data.lower()
        # Rejected before anything was written.
        assert list(image_dir.iterdir()) == []

    def test_limit_message_quotes_the_real_number(self, client, admin_user, sample_game, image_dir):
        payload = b'\x89PNG\r\n\x1a\n' + os.urandom(MAX_IMAGE_UPLOAD_BYTES + 1024)
        response = _upload(client, admin_user, sample_game, payload)
        assert f'{MAX_IMAGE_UPLOAD_BYTES // (1024 * 1024)}MB'.encode() in response.data

    def test_normal_upload_still_works(self, client, admin_user, sample_game, image_dir):
        response = _upload(client, admin_user, sample_game, _png(600, 800))

        assert response.status_code == 200
        written = list(image_dir.iterdir())
        assert len(written) == 1
        assert sample_game.uuid not in written[0].name
        with PILImage.open(written[0]) as saved:
            assert saved.size == (600, 800)

    def test_decoded_format_sets_saved_suffix_not_client_filename(
        self, client, admin_user, sample_game, image_dir,
    ):
        response = _upload(
            client, admin_user, sample_game, _png(32, 48), name='art.jpg',
        )
        assert response.status_code == 200
        written = list(image_dir.iterdir())
        assert len(written) == 1
        assert written[0].suffix == '.png'
        with PILImage.open(written[0]) as saved:
            assert saved.format == 'PNG'

    def test_unsupported_decoded_format_is_rejected_even_with_allowed_suffix(
        self, client, admin_user, sample_game, image_dir,
    ):
        payload = io.BytesIO()
        PILImage.new('RGB', (8, 8), (80, 40, 20)).save(payload, format='TIFF')
        response = _upload(
            client, admin_user, sample_game, payload.getvalue(), name='art.png',
        )
        assert response.status_code == 400
        assert list(image_dir.iterdir()) == []

    def test_non_image_bytes_are_rejected(self, client, admin_user, sample_game, image_dir):
        response = _upload(client, admin_user, sample_game, b'not an image at all')
        assert response.status_code == 400
        assert list(image_dir.iterdir()) == []


class TestCoverResize:
    def test_oversized_cover_is_stored_resized(self, client, admin_user, sample_game, image_dir):
        """The regression: thumbnail() ran, then the original bytes were saved."""
        response = _upload(client, admin_user, sample_game, _png(2400, 3200))
        assert response.status_code == 200

        written = list(image_dir.iterdir())
        assert len(written) == 1
        with PILImage.open(written[0]) as saved:
            assert saved.width <= 1200
            assert saved.height <= 1600
            assert saved.size != (2400, 3200)

    def test_resized_cover_keeps_its_format(self, client, admin_user, sample_game, image_dir):
        _upload(client, admin_user, sample_game, _png(2400, 3200))
        written = list(image_dir.iterdir())[0]
        with PILImage.open(written) as saved:
            assert saved.format == 'PNG'

    def test_cover_within_bounds_is_untouched(self, client, admin_user, sample_game, image_dir):
        _upload(client, admin_user, sample_game, _png(1000, 1400))
        written = list(image_dir.iterdir())[0]
        with PILImage.open(written) as saved:
            assert saved.size == (1000, 1400)

    def test_screenshots_are_not_resized(self, client, admin_user, sample_game, image_dir):
        """Only covers carry the 1200x1600 bound."""
        _upload(client, admin_user, sample_game, _png(2000, 1200), kind='screenshot')
        written = list(image_dir.iterdir())[0]
        with PILImage.open(written) as saved:
            assert saved.size == (2000, 1200)


class TestDecompressionBomb:
    def test_pixel_ceiling_clears_ordinary_artwork(self):
        """A 4K cover must be nowhere near the bound."""
        assert 3840 * 2160 < MAX_IMAGE_PIXELS

    def test_huge_canvas_is_rejected(self, client, admin_user, sample_game, image_dir, monkeypatch):
        # Building a real 60-megapixel PNG would cost more than the assertion is
        # worth, so the declared canvas is faked at the decode boundary — which
        # is exactly what a bomb does.
        real_open = PILImage.open

        class _Huge:
            width = 20000
            height = 20000
            format = 'PNG'

            def __enter__(self):
                return self

            def __exit__(self, *_exc):
                return False

            def verify(self):
                return None

            def __getattr__(self, name):
                raise AssertionError(f'decoded a bomb: touched {name}')

        calls = {'n': 0}

        def fake_open(fp, *args, **kwargs):
            calls['n'] += 1
            if calls['n'] <= 2:
                return _Huge()
            return real_open(fp, *args, **kwargs)

        monkeypatch.setattr('PIL.Image.open', fake_open)
        response = _upload(client, admin_user, sample_game, _png(10, 10))

        assert response.status_code == 400
        body = response.get_json()
        assert body['error_code'] == 'bad_request'
        # Assert the substance, not the sentence. This used to look for the word
        # "dimensions", which the UID-041 copy pass replaced with "That image is
        # too big. The limit is 60 megapixels." — the bound is what matters, and
        # it is derived from MAX_IMAGE_PIXELS rather than typed here.
        assert 'megapixels' in body['error'].lower()
        assert list(image_dir.iterdir()) == []
