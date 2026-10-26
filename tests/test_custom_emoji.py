"""Custom chat emoji (Wave 17b) unit tests."""

from __future__ import annotations

from io import BytesIO
import struct
from uuid import uuid4
import zlib

import pytest
from PIL import Image
from werkzeug.datastructures import FileStorage

from oneirodex.models import User
from oneirodex.utils.chat import ALLOWED_REACTIONS, is_allowed_reaction
from oneirodex.utils.custom_emoji import (
    MAX_CUSTOM_EMOJI,
    delete_custom_emoji,
    list_custom_emoji,
    normalize_slug,
    upload_custom_emoji,
)


@pytest.fixture
def admin(db_session):
    uid = str(uuid4())
    user = User(
        name=f'emoji_admin_{uid[:8]}',
        email=f'emoji_admin_{uid[:8]}@example.com',
        password_hash='hashed_password',
        role='admin',
        user_id=uid,
        avatarpath='newstyle/avatar_default.jpg',
        invite_quota=5,
        is_email_verified=True,
    )
    user.set_password('testpassword123')
    db_session.add(user)
    db_session.commit()
    return user


def _png_file(name='party.png', size=(64, 64)):
    buf = BytesIO()
    Image.new('RGBA', size, (255, 0, 0, 255)).save(buf, format='PNG')
    buf.seek(0)
    return FileStorage(stream=buf, filename=name, content_type='image/png')


def _png_header(width, height):
    header = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)

    def chunk(kind, data):
        body = kind + data
        return struct.pack('>I', len(data)) + body + struct.pack('>I', zlib.crc32(body))

    return (
        b'\x89PNG\r\n\x1a\n'
        + chunk(b'IHDR', header)
        + chunk(b'IDAT', zlib.compress(b''))
        + chunk(b'IEND', b'')
    )


def test_normalize_slug():
    assert normalize_slug(':Party_1:') == 'party_1'
    with pytest.raises(ValueError):
        normalize_slug('x')
    with pytest.raises(ValueError):
        normalize_slug('Bad Slug!')


def test_is_allowed_reaction_fixed():
    assert is_allowed_reaction('👍') is True
    assert is_allowed_reaction('nope') is False


def test_upload_list_delete(app, db_session, admin, tmp_path, monkeypatch):
    with app.app_context():
        monkeypatch.setitem(app.config, 'UPLOAD_FOLDER', str(tmp_path))
        row = upload_custom_emoji(
            slug='party',
            label='Party',
            file=_png_file(),
            uploader=admin,
        )
        assert row.reaction_key() == ':party:'
        assert is_allowed_reaction(':party:') is True
        listed = list_custom_emoji()
        assert any(item['slug'] == 'party' for item in listed)
        assert delete_custom_emoji('party') is True
        assert is_allowed_reaction(':party:') is False


def test_upload_rejects_duplicate_and_cap(app, db_session, admin, tmp_path, monkeypatch):
    with app.app_context():
        monkeypatch.setitem(app.config, 'UPLOAD_FOLDER', str(tmp_path))
        upload_custom_emoji(slug='one', label='One', file=_png_file(), uploader=admin)
        with pytest.raises(ValueError, match='already exists'):
            upload_custom_emoji(slug='one', label='One', file=_png_file(), uploader=admin)

        # Fill to cap
        for i in range(2, MAX_CUSTOM_EMOJI + 1):
            upload_custom_emoji(
                slug=f'e{i:02d}',
                label=f'E{i}',
                file=_png_file(name=f'e{i}.png'),
                uploader=admin,
            )
        with pytest.raises(ValueError, match='limit'):
            upload_custom_emoji(slug='overflow', label='X', file=_png_file(), uploader=admin)


def test_upload_rejects_oversized_dimensions_before_decode_or_file_creation(
    app, db_session, admin, tmp_path, monkeypatch,
):
    def fail_if_decoded(*_args, **_kwargs):
        raise AssertionError('oversized emoji image must be rejected before decode')

    monkeypatch.setattr(Image.Image, 'load', fail_if_decoded)
    monkeypatch.setattr(Image.Image, 'convert', fail_if_decoded)
    monkeypatch.setitem(app.config, 'UPLOAD_FOLDER', str(tmp_path))
    upload = FileStorage(
        stream=BytesIO(_png_header(3000, 3000)),
        filename='large.png', content_type='image/png',
    )

    with app.app_context(), pytest.raises(ValueError, match='dimensions are too large'):
        upload_custom_emoji(slug='large', label='Large', file=upload, uploader=admin)

    assert not (tmp_path / 'chat-emoji').exists()


def test_fixed_set_unchanged():
    assert len(ALLOWED_REACTIONS) == 5
