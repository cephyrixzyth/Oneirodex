"""Member self-service account API — what the account modals talk to.

Covers the parts that were not previously reachable as JSON at all: the
summary, the password change (which now asks for the current password), and
invites created without an email address.
"""

import io
from uuid import uuid4

import pytest

from oneirodex.models import InviteToken, User
from oneirodex.utils.accounts import (
    display_email,
    is_placeholder_email,
    placeholder_email,
)
from oneirodex.utils.avatar import (
    DEFAULT_AVATAR,
    LEGACY_DEFAULT_AVATAR,
    STOCK_AVATARS,
    is_shipped_avatar,
    thumbnail_for,
)


@pytest.fixture
def member(db_session):
    suffix = str(uuid4())[:8]
    user = User(
        name=f'member_{suffix}',
        email=f'member_{suffix}@example.com',
        password_hash='placeholder',
        role='user',
        user_id=str(uuid4()),
        avatarpath=DEFAULT_AVATAR,
        invite_quota=3,
    )
    user.set_password('correct horse battery')
    db_session.add(user)
    db_session.commit()
    return user


def login(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
        session['_fresh'] = True


class TestAccountSummary:
    def test_requires_login(self, client):
        assert client.get('/api/account/summary').status_code == 302

    def test_reports_identity_and_invite_budget(self, client, member):
        login(client, member)
        body = client.get('/api/account/summary').get_json()

        assert body['ok'] is True
        assert body['username'] == member.name
        assert body['role'] == 'user'
        assert body['invite_quota'] == 3
        assert body['invites_used'] == 0
        assert body['invites_remaining'] == 3

    def test_remaining_drops_as_invites_are_opened(self, client, db_session, member):
        db_session.add(InviteToken(token=str(uuid4()), creator_user_id=member.user_id))
        db_session.commit()
        login(client, member)

        body = client.get('/api/account/summary').get_json()
        assert (body['invites_used'], body['invites_remaining']) == (1, 2)


class TestPasswordChange:
    @pytest.mark.parametrize('without_content_length', [False, True])
    def test_oversized_password_body_is_refused_before_json_parse(
        self, client, member, without_content_length
    ):
        from oneirodex.routes_apis.account import PASSWORD_CHANGE_BODY_MAX_BYTES

        login(client, member)
        body = b'{"padding":"' + b'x' * PASSWORD_CHANGE_BODY_MAX_BYTES + b'"}'
        response = client.post(
            '/api/account/password', data=body, content_type='application/json',
        ) if not without_content_length else None
        if without_content_length:
            from werkzeug.test import EnvironBuilder

            environ = EnvironBuilder(
                method='POST', path='/api/account/password',
                input_stream=io.BytesIO(body), content_type='application/json',
            ).get_environ()
            environ.pop('CONTENT_LENGTH', None)
            environ['wsgi.input_terminated'] = True
            response = client.open(environ)

        assert response.status_code == 413
        assert response.get_json()['error_code'] == 'payload_too_large'
        assert member.check_password('correct horse battery')

    def test_wrong_current_password_is_refused(self, client, member):
        login(client, member)
        response = client.post('/api/account/password', json={
            'current_password': 'not it',
            'new_password': 'a brand new one',
            'confirm_password': 'a brand new one',
        })

        assert response.status_code == 401
        assert response.get_json()['error_code'] == 'unauthorized'
        # And the old password still works.
        assert member.check_password('correct horse battery')

    def test_mismatched_confirmation_is_refused(self, client, member):
        login(client, member)
        response = client.post('/api/account/password', json={
            'current_password': 'correct horse battery',
            'new_password': 'a brand new one',
            'confirm_password': 'a different one',
        })

        assert response.status_code == 422
        assert "don't match" in response.get_json()['error']

    def test_short_password_is_refused(self, client, member):
        login(client, member)
        response = client.post('/api/account/password', json={
            'current_password': 'correct horse battery',
            'new_password': 'short',
            'confirm_password': 'short',
        })

        assert response.status_code == 422
        assert member.check_password('correct horse battery')

    def test_reusing_the_current_password_is_refused(self, client, member):
        login(client, member)
        response = client.post('/api/account/password', json={
            'current_password': 'correct horse battery',
            'new_password': 'correct horse battery',
            'confirm_password': 'correct horse battery',
        })

        assert response.status_code == 422

    def test_valid_change_takes_effect(self, client, db_session, member):
        login(client, member)
        response = client.post('/api/account/password', json={
            'current_password': 'correct horse battery',
            'new_password': 'a brand new one',
            'confirm_password': 'a brand new one',
        })

        assert response.status_code == 200
        db_session.refresh(member)
        assert member.check_password('a brand new one')
        assert not member.check_password('correct horse battery')

    def test_missing_fields_are_unprocessable(self, client, member):
        login(client, member)
        response = client.post('/api/account/password', json={})
        assert response.status_code == 422
        body = response.get_json()
        assert body['error_code'] == 'unprocessable'
        assert 'current_password' in body['detail']
        assert 'new_password' in body['detail']
        assert 'confirm_password' in body['detail']


class TestInvites:
    def test_invite_without_an_email_is_created_and_returns_its_link(self, client, member):
        login(client, member)
        response = client.post('/api/account/invites', json={})

        assert response.status_code == 201
        invite = response.get_json()['invite']
        assert invite['email'] is None
        assert invite['token'] in invite['url']
        assert '/register?token=' in invite['url']

    def test_invite_with_an_email_records_it(self, client, member):
        login(client, member)
        body = client.post(
            '/api/account/invites', json={'email': 'friend@example.com'},
        ).get_json()

        assert body['invite']['email'] == 'friend@example.com'
        # No SMTP configured in tests, so nothing was sent — and the response
        # says so rather than implying delivery.
        assert body['emailed'] is False

    def test_quota_is_enforced(self, client, db_session, member):
        member.invite_quota = 1
        db_session.commit()
        login(client, member)

        assert client.post('/api/account/invites', json={}).status_code == 201
        refused = client.post('/api/account/invites', json={})
        assert refused.status_code == 403
        assert refused.get_json()['error_code'] == 'forbidden'

    def test_listing_returns_open_invites_only(self, client, db_session, member):
        db_session.add(InviteToken(token=str(uuid4()), creator_user_id=member.user_id))
        db_session.add(
            InviteToken(token=str(uuid4()), creator_user_id=member.user_id, used=True),
        )
        db_session.commit()
        login(client, member)

        body = client.get('/api/account/invites').get_json()
        assert len(body['invites']) == 1
        assert body['remaining'] == 2

    def test_revoking_frees_the_slot(self, client, member):
        login(client, member)
        token = client.post('/api/account/invites', json={}).get_json()['invite']['token']

        response = client.delete(f'/api/account/invites/{token}')
        assert response.status_code == 200
        assert response.get_json()['remaining'] == 3

    def test_cannot_revoke_someone_elses_invite(self, client, db_session, member):
        other = User(
            name=f'other_{str(uuid4())[:8]}',
            email=f'other_{str(uuid4())[:8]}@example.com',
            password_hash='placeholder',
            role='user',
            user_id=str(uuid4()),
            invite_quota=1,
        )
        other.set_password('another password')
        db_session.add(other)
        token = str(uuid4())
        db_session.add(InviteToken(token=token, creator_user_id=other.user_id))
        db_session.commit()

        login(client, member)
        assert client.delete(f'/api/account/invites/{token}').status_code == 404


class TestAvatarUpload:
    def test_missing_file_is_a_bad_request(self, client, member):
        login(client, member)
        response = client.post('/api/account/avatar', data={})
        assert response.status_code == 400

    def test_non_image_is_refused_without_changing_the_avatar(self, client, member):
        login(client, member)
        response = client.post(
            '/api/account/avatar',
            data={'avatar': (io.BytesIO(b'not an image'), 'payload.txt')},
            content_type='multipart/form-data',
        )

        assert response.status_code == 422
        assert member.avatarpath == DEFAULT_AVATAR


class TestStockAvatars:
    """The six shipped picks, so having no picture to hand is not a dead end."""

    def test_summary_offers_the_full_set_with_urls(self, client, member):
        login(client, member)
        body = client.get('/api/account/summary').get_json()

        assert len(body['stock_avatars']) == 6
        assert {entry['id'] for entry in body['stock_avatars']} == {
            entry['id'] for entry in STOCK_AVATARS
        }
        for entry in body['stock_avatars']:
            # `path` is the identity the client sends back; `url` is what it
            # renders, and for shipped avatars that resolves into the *active
            # theme* so the art recolours with the preset (see avatar_url).
            # Asserting url.endswith(path) predated theming and had been failing
            # ever since — the file is not in CI's core list, so nothing caught it.
            filename = entry['path'].rsplit('/', 1)[-1]
            assert entry['url'].endswith(filename)
            assert entry['url'].startswith('/static/')
            assert entry['label']

    def test_choosing_one_sets_it(self, client, db_session, member):
        login(client, member)
        response = client.post('/api/account/avatar/stock', json={'id': 'arcade'})

        assert response.status_code == 200
        db_session.refresh(member)
        assert member.avatarpath == 'newstyle/avatars/arcade.svg'
        assert response.get_json()['avatar_path'] == member.avatarpath

    def test_an_unknown_id_is_refused(self, client, member):
        login(client, member)
        response = client.post('/api/account/avatar/stock', json={'id': 'nope'})

        assert response.status_code == 400
        assert member.avatarpath == DEFAULT_AVATAR

    def test_missing_id_is_unprocessable(self, client, member):
        login(client, member)
        response = client.post('/api/account/avatar/stock', json={})
        assert response.status_code == 422
        body = response.get_json()
        assert body['error_code'] == 'unprocessable'
        assert 'id' in body['detail']

    def test_a_path_is_not_an_id(self, client, member):
        """The set is closed on purpose — a path here would set any static file."""
        login(client, member)
        response = client.post(
            '/api/account/avatar/stock',
            json={'id': '../../../etc/passwd'},
        )

        assert response.status_code == 400
        assert member.avatarpath == DEFAULT_AVATAR

    def test_every_shipped_file_exists_on_disk(self):
        from pathlib import Path

        static_root = Path(__file__).resolve().parents[1] / 'oneirodex' / 'static'
        for entry in STOCK_AVATARS:
            assert (static_root / entry['path']).is_file(), entry['id']
        assert (static_root / DEFAULT_AVATAR).is_file()

    def test_shipped_avatars_are_never_deleted_as_stale(self):
        assert is_shipped_avatar(DEFAULT_AVATAR)
        assert is_shipped_avatar(LEGACY_DEFAULT_AVATAR)
        assert all(is_shipped_avatar(entry['path']) for entry in STOCK_AVATARS)
        assert not is_shipped_avatar('library/images/avatars_users/abc.png')

    def test_shipped_avatars_are_their_own_thumbnail(self):
        # They are SVGs: no `_thumbnail` file was ever written for them, and
        # deriving one produced a broken image beside "Thumbnail preview".
        assert thumbnail_for(DEFAULT_AVATAR) == DEFAULT_AVATAR
        assert thumbnail_for(STOCK_AVATARS[0]['path']) == STOCK_AVATARS[0]['path']

    def test_uploads_still_get_a_derived_thumbnail(self):
        assert thumbnail_for('library/images/avatars_users/abc.png') == (
            'library/images/avatars_users/abc_thumbnail.png'
        )


class TestPlaceholderEmails:
    """Accounts an admin creates with no address at all."""

    def test_generated_address_is_unroutable_and_unique(self):
        first = placeholder_email('Living Room')
        second = placeholder_email('Living Room')

        assert first != second
        assert first.endswith('@no-email.invalid')
        assert is_placeholder_email(first)

    def test_a_real_address_is_not_a_placeholder(self):
        assert not is_placeholder_email('someone@example.com')
        assert display_email('someone@example.com') == 'someone@example.com'

    def test_placeholders_are_never_displayed(self):
        assert display_email(placeholder_email('kid')) is None
        assert display_email(None) is None

    def test_blank_counts_as_no_address(self):
        assert is_placeholder_email('')
        assert is_placeholder_email(None)
