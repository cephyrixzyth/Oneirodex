"""OIDC account links must be scoped to the identity provider's issuer."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from oneirodex.models import User
from oneirodex.utils.oidc import provision_or_update_user


def _config(issuer):
    return SimpleNamespace(issuer_url=issuer, role_claim='groups', role_map={})


def _user(db_session, *, role='user', email=None, subject=None):
    suffix = uuid4().hex[:10]
    user = User(
        name=f'oidc_{suffix}',
        email=email or f'oidc_{suffix}@example.com',
        role=role,
        state=True,
        is_email_verified=True,
        user_id=str(uuid4()),
        oidc_subject=subject,
    )
    user.set_password('an unrelated local password')
    db_session.add(user)
    db_session.commit()
    return user


def test_same_subject_at_new_issuer_does_not_inherit_old_admin(app, db_session):
    admin = _user(db_session, role='admin')
    admin.oidc_issuer_url = 'https://first-idp.example'
    admin.oidc_subject = 'shared-subject'
    db_session.commit()

    other = provision_or_update_user(db_session, {
        'sub': 'shared-subject', 'email': 'other@example.com',
        'email_verified': True, 'preferred_username': 'other',
    }, _config('https://second-idp.example'))

    assert other.id != admin.id
    assert other.role == 'user'
    assert other.oidc_issuer_url == 'https://second-idp.example'
    db_session.refresh(admin)
    assert admin.role == 'admin' and admin.oidc_issuer_url == 'https://first-idp.example'


def test_subject_whitespace_is_a_distinct_signed_identity(app, db_session):
    admin = _user(db_session, role='admin', subject='subject')
    admin.oidc_issuer_url = 'https://trusted-idp.example'
    db_session.commit()

    other = provision_or_update_user(db_session, {
        'sub': 'subject ', 'preferred_username': 'different',
    }, _config('https://trusted-idp.example'))

    assert other.id != admin.id and other.role == 'user'
    assert other.oidc_subject == 'subject '


def test_new_oidc_name_avoids_case_insensitive_password_login_collision(app, db_session):
    existing = _user(db_session, role='admin')
    existing.name = 'admin'
    db_session.commit()

    newcomer = provision_or_update_user(db_session, {
        'sub': 'different-subject', 'preferred_username': 'Admin',
    }, _config('https://trusted-idp.example'))

    assert newcomer.id != existing.id
    assert newcomer.name.lower() != existing.name.lower()


def test_new_oidc_account_email_verification_requires_provider_or_operator_trust(app, db_session):
    unverified = provision_or_update_user(db_session, {
        'sub': 'unverified-email-subject',
        'email': 'unverified-oidc@example.test',
        'email_verified': False,
        'preferred_username': 'unverified-email',
    }, _config('https://trusted-idp.example'))
    trusted = provision_or_update_user(db_session, {
        'sub': 'operator-trusted-subject',
        'email': 'operator-trusted@example.test',
        'email_verified': False,
        'preferred_username': 'operator-trusted',
    }, _config('https://trusted-idp.example'), trust_provider_email=True)

    assert unverified.is_email_verified is False
    assert trusted.is_email_verified is True


def test_existing_oidc_account_only_verifies_matching_trusted_email(app, db_session):
    local = provision_or_update_user(db_session, {
        'sub': 'email-verification-subject',
        'email': 'first@example.test',
        'email_verified': False,
        'preferred_username': 'email-verification',
    }, _config('https://trusted-idp.example'))
    assert local.is_email_verified is False

    # Repeated sign-in with an unverified assertion does not change state.
    repeated = provision_or_update_user(db_session, {
        'sub': 'email-verification-subject',
        'email': 'first@example.test',
        'email_verified': False,
        'preferred_username': 'email-verification',
    }, _config('https://trusted-idp.example'))
    assert repeated.is_email_verified is False

    # A verified replacement email does not verify the unchanged local email.
    changed = provision_or_update_user(db_session, {
        'sub': 'email-verification-subject',
        'email': 'changed@example.test',
        'email_verified': True,
        'preferred_username': 'email-verification',
    }, _config('https://trusted-idp.example'))
    assert changed.email == 'first@example.test'
    assert changed.is_email_verified is False

    # The identity provider can verify the account after vouching for the same address.
    verified = provision_or_update_user(db_session, {
        'sub': 'email-verification-subject',
        'email': 'first@example.test',
        'email_verified': True,
        'preferred_username': 'email-verification',
    }, _config('https://trusted-idp.example'))
    assert verified.is_email_verified is True


def test_email_conflict_does_not_reveal_local_account_existence(app, db_session):
    email = 'private-conflict@example.test'
    _user(db_session, email=email)

    with pytest.raises(ValueError) as caught:
        provision_or_update_user(db_session, {
            'sub': 'conflicting-oidc-subject',
            'email': email,
            'email_verified': False,
            'preferred_username': 'conflicting-user',
        }, _config('https://trusted-idp.example'))

    assert 'already exists' not in str(caught.value).lower()
    assert email not in str(caught.value).lower()


def test_legacy_subject_collision_without_email_fails_closed(app, db_session):
    legacy = _user(db_session, role='admin', subject='shared-subject')
    with pytest.raises(ValueError, match='older account link with no recorded issuer'):
        provision_or_update_user(db_session, {
            'sub': 'shared-subject', 'preferred_username': legacy.name,
        }, _config('https://new-idp.example'))
    db_session.refresh(legacy)
    assert legacy.oidc_issuer_url is None and legacy.role == 'admin'


def test_verified_email_repairs_legacy_link_to_same_account(app, db_session):
    legacy = _user(db_session, role='admin', subject='old-subject')
    original_email = legacy.email
    linked = provision_or_update_user(db_session, {
        'sub': 'new-subject', 'email': original_email,
        'email_verified': True, 'preferred_username': 'renamed',
    }, _config('https://trusted-idp.example'))

    assert linked.id == legacy.id
    assert linked.oidc_issuer_url == 'https://trusted-idp.example'
    assert linked.oidc_subject == 'new-subject'
    assert linked.email == original_email and linked.role == 'admin'


def test_legacy_placeholder_name_never_proves_new_identity(app, db_session):
    legacy = _user(db_session, email='old@oidc.local', subject='old-subject')
    newcomer = provision_or_update_user(db_session, {
        'sub': 'different-subject', 'preferred_username': legacy.name,
    }, _config('https://new-idp.example'))

    assert newcomer.id != legacy.id
    assert newcomer.name != legacy.name
    assert legacy.oidc_issuer_url is None


def test_verified_email_does_not_rebind_known_other_issuer(app, db_session):
    bound = _user(db_session, subject='old-subject')
    bound.oidc_issuer_url = 'https://first-idp.example'
    db_session.commit()

    with pytest.raises(ValueError) as caught:
        provision_or_update_user(db_session, {
            'sub': 'new-subject', 'email': bound.email,
            'email_verified': True,
        }, _config('https://second-idp.example'))
    assert 'unable to sign in' in str(caught.value).lower()
    assert bound.email.lower() not in str(caught.value).lower()
    db_session.refresh(bound)
    assert bound.oidc_issuer_url == 'https://first-idp.example'


def test_unlocked_oidc_role_sync_cannot_demote_last_active_admin(app, db_session):
    app.config['OIDC_LOCK_ROLES'] = False
    admin = _user(db_session, role='admin', subject='admin-subject')
    admin.oidc_issuer_url = 'https://trusted-idp.example'
    db_session.commit()

    with pytest.raises(ValueError, match='last active administrator'):
        provision_or_update_user(db_session, {
            'sub': 'admin-subject', 'preferred_username': admin.name,
        }, _config('https://trusted-idp.example'))

    db_session.rollback()
    db_session.refresh(admin)
    assert admin.role == 'admin' and admin.state is True


def test_unlocked_oidc_role_sync_can_demote_when_another_admin_remains(app, db_session):
    app.config['OIDC_LOCK_ROLES'] = False
    admin = _user(db_session, role='admin', subject='admin-subject')
    admin.oidc_issuer_url = 'https://trusted-idp.example'
    remaining = _user(db_session, role='admin')
    db_session.commit()

    updated = provision_or_update_user(db_session, {
        'sub': 'admin-subject', 'preferred_username': admin.name,
    }, _config('https://trusted-idp.example'))

    assert updated.id == admin.id and updated.role == 'user'
    db_session.refresh(remaining)
    assert remaining.role == 'admin' and remaining.state is True
