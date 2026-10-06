"""Tests for API tokens, library health, and event bus."""

import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import ApiToken, ClientDevice, Game, Library, User
from oneirodex.platform import LibraryPlatform
from oneirodex.utils.api_tokens import (
    VALID_SCOPES,
    generate_api_token,
    is_raw_api_token,
    revoke_api_token,
    scrub_token_prefix_for_log,
    verify_bearer_token,
    verify_bearer_token_detailed,
)
from oneirodex.utils.event_bus import event_bus
from oneirodex.utils.library_health import score_game, summarize_library_health


@pytest.fixture
def user(db_session):
    uid = str(uuid4())
    u = User(
        name=f'tokenuser_{uid[:8]}',
        email=f'token_{uid[:8]}@example.com',
        role='user',
        user_id=uid,
        state=True,
    )
    u.set_password('password123')
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def admin(db_session):
    uid = str(uuid4())
    u = User(
        name=f'tokenadmin_{uid[:8]}',
        email=f'tokenadmin_{uid[:8]}@example.com',
        role='admin',
        user_id=uid,
        state=True,
    )
    u.set_password('password123')
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def library(db_session):
    lib = Library(name=f'Lib_{uuid4().hex[:6]}', platform=LibraryPlatform.PCWIN)
    db_session.add(lib)
    db_session.commit()
    return lib


def test_generate_and_verify_api_token(db_session, user):
    row, raw = generate_api_token(user, 'CLI', ['read:library'])
    assert row.token_prefix
    assert raw.startswith('gt_')
    assert is_raw_api_token(raw)
    assert 'admin' not in (row.scopes or [])
    # Purity: no whitespace, labels, or trailing junk after the urlsafe secret.
    assert raw == raw.strip()
    assert ' ' not in raw
    assert '\n' not in raw
    assert '…' not in raw

    found_user, found_token = verify_bearer_token(raw)
    assert found_user.id == user.id
    assert found_token.id == row.id

    bad_user, bad_token = verify_bearer_token('gt_deadbeef_not-a-real-secret')
    assert bad_user is None and bad_token is None

    # Truncating at a hyphen inside the secret always fails verification.
    if '-' in raw:
        truncated = raw.rsplit('-', 1)[0]
        trunc_user, trunc_token, trunc_reason = verify_bearer_token_detailed(truncated)
        assert trunc_user is None and trunc_token is None
        assert trunc_reason in {'malformed', 'bad_hash', 'unknown_prefix'}


def test_verify_bearer_token_detailed_reasons(db_session, user):
    row, raw = generate_api_token(user, 'reasons', ['read:library'])
    ok_user, ok_token, ok_reason = verify_bearer_token_detailed(raw)
    assert ok_user.id == user.id
    assert ok_token.id == row.id
    assert ok_reason is None

    _, _, malformed = verify_bearer_token_detailed('not-a-token')
    assert malformed == 'malformed'

    _, _, unknown = verify_bearer_token_detailed('gt_deadbeef_not-a-real-secret')
    assert unknown == 'unknown_prefix'

    # Same prefix, wrong secret → bad_hash (prefix exists from generate).
    prefix = row.token_prefix
    _, _, bad_hash = verify_bearer_token_detailed(f'gt_{prefix}_wrong-secret-value')
    assert bad_hash == 'bad_hash'


def test_scrub_token_prefix_never_includes_secret():
    assert scrub_token_prefix_for_log('gt_ab12cd34_super-secret-value') == 'ab12cd34'
    assert scrub_token_prefix_for_log('Bearer junk') == 'none'
    assert scrub_token_prefix_for_log('gt_onlyprefix') == 'malformed'
    assert 'secret' not in scrub_token_prefix_for_log('gt_ab12cd34_super-secret-value')


def test_bearer_auth_failure_logs_warning_without_secret(client, db_session, user, caplog):
    import logging

    row, raw = generate_api_token(user, 'logcheck', ['read:library'])
    prefix = row.token_prefix
    bad = f'gt_{prefix}_definitely-wrong-secret'

    with caplog.at_level(logging.WARNING, logger='oneirodex.utils.api_tokens'):
        resp = client.get(
            '/api/tokens',
            headers={'Authorization': f'Bearer {bad}'},
        )

    # Unauthenticated after failed Bearer — login_required rejects (401 or redirect).
    assert resp.status_code in {401, 302, 403}
    matching = [r for r in caplog.records if 'api_token_auth_failed' in r.getMessage()]
    assert matching, 'expected api_token_auth_failed WARNING when Bearer verify fails'
    msg = matching[-1].getMessage()
    assert 'reason=bad_hash' in msg
    assert f'prefix={prefix}' in msg
    assert bad not in msg
    assert 'definitely-wrong-secret' not in msg
    assert raw not in msg


