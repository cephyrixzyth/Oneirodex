"""Delegated library tokens must not inherit private social/account reads."""
from io import BytesIO
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from werkzeug.datastructures import FileStorage

from oneirodex.models import (
    Game,
    DownloadRequest,
    InviteToken,
    Library,
    SupportTicket,
    User,
    UserGameProgress,
    UserLibraryAccess,
)
from oneirodex.platform import LibraryPlatform
from oneirodex.utils.api_tokens import generate_api_token, verify_bearer_token
from oneirodex.utils.chat import open_or_create_dm, post_message
from oneirodex.utils.chat_attachments import upload_attachment


@pytest.fixture
def private_data(app, db_session, configured_install, tmp_path, monkeypatch):
    monkeypatch.setitem(app.config, 'UPLOAD_FOLDER', str(tmp_path))
    users = []
    for label in ('owner', 'peer', 'outsider'):
        uid = uuid4().hex
        user = User(name=f'{label}_{uid[:8]}', email=f'{uid}@example.com',
                    user_id=uid, role='user', state=True, invite_quota=3,
                    password_hash='unused-test-password-hash')
        db_session.add(user)
        users.append(user)
    db_session.commit()
    owner, peer, outsider = users
    channel = open_or_create_dm(owner, peer)
    attachment = upload_attachment(channel=channel, user=peer, file=FileStorage(
        stream=BytesIO(b'private attachment'), filename='private.txt', content_type='text/plain'))
    post_message(channel, peer, 'private DM secret', attachment_ids=[attachment.id])
    invite = InviteToken(token=str(uuid4()), creator_user_id=owner.user_id)
    db_session.add(invite)
    db_session.commit()
    return owner, outsider, channel, attachment, invite


def bearer(user, scopes):
    row, raw = generate_api_token(user, 'scope regression', scopes)
    assert row.scopes == scopes
    return {'Authorization': f'Bearer {raw}'}


def social_paths(channel, attachment):
    return ['/api/chat/channels', f'/api/chat/channels/{channel.id}/messages',
            f'/api/chat/attachments/{attachment.file_name}', '/api/chat/search?q=private',
            '/api/chat/emoji', '/api/notifications', '/api/chat/spaces',
            '/api/chat/spaces/999/members', '/api/chat/spaces/999/voice/999/room']


def test_library_token_cannot_read_private_social_data(client, private_data):
    owner, _, channel, attachment, _ = private_data
    headers = bearer(owner, ['read:library'])
    for path in social_paths(channel, attachment):
        response = client.get(path, headers=headers)
        assert response.status_code == 403, path
        assert response.get_json()['error_code'] == 'forbidden'
        assert b'private DM secret' not in response.data


def test_delegated_tokens_cannot_read_account_summary_or_support_reports(
    client, db_session, private_data,
):
    owner, _, _, _, _ = private_data
    ticket = SupportTicket(
        user_id=owner.id,
        title='Private report',
        body='private support details',
        logs='private diagnostic output',
    )
    db_session.add(ticket)
    db_session.commit()

    for scopes in (['read:library'], ['read:social']):
        headers = bearer(owner, scopes)
        paths = [
            '/api/account/summary',
            '/api/support/tickets',
            f'/api/support/tickets/{ticket.id}',
        ]
        for path in paths:
            response = client.get(path, headers=headers)
            assert response.status_code == 403, path
            assert response.get_json()['error_code'] == 'forbidden'
            assert b'private support details' not in response.data
            assert b'private diagnostic output' not in response.data


def test_library_token_cannot_read_social_presence_profiles_or_activity(client, private_data):
    owner, _, _, _, _ = private_data
    headers = bearer(owner, ['read:library'])
    paths = [
        ('GET', '/api/social/status'),
        ('GET', '/api/social/friends'),
        ('POST', '/api/social/friends'),
        ('POST', '/api/social/friends/999/reject'),
        ('POST', '/api/social/friends/999/block'),
        ('POST', '/api/social/friends/999/accept'),
        ('DELETE', '/api/social/friends/999'),
        ('GET', f'/api/users/{owner.id}/profile'),
        ('GET', f'/api/users/{owner.id}/compare/{owner.id}'),
        ('GET', '/api/activity'),
        ('GET', '/api/activity/stream'),
    ]
    for method, path in paths:
        response = client.open(path, method=method, headers=headers, json={})
        assert response.status_code == 403, (method, path)


