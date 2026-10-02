"""Member self-service account API — what the account modals talk to.

Avatar, password, invites and the profile summary each had exactly one home: a
server-rendered page you navigated to and came back from. That is the wrong
shape for "change my avatar" — a whole-page trip for a two-field form — so the
member SPA opens them as modals instead, and modals need JSON.

The Jinja pages stay. They are the fallback when the SPA is not running (Big
Picture, the pop-out host, a browser with JS off) and they now share this
module's helpers rather than reimplementing them.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from flask import current_app, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, select

from oneirodex import db
from oneirodex.models import InviteToken, User
from oneirodex.schemas.account import ChangePasswordBody, StockAvatarBody
from oneirodex.utils.api_response import api_error, api_ok
from oneirodex.utils.avatar import (
    STOCK_AVATARS,
    avatar_url,
    save_avatar,
    set_stock_avatar,
)
from oneirodex.utils.public_origin import (
    invite_url as build_invite_url,
    is_local_site_url,
    public_origin,
    site_url_is_configured,
)
from oneirodex.utils.smtp import is_smtp_config_valid
from oneirodex.utils.validation import validate_body

from . import apis_bp

# Matches the copy on the classic invites page. Kept here so the modal can say
# the same thing without the caller hardcoding it; the authoritative value is
# the row's own `expires_at`, which this only describes.
INVITE_TTL_HOURS = 48

MIN_PASSWORD_LENGTH = 8


def _smtp_ready() -> bool:
    """Can this install actually send the invite it just created?

    `routes_login.is_smtp_configured` answers the same question but lives in a
    route module; importing a blueprint module from another blueprint module to
    borrow one predicate is how import cycles start. `is_smtp_config_valid` is
    the utils-layer answer and is stricter (it also checks the sender address
    and the port range), which is the right way to be wrong here: claiming mail
    works when it does not is what hides an invite nobody received.
    """
    try:
        valid, _reason = is_smtp_config_valid()
        return bool(valid)
    except Exception:  # pragma: no cover - settings row missing entirely
        return False


def _site_url() -> str:
    return public_origin()


def _invite_url(token: str) -> str:
    return build_invite_url(token)


def _invites_unlimited(user) -> bool:
    """Main admins are not invite-metered."""
    return getattr(user, 'role', None) == 'admin'


def _is_expired(expires) -> bool:
    """Compare against an aware `now`.

    Postgres hands these back naive when the column is `timestamp without time
    zone`, and comparing naive to aware raises rather than answering — which
    would turn "list my invites" into a 500 the moment one existed.
    """
    if not expires:
        return False
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires < datetime.now(timezone.utc)


def _unused_invite_count(user) -> int:
    return db.session.scalar(
        select(func.count(InviteToken.id)).filter_by(
            creator_user_id=user.user_id, used=False,
        )
    ) or 0


def _invite_row(invite) -> dict:
    created = getattr(invite, 'created_at', None)
    # `expires_at` is a real column with its own default — read it rather than
    # deriving it, or the modal and the redeem check can disagree about whether
    # a link is still good.
    expires = getattr(invite, 'expires_at', None)
    return {
        'token': invite.token,
        'email': invite.recipient_email or None,
        'url': _invite_url(invite.token),
        'created_at': created.isoformat() if created else None,
        'expires_at': expires.isoformat() if expires else None,
        'expired': _is_expired(expires),
    }


@apis_bp.route('/account/summary', methods=['GET'])
@login_required
def account_summary():
    """Everything the account modals show in their headers, in one call."""
    unused = _unused_invite_count(current_user)
    unlimited = _invites_unlimited(current_user)
    return api_ok({
        'username': current_user.name,
        'email': current_user.email,
        'role': current_user.role,
        'avatar_path': current_user.avatarpath,
        # Resolved alongside the raw path rather than instead of it: the path is
        # the identity the client sends back, the URL is what it renders. Shipped
        # avatars resolve into the active theme, so the picker and the account
        # header show the same recoloured art the rail does — see avatar_url.
        'avatar_url': avatar_url(current_user.avatarpath),
        'stock_avatars': [
            {**entry, 'url': avatar_url(entry['path'])}
            for entry in STOCK_AVATARS
        ],
        'invite_quota': None if unlimited else current_user.invite_quota,
        'invites_used': unused,
        'invites_remaining': None if unlimited else max(0, (current_user.invite_quota or 0) - unused),
        'invites_unlimited': unlimited,
        'smtp_enabled': _smtp_ready(),
    })


@apis_bp.route('/account/avatar', methods=['POST'])
@login_required
def account_avatar():
    """Multipart, not JSON — this one carries a file."""
    file = request.files.get('avatar')
    if not file:
        return api_error('Choose an image first.', code='bad_request')

    path, error = save_avatar(file, current_user, current_app)
    if error:
        return api_error(error, code='unprocessable')

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.warning('avatar commit failed: %s', exc)
        return api_error("Couldn't save that avatar. Try a different image.", code='internal')

    # Cache-busted so the rail and the modal both show the new image
    # immediately; the filename is a fresh uuid, so this is belt and braces for
    # any proxy holding the old bytes under the old name.
    return api_ok({
        'avatar_path': path,
        'avatar_url': avatar_url(path),
    })


@apis_bp.route('/account/avatar/stock', methods=['POST'])
@login_required
@validate_body(StockAvatarBody)
def account_stock_avatar(body: StockAvatarBody):
    """Pick one of the avatars Oneirodex ships.

    Takes an **id**, never a path. A path parameter here would be an
    arbitrary-file setter aimed at the static tree, and the whole point of a
    fixed set is that the server already knows every legal answer.
    """
    path, error = set_stock_avatar(body.id, current_user, current_app)
    if error:
        return api_error(error, code='bad_request')

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.warning('stock avatar commit failed: %s', exc)
        return api_error("Couldn't save that avatar. Try a different image.", code='internal')

    return api_ok({
        'avatar_path': path,
        'avatar_url': avatar_url(path),
    })


@apis_bp.route('/account/password', methods=['POST'])
@login_required
@validate_body(ChangePasswordBody)
def account_password(body: ChangePasswordBody):
    current = body.current_password
    new_password = body.new_password
    confirm = body.confirm_password

    user = db.session.get(User, current_user.id)
    if user is None:
        return api_error('Account not found.', code='not_found')

    # The classic page never asked for the current password, because getting to
    # it required an authenticated session. A modal opens from anywhere in the
    # app, including a session someone walked away from, so it does ask.
    if not user.check_password(current):
        return api_error('Current password is incorrect.', code='unauthorized')

    if len(new_password) < MIN_PASSWORD_LENGTH:
        return api_error(
            f'New password must be at least {MIN_PASSWORD_LENGTH} characters.',
            code='unprocessable',
        )
    if new_password != confirm:
        return api_error("Those two passwords don't match.", code='unprocessable')
    if new_password == current:
        return api_error("Pick a password you're not already using.", code='unprocessable')

    try:
        user.set_password(new_password)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.warning('password change failed for user %s: %s', user.id, exc)
        return api_error('Could not change your password.', code='internal')

    # The new password ends every other session (User.get_id); keep this one.
    from flask_login import login_user

    login_user(user, remember=True)
    return api_ok({'changed': True})


@apis_bp.route('/account/invites', methods=['GET'])
@login_required
def account_invites():
    invites = db.session.execute(
        select(InviteToken).filter_by(creator_user_id=current_user.user_id, used=False)
    ).scalars().all()
    unlimited = _invites_unlimited(current_user)
    return api_ok({
        'invites': [_invite_row(invite) for invite in invites],
        'quota': None if unlimited else current_user.invite_quota,
        'remaining': None if unlimited else max(0, (current_user.invite_quota or 0) - len(invites)),
        'unlimited': unlimited,
        'smtp_enabled': _smtp_ready(),
        'ttl_hours': INVITE_TTL_HOURS,
        'site_url_configured': site_url_is_configured() or not is_local_site_url(_site_url()),
    })


@apis_bp.route('/account/invites', methods=['POST'])
@login_required
def create_account_invite():
    """Create an invite. The email address is optional.

    Requiring one was the reason a household with no SMTP server could not
    invite anybody: the form demanded an address, then handed it to a mailer
    that was never configured, and the invite link — which works perfectly well
    pasted into a chat window — was never shown to anyone. With no address the
    invite is created and its URL returned for the inviter to pass on directly.
    """
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip() or None

    unused = _unused_invite_count(current_user)
    if not _invites_unlimited(current_user) and (current_user.invite_quota or 0) <= unused:
        return api_error("You're out of invites. An admin can raise your limit.", code='forbidden')

    token = str(uuid.uuid4())
    invite = InviteToken(
        token=token,
        creator_user_id=current_user.user_id,
        recipient_email=email,
    )
    db.session.add(invite)
    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.warning('invite create failed: %s', exc)
        return api_error('Could not create the invite.', code='internal')

    emailed = False
    if email and _smtp_ready():
        # A mail failure must not lose the invite: it already exists and its
        # URL is in the response, so the inviter can still pass the link on.
        try:
            from oneirodex.utils.smtp import send_invite_email

            send_invite_email(email, _invite_url(token))
            emailed = True
        except Exception as exc:
            current_app.logger.warning('invite email failed: %s', exc)

    unlimited = _invites_unlimited(current_user)
    return api_ok({
        'invite': _invite_row(invite),
        'emailed': emailed,
        'remaining': None if unlimited else max(0, (current_user.invite_quota or 0) - (unused + 1)),
        'unlimited': unlimited,
    }, status=201)


@apis_bp.route('/account/invites/<token>', methods=['DELETE'])
@login_required
def delete_account_invite(token):
    invite = db.session.execute(
        select(InviteToken).filter_by(token=token, creator_user_id=current_user.user_id)
    ).scalar_one_or_none()
    if not invite:
        return api_error('Invite not found.', code='not_found')

    db.session.delete(invite)
    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.warning('invite delete failed: %s', exc)
        return api_error('Could not revoke the invite.', code='internal')

    return api_ok({
        'revoked': token,
        'remaining': max(0, (current_user.invite_quota or 0) - _unused_invite_count(current_user)),
    })