def test_create_token_secret_payload_is_pure(client, db_session, user):
    from oneirodex.utils.api_tokens import TOKEN_SCOPE_PRESETS

    # A token may only mint tokens within its own scopes, so the caller holds
    # the companion preset's scopes itself.
    _row, raw = generate_api_token(user, 'auth', list(TOKEN_SCOPE_PRESETS['companion']['scopes']))
    headers = {
        'Authorization': f'Bearer {raw}',
        'Content-Type': 'application/json',
    }
    created = client.post(
        '/api/tokens',
        headers=headers,
        data=json.dumps({'name': 'Pure', 'preset': 'companion'}),
    )
    assert created.status_code == 201
    body = created.get_json()
    secret = body['secret']
    assert is_raw_api_token(secret)
    assert secret == secret.strip()
    assert 'warning' in body
    assert secret not in body['warning']
    assert body['token']['token_prefix'] in secret
    # Round-trip the returned secret.
    found_user, found_token = verify_bearer_token(secret)
    assert found_user.id == user.id
    assert found_token is not None


def test_library_token_cannot_write_client_presence(client, db_session, user):
    _, raw = generate_api_token(user, 'library-only', ['read:library'])

    denied = client.post(
        '/api/client/heartbeat',
        headers={'Authorization': f'Bearer {raw}'},
        json={'device_id': 'narrow-token-device'},
    )

    assert denied.status_code == 403
    assert denied.get_json()['error_code'] == 'forbidden'
    assert db_session.execute(
        select(ClientDevice).filter_by(user_id=user.id, device_id='narrow-token-device')
    ).scalar_one_or_none() is None


def test_presence_scope_can_write_client_presence(client, db_session, user):
    _, presence_raw = generate_api_token(user, 'presence', ['write:presence'])
    allowed = client.post(
        '/api/client/heartbeat',
        headers={'Authorization': f'Bearer {presence_raw}'},
        json={'device_id': 'presence-token-device'},
    )

    assert allowed.status_code == 200
    assert db_session.execute(
        select(ClientDevice).filter_by(user_id=user.id, device_id='presence-token-device')
    ).scalar_one_or_none() is not None


def test_revoke_api_token(db_session, user):
    row, raw = generate_api_token(user, 'temp', ['read:library'])
    assert revoke_api_token(row.id, user_id=user.id) is True
    found_user, _ = verify_bearer_token(raw)
    assert found_user is None


def test_tokens_http_create_list_delete(client, db_session, user):
    row, raw = generate_api_token(user, 'Test', ['read:library'])
    headers = {'Authorization': f'Bearer {raw}'}

    listed = client.get('/api/tokens', headers=headers)
    assert listed.status_code == 200
    body = listed.get_json()
    assert any(t['id'] == row.id for t in body['tokens'])
    assert 'valid_scopes' in body

    created = client.post(
        '/api/tokens',
        headers={**headers, 'Content-Type': 'application/json'},
        data=json.dumps({'name': 'Second', 'scopes': ['read:library']}),
    )
    assert created.status_code == 201
    secret = created.get_json()['secret']
    assert secret.startswith('gt_')

    deleted = client.delete(f'/api/tokens/{row.id}', headers=headers)
    assert deleted.status_code == 200
    assert revoke_api_token(row.id, user_id=user.id) is False


def test_openapi_json_served(client, app):
    resp = client.get('/api/openapi.json')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['openapi'].startswith('3.')
    assert '/api/tokens' in data['paths']


def test_score_game_missing_path(db_session, library):
    game = Game(
        name='Broken Path Game',
        full_disk_path='/definitely/not/a/real/path_' + uuid4().hex,
        library_uuid=library.uuid,
        igdb_id=None,
    )
    db_session.add(game)
    db_session.commit()
    result = score_game(game)
    assert result['score'] < 100
    codes = {i['code'] for i in result['issues']}
    assert 'broken_path' in codes or 'missing_path' in codes
    assert 'missing_igdb' in codes


def test_summarize_library_health(db_session, library):
    game = Game(
        name='Health Summary Game',
        full_disk_path='/tmp/does-not-exist-' + uuid4().hex,
        library_uuid=library.uuid,
        igdb_id=900000000 + (uuid4().int % 100000000),
        summary='A game',
    )
    db_session.add(game)
    db_session.commit()
    summary = summarize_library_health(limit=50, library_uuid=library.uuid)
    assert summary['count'] >= 1
    assert 'average_score' in summary
    assert isinstance(summary['worst'], list)


def test_event_bus_publish_subscribe():
    queue = event_bus.subscribe()
    try:
        event_bus.publish('test', hello=True)
        # Drain until we see our event (history may include older ones)
        found = False
        for _ in range(20):
            try:
                evt = queue.get_nowait()
            except Exception:
                break
            if evt.type == 'test' and evt.payload.get('hello') is True:
                found = True
                break
        assert found
    finally:
        event_bus.unsubscribe(queue)


def test_valid_scopes_frozen():
    assert 'read:library' in VALID_SCOPES
    assert 'read:social' in VALID_SCOPES
    assert 'write:social' in VALID_SCOPES
    assert 'write:presence' in VALID_SCOPES
    assert 'admin' in VALID_SCOPES