def test_child_profile_total_excludes_games_outside_their_library_allowlist(
    client, db_session, private_data,
):
    owner, _, _, _, _ = private_data
    suffix = uuid4().hex[:8]
    child = User(
        name=f'profile_child_{suffix}',
        email=f'profile_child_{suffix}@example.com',
        user_id=uuid4().hex,
        role='child',
        state=True,
        password_hash='unused-test-password-hash',
    )
    visible_library = Library(
        name=f'Visible {suffix}', platform=LibraryPlatform.PCWIN,
    )
    hidden_library = Library(
        name=f'Hidden {suffix}', platform=LibraryPlatform.PCWIN,
    )
    db_session.add_all([child, visible_library, hidden_library])
    db_session.flush()
    visible_game = Game(
        uuid=str(uuid4()), name='Visible profile game', library_uuid=visible_library.uuid,
    )
    hidden_game = Game(
        uuid=str(uuid4()), name='Hidden profile game', library_uuid=hidden_library.uuid,
    )
    db_session.add_all([visible_game, hidden_game])
    db_session.add(UserLibraryAccess(user_id=child.id, library_uuid=visible_library.uuid))
    now = datetime.now(timezone.utc)
    db_session.add_all([
        UserGameProgress(
            user_id=owner.id, game_uuid=visible_game.uuid,
            total_seconds=17, last_played_at=now,
        ),
        UserGameProgress(
            user_id=owner.id, game_uuid=hidden_game.uuid,
            total_seconds=100, last_played_at=now,
        ),
    ])
    db_session.commit()
    headers = bearer(child, ['read:social'])

    response = client.get(f'/api/users/{owner.id}/profile', headers=headers)

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['total_seconds'] == 17
    assert [game['game_uuid'] for game in payload['recent_games']] == [visible_game.uuid]


def test_child_playtime_summary_hides_games_outside_library_allowlist(
    client, db_session,
):
    suffix = uuid4().hex[:8]
    child = User(
        name=f'playtime_child_{suffix}', email=f'{suffix}@example.com',
        user_id=uuid4().hex, role='child', state=True,
        password_hash='unused-test-password-hash',
    )
    visible_library = Library(name=f'Playtime visible {suffix}', platform=LibraryPlatform.PCWIN)
    hidden_library = Library(name=f'Playtime hidden {suffix}', platform=LibraryPlatform.PCWIN)
    db_session.add_all([child, visible_library, hidden_library])
    db_session.flush()
    visible_game = Game(
        uuid=str(uuid4()), name='Visible playtime game', library_uuid=visible_library.uuid,
    )
    hidden_game = Game(
        uuid=str(uuid4()), name='Hidden playtime game', library_uuid=hidden_library.uuid,
    )
    db_session.add_all([visible_game, hidden_game])
    db_session.add(UserLibraryAccess(user_id=child.id, library_uuid=visible_library.uuid))
    now = datetime.now(timezone.utc)
    db_session.add_all([
        UserGameProgress(user_id=child.id, game_uuid=visible_game.uuid,
                         total_seconds=23, last_played_at=now),
        UserGameProgress(user_id=child.id, game_uuid=hidden_game.uuid,
                         total_seconds=400, last_played_at=now),
    ])
    db_session.commit()

    response = client.get('/api/playtime/me', headers=bearer(child, ['read:social']))

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['total_seconds'] == 23
    assert [game['game_uuid'] for game in payload['games']] == [visible_game.uuid]


def test_child_download_history_hides_games_outside_library_allowlist(
    client, db_session,
):
    suffix = uuid4().hex[:8]
    child = User(
        name=f'download_child_{suffix}', email=f'{suffix}@example.com',
        user_id=uuid4().hex, role='child', state=True,
        password_hash='unused-test-password-hash',
    )
    visible_library = Library(name=f'Download visible {suffix}', platform=LibraryPlatform.PCWIN)
    hidden_library = Library(name=f'Download hidden {suffix}', platform=LibraryPlatform.PCWIN)
    db_session.add_all([child, visible_library, hidden_library])
    db_session.flush()
    visible_game = Game(
        uuid=str(uuid4()), name='Visible download game', library_uuid=visible_library.uuid,
    )
    hidden_game = Game(
        uuid=str(uuid4()), name='Hidden download game', library_uuid=hidden_library.uuid,
    )
    db_session.add_all([visible_game, hidden_game])
    db_session.add(UserLibraryAccess(user_id=child.id, library_uuid=visible_library.uuid))
    db_session.add_all([
        DownloadRequest(user_id=child.id, game_uuid=visible_game.uuid, status='available',
                        zip_file_path='/downloads/visible.zip'),
        DownloadRequest(user_id=child.id, game_uuid=hidden_game.uuid, status='available',
                        zip_file_path='/downloads/hidden.zip'),
    ])
    db_session.commit()

    response = client.get('/api/my_downloads', headers=bearer(child, ['read:social']))

    assert response.status_code == 200
    payload = response.get_json()
    assert len(payload) == 1
    assert payload[0]['game_name'] == 'Visible download game'
    assert payload[0]['file_name'] == 'visible.zip'


