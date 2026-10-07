"""Wave 16 — chat message file/image attachments."""

from __future__ import annotations

from io import BytesIO
from uuid import uuid4

import pytest
from PIL import Image
from werkzeug.datastructures import FileStorage

from oneirodex.models import User
from oneirodex.utils.chat import create_household_channel, list_messages, post_message
from oneirodex.utils.chat_attachments import (
    MAX_ATTACHMENT_BYTES,
    _stored_attachment_bytes,
    upload_attachment,
)


def _make_user(db_session, *, role: str, prefix: str) -> User:
    uid = str(uuid4())
    user = User(
        name=f'{prefix}_{uid[:8]}',
        email=f'{prefix}_{uid[:8]}@example.com',
        password_hash='hashed_password',
        role=role,
        user_id=uid,
        avatarpath='newstyle/avatar_default.jpg',
    )
    user.set_password('testpassword123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def member(db_session):
    return _make_user(db_session, role='user', prefix='att_member')


@pytest.fixture
def child(db_session):
    return _make_user(db_session, role='child', prefix='att_child')


def _png_file(name='shot.png', size=(32, 32)):
    buf = BytesIO()
    Image.new('RGBA', size, (0, 128, 255, 255)).save(buf, format='PNG')
    buf.seek(0)
    return FileStorage(stream=buf, filename=name, content_type='image/png')


def _txt_file(name='notes.txt', content=b'hello household'):
    return FileStorage(
        stream=BytesIO(content),
        filename=name,
        content_type='text/plain',
    )


def test_upload_and_attach_on_message(app, db_session, member, tmp_path, monkeypatch):
    with app.app_context():
        monkeypatch.setitem(app.config, 'UPLOAD_FOLDER', str(tmp_path))
        ch = create_household_channel(
            member,
            name='Attach room',
            slug=f'attach-{uuid4().hex[:8]}',
        )
        pending = upload_attachment(channel=ch, user=member, file=_png_file())
        assert pending.id
        assert pending.message_id is None
        payload = pending.to_dict()
        assert payload['mime'] == 'image/png'
        assert payload['url'].startswith('/api/chat/attachments/')
        assert payload['size'] > 0

        msg = post_message(
            ch,
            member,
            'see this',
            attachment_ids=[pending.id],
        )
        listed = list_messages(ch.id, viewer_user_id=member.id)
        row = next(m for m in listed if m['id'] == msg.id)
        assert row['body'] == 'see this'
        assert len(row['attachments']) == 1
        assert row['attachments'][0]['id'] == pending.id
        assert 'reactions' in row
        assert 'mine' in row


def test_attachment_only_message(app, db_session, member, tmp_path, monkeypatch):
    with app.app_context():
        monkeypatch.setitem(app.config, 'UPLOAD_FOLDER', str(tmp_path))
        ch = create_household_channel(
            member,
            name='File only',
            slug=f'fileonly-{uuid4().hex[:8]}',
        )
        pending = upload_attachment(channel=ch, user=member, file=_txt_file())
        msg = post_message(ch, member, '', attachment_ids=[pending.id])
        assert msg.body == ''
        listed = list_messages(ch.id, viewer_user_id=member.id)
        row = next(m for m in listed if m['id'] == msg.id)
        assert row['attachments'][0]['mime'] == 'text/plain'


def test_child_cannot_upload(app, db_session, child, member, tmp_path, monkeypatch):
    with app.app_context():
        monkeypatch.setitem(app.config, 'UPLOAD_FOLDER', str(tmp_path))
        ch = create_household_channel(
            member,
            name='Kid ACL',
            slug=f'kidacl-{uuid4().hex[:8]}',
        )
        with pytest.raises(PermissionError, match='Child'):
            upload_attachment(channel=ch, user=child, file=_png_file())


def test_size_reject(app, db_session, member, tmp_path, monkeypatch):
    with app.app_context():
        monkeypatch.setitem(app.config, 'UPLOAD_FOLDER', str(tmp_path))
        ch = create_household_channel(
            member,
            name='Size room',
            slug=f'size-{uuid4().hex[:8]}',
        )
        huge = FileStorage(
            stream=BytesIO(b'x' * (MAX_ATTACHMENT_BYTES + 1)),
            filename='big.txt',
            content_type='text/plain',
        )
        with pytest.raises(ValueError, match='too large'):
            upload_attachment(channel=ch, user=member, file=huge)


def test_total_chat_attachment_storage_quota_includes_sent_files_and_all_channels(
    app, db_session, member, tmp_path, monkeypatch
):
    with app.app_context():
        monkeypatch.setitem(app.config, 'UPLOAD_FOLDER', str(tmp_path))
        monkeypatch.setitem(app.config, 'CHAT_ATTACHMENT_STORAGE_MAX_BYTES', 8)
        first_channel = create_household_channel(
            member,
            name='Quota room one',
            slug=f'quota1-{uuid4().hex[:8]}',
        )
        second_channel = create_household_channel(
            member,
            name='Quota room two',
            slug=f'quota2-{uuid4().hex[:8]}',
        )

        first = upload_attachment(
            channel=first_channel, user=member, file=_txt_file(content=b'1234')
        )
        post_message(first_channel, member, 'sent', attachment_ids=[first.id])
        second = upload_attachment(
            channel=second_channel, user=member, file=_txt_file(content=b'5678')
        )
        assert second.size_bytes == 4

        with pytest.raises(ValueError, match='storage limit'):
            upload_attachment(
                channel=second_channel, user=member, file=_txt_file(content=b'x')
            )

        assert len(list((tmp_path / 'chat-attachments').iterdir())) == 2


def test_total_chat_attachment_file_quota_includes_orphans_and_bounds_uploads(
    app, db_session, member, tmp_path, monkeypatch
):
    with app.app_context():
        monkeypatch.setitem(app.config, 'UPLOAD_FOLDER', str(tmp_path))
        monkeypatch.setitem(app.config, 'CHAT_ATTACHMENT_STORAGE_MAX_BYTES', 1024)
        monkeypatch.setitem(app.config, 'CHAT_ATTACHMENT_STORAGE_MAX_FILES', 2)
        ch = create_household_channel(
            member,
            name='File quota room',
            slug=f'filequota-{uuid4().hex[:8]}',
        )
        attachment_dir = tmp_path / 'chat-attachments'
        attachment_dir.mkdir()
        # Orphaned files still consume the global file quota.
        (attachment_dir / 'orphan.txt').write_bytes(b'orphan')

        uploaded = upload_attachment(channel=ch, user=member, file=_txt_file())
        assert uploaded.id
        with pytest.raises(ValueError, match='file limit'):
            upload_attachment(channel=ch, user=member, file=_txt_file())


def test_attachment_file_quota_stops_scanning_at_limit(tmp_path, monkeypatch):
    attachment_dir = tmp_path / 'chat-attachments'
    attachment_dir.mkdir()
    for index in range(20):
        (attachment_dir / f'{index}.txt').write_bytes(b'x')

    import oneirodex.utils.chat_attachments as attachments

    original_stat = attachments.os.stat
    scanned = []

    def track_stat(path, *args, **kwargs):
        if str(path).startswith(str(attachment_dir)):
            scanned.append(str(path))
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(attachments.os, 'stat', track_stat)
    with pytest.raises(ValueError, match='file limit'):
        _stored_attachment_bytes(str(attachment_dir), 3)
    assert len(scanned) == 3


def test_unsupported_mime_reject(app, db_session, member, tmp_path, monkeypatch):
    with app.app_context():
        monkeypatch.setitem(app.config, 'UPLOAD_FOLDER', str(tmp_path))
        ch = create_household_channel(
            member,
            name='Mime room',
            slug=f'mime-{uuid4().hex[:8]}',
        )
        exe = FileStorage(
            stream=BytesIO(b'MZ'),
            filename='bad.exe',
            content_type='application/octet-stream',
        )
        with pytest.raises(ValueError, match='Unsupported'):
            upload_attachment(channel=ch, user=member, file=exe)


def test_message_requires_body_or_attachment(app, db_session, member):
    with app.app_context():
        ch = create_household_channel(
            member,
            name='Empty room',
            slug=f'empty-{uuid4().hex[:8]}',
        )
        with pytest.raises(ValueError, match='Message required'):
            post_message(ch, member, '')


class _As:
    """A test client signed in as one user. Flask-Login caches the user in
    ``g``, which outlives a request while the test holds an app context, so
    the cache is dropped before each request made as a different user."""

    def __init__(self, app, user=None):
        self.client = app.test_client()
        if user is not None:
            with self.client.session_transaction() as sess:
                sess['_user_id'] = user.get_id()
                sess['_fresh'] = True

    def get(self, url):
        from flask import g, has_app_context

        if has_app_context():
            g.pop('_login_user', None)
        return self.client.get(url)


def _signed_in(app, user):
    return _As(app, user)


def test_attachments_are_served_only_to_people_who_can_read_the_channel(app, db_session, member, tmp_path, monkeypatch):
    from oneirodex.utils.chat_spaces import create_channel, create_space

    other = _make_user(db_session, role='user', prefix='att_other')
    monkeypatch.setitem(app.config, 'UPLOAD_FOLDER', str(tmp_path))
    with app.app_context():
        space = create_space(name='Private room', created_by_user_id=member.id, visibility='invite')
        ch = create_channel(space=space, name='secret', created_by_user_id=member.id)
        pending = upload_attachment(channel=ch, user=member, file=_png_file())
        post_message(ch, member, 'look', attachment_ids=[pending.id])  # sent: the channel decides now
        url = pending.to_dict()['url']
        file_name = pending.file_name

    owner, outsider = _signed_in(app, member), _signed_in(app, other)
    with owner.get(url) as resp:
        assert resp.status_code == 200 and resp.mimetype == 'image/png'
    with outsider.get(url) as resp:
        assert resp.status_code == 404, 'not in the invite-only space'
    with _As(app).get(url) as resp:
        assert resp.status_code in (302, 401, 404), 'signed-out callers get nothing'
    # The old static address is closed, for every spelling of it.
    for spelling in (f'/static/library/chat-attachments/{file_name}',
                     f'/static//library/chat-attachments/{file_name}',
                     f'/static/LIBRARY/Chat-Attachments/{file_name}'):
        with owner.get(spelling) as resp:
            assert resp.status_code == 404, spelling


def test_invite_only_space_channels_stay_private_through_the_channel_api(app, db_session, member):
    from oneirodex.utils.chat import list_channels_for_user, user_can_access_channel
    from oneirodex.utils.chat_spaces import create_channel, create_space

    other = _make_user(db_session, role='user', prefix='att_other2')
    with app.app_context():
        space = create_space(name='Invite only', created_by_user_id=member.id, visibility='invite')
        ch = create_channel(space=space, name='hidden', created_by_user_id=member.id)
        assert user_can_access_channel(member, ch)
        assert not user_can_access_channel(other, ch)
        assert ch.id not in {c['id'] for c in list_channels_for_user(other)}
        assert ch.id in {c['id'] for c in list_channels_for_user(member)}
        channel_id = ch.id
    with _signed_in(app, other).get(f'/api/chat/channels/{channel_id}/messages') as resp:
        assert resp.status_code == 404