def test_social_token_can_read_its_social_surfaces(client, private_data):
    owner, _, _, _, _ = private_data
    headers = bearer(owner, ['read:social'])
    for path in ('/api/social/status', '/api/social/friends',
                 f'/api/users/{owner.id}/profile',
                 f'/api/users/{owner.id}/compare/{owner.id}', '/api/activity'):
        assert client.get(path, headers=headers).status_code == 200, path


def test_social_token_cannot_read_library_save_bytes(client, private_data):
    owner, _, _, _, _ = private_data
    headers = bearer(owner, ['read:social'])
    for path in ('/api/games/missing-game/saves',
                 '/api/games/missing-game/saves/slot1'):
        response = client.get(path, headers=headers)
        assert response.status_code == 403, path
        assert response.get_json()['error_code'] == 'forbidden'
    for method, path in (('POST', '/api/games/missing-game/saves'),
                         ('DELETE', '/api/games/missing-game/saves/slot1')):
        response = client.open(path, method=method, headers=headers)
        assert response.status_code == 403, (method, path)


def test_read_social_token_cannot_mutate_social(client, private_data):
    owner, outsider, channel, _, _ = private_data
    read_headers = bearer(owner, ['read:social'])
    requests = [
        ('POST', f'/api/chat/channels/{channel.id}/messages', {'body': 'scope check'}),
        ('POST', '/api/social/friends', {'user_id': outsider.id}),
        ('POST', '/api/notifications/read', {'all': True}),
        ('POST', '/api/notifications/preferences', {'share_activity': False}),
    ]
    for method, path, payload in requests:
        response = client.open(path, method=method, headers=read_headers, json=payload)
        assert response.status_code == 403, path


def test_write_social_token_can_mutate_social(client, private_data):
    owner, outsider, channel, _, _ = private_data
    headers = bearer(owner, ['read:social', 'write:social'])
    _, token = verify_bearer_token(headers['Authorization'].split(' ', 1)[1])
    assert token is not None and token.has_scope('write:social')
    requests = [
        ('POST', f'/api/chat/channels/{channel.id}/messages', {'body': 'scope check'}),
        ('POST', '/api/social/friends', {'user_id': outsider.id}),
        ('POST', '/api/notifications/read', {'all': True}),
        ('POST', '/api/notifications/preferences', {'share_activity': False}),
    ]
    for method, path, payload in requests:
        response = client.open(path, method=method, headers=headers, json=payload)
        assert response.status_code in (200, 201), path


def test_social_token_preserves_owner_access(client, private_data):
    owner, _, channel, attachment, _ = private_data
    headers = bearer(owner, ['read:social'])
    for path in social_paths(channel, attachment)[:7]:
        with client.get(path, headers=headers) as response:
            assert response.status_code == 200, path
    assert b'private DM secret' in client.get('/api/notifications', headers=headers).data


def test_social_scope_does_not_bypass_dm_membership(client, private_data):
    _, outsider, channel, attachment, _ = private_data
    outsider_headers = bearer(outsider, ['read:social'])
    for path in (f'/api/chat/channels/{channel.id}/messages',
                 f'/api/chat/attachments/{attachment.file_name}'):
        assert client.get(path, headers=outsider_headers).status_code == 404


@pytest.mark.parametrize('scopes', [['read:library'], ['read:social']])
def test_invites_require_session_for_every_method(client, private_data, scopes):
    owner, _, _, _, invite = private_data
    headers = bearer(owner, scopes)
    for method, path in [('GET', '/api/account/invites'), ('POST', '/api/account/invites'),
                         ('DELETE', f'/api/account/invites/{invite.token}'),
                         ('GET', '/user/invites'), ('POST', '/user/invites'),
                         ('POST', f'/delete_invite/{invite.token}')]:
        response = client.open(path, method=method, headers=headers, json={})
        assert response.status_code == 403, (method, path)
        assert invite.token.encode() not in response.data


def test_browser_session_still_reads_invites_and_chat(client, private_data):
    owner, _, channel, _, invite = private_data
    with client.session_transaction() as session:
        session['_user_id'] = str(owner.id)
        session['_fresh'] = True
    # Preserve Flask-Login's existing session precedence even with a bearer header.
    headers = bearer(owner, ['read:library'])
    assert invite.token.encode() in client.get('/api/account/invites', headers=headers).data
    assert client.get(f'/api/chat/channels/{channel.id}/messages', headers=headers).status_code == 200
