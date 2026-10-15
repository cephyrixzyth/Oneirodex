from oneirodex.utils.api_tokens import require_browser_session
import os
import uuid
from html import escape as html_escape
from flask import Blueprint, redirect, url_for, request, flash, current_app, abort, session, get_flashed_messages
from flask_login import current_user, login_required, login_user, logout_user
from oneirodex import db
from oneirodex.models import User, InviteToken, GlobalSettings, Whitelist
from oneirodex.utils.global_settings import global_settings_row
from oneirodex.utils.public_origin import (
    invite_url as build_invite_url,
    public_origin,
    site_url_is_configured,
)
from oneirodex.forms import LoginForm, RegistrationForm, ResetPasswordRequestForm, InviteForm, UserPasswordForm
from oneirodex.utils.auth import burn_password_check, safe_next_url, sign_in_and_redirect
from oneirodex.utils.accounts import is_placeholder_email
from oneirodex.utils.api_response import api_error, api_ok
from oneirodex.schemas.auth import LoginBody
from oneirodex.schemas.registration import RegistrationBody
from oneirodex.schemas.password_reset import PasswordResetRequestBody, PasswordResetConfirmBody
from oneirodex.utils.validation import validate_body
from oneirodex.utils.smtp import send_email, send_password_reset_email, send_invite_email
from oneirodex.utils.event_logging import log_system_event
from oneirodex.utils.oidc import (
    AUTHLIB_AVAILABLE,
    build_oidc_config,
    format_oidc_callback_error,
    format_oidc_idp_error,
    generate_pkce_pair,
    get_oauth_client,
    init_oauth,
    pop_oidc_session,
    provision_or_update_user,
    register_oidc_provider,
    store_oidc_session,
)
from oneirodex.utils.login_rate_limit import (
    auth_endpoint_key,
    clear_failures,
    client_ip_from_request,
    is_rate_limited,
    login_rate_key,
    record_failure,
)
from datetime import datetime, timedelta, timezone
from sqlalchemy import func, select, update
from urllib.parse import urlparse
from itsdangerous import SignatureExpired, BadSignature
from uuid import uuid4
from sqlalchemy.exc import IntegrityError
from werkzeug.datastructures import MultiDict

from oneirodex.utils.tokens import get_serializer
from oneirodex.utils.rbac import is_admin
from oneirodex.utils.member_auth_spa import render_member_auth_spa


login_bp = Blueprint('login', __name__)

_INVALID_CREDS = 'Invalid username or password. USERNAMES ARE CASE SENSITIVE!'
_REGISTRATION_ACK = 'If the details can be used to create an account, check your email for next steps.'


def _registration_ack():
    """Return the same public response for eligible and ineligible details."""
    return api_ok({
        'requested': True,
        'message': _REGISTRATION_ACK,
        'next_url': url_for('login.login'),
    }, status=202)


def _registration_confirmation_email(confirm_url: str) -> str:
    """Render the confirmation message without loading an application template."""
    safe_url = html_escape(confirm_url, quote=True)
    return f'''<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Confirm your Oneirodex email</title>
<style>body{{background:#f3f4f6;color:#333;font-family:'Courier New',Courier,monospace;padding:20px}}.container{{background:#fff;border:1px solid #ddd;padding:20px;border-radius:10px;max-width:600px;margin:20px auto;box-shadow:0 2px 4px rgba(0,0,0,.1)}}h1{{color:#007bff}}a{{background:#007bff;color:#fff;padding:10px 20px;text-decoration:none;border-radius:5px;font-weight:bold}}p{{margin-bottom:20px}}</style></head>
<body><div class="container"><h2>Ready, Player One!</h2>
<p>You're just one click away from joining the elite ranks at Oneirodex. Grab your controller and get ready to dive into an epic gaming adventure. But first, let's complete your character creation!</p>
<p>Click the power-up below to confirm your email and activate your account. Quick, before the server resets!</p>
<a href="{safe_url}">Confirm Your Email</a>
<p>If you didn't try to create an account with us, just ignore this message and no action is needed. This email will despawn automatically.</p></div></body></html>'''


def _check_login_credentials(username: str, password: str):
    """Apply the shared password, account-state, and throttling checks.

    Returns ``(user, None)`` on success or ``(None, failure)`` where failure
    contains the stable API code and the classic flash category. Both the
    classic form and JSON route use this function to keep auth policy aligned.
    """
    ip = client_ip_from_request(request)
    rate_key = login_rate_key(ip, username)
    if is_rate_limited(rate_key) or is_rate_limited(login_rate_key(ip, None)):
        log_system_event(
            f'Login rate-limited for IP {ip}', event_type='login', event_level='warning'
        )
        return None, {
            'code': 'rate_limited',
            'message': 'Too many login attempts. Please wait a few minutes and try again.',
            'category': 'error',
        }

    user = db.session.execute(select(User).filter_by(name=username)).scalar_one_or_none()
    # Check a real account hash or burn an equivalent hash for an unknown
    # username before returning, so failures do not reveal account existence.
    if user is None:
        burn_password_check(password)
    if user is None or not user.check_password(password):
        if user is None:
            log_system_event(
                f"Failed login for unknown user from {ip}", event_type='login', event_level='warning'
            )
        else:
            log_system_event(
                f"User {username} attempted to log in with invalid credentials.",
                event_type='login', event_level='warning',
            )
        record_failure(rate_key)
        record_failure(login_rate_key(ip, None))
        return None, {'code': 'unauthorized', 'message': _INVALID_CREDS, 'category': 'error'}

    # Admin-created accounts with unroutable placeholder email have no
    # confirmation link to follow, so the real-address verification gate does
    # not apply to them.
    if not user.is_email_verified and not is_placeholder_email(user.email):
        log_system_event(
            f"User {username} attempted to log in with an unverified account.",
            event_type='login', event_level='warning',
        )
        record_failure(rate_key)
        return None, {
            'code': 'forbidden',
            'message': 'Your account is not activated, check your email.',
            'category': 'warning',
        }

    if not user.state:
        log_system_event(
            f"User {username} attempted to log in with a banned account.",
            event_type='login', event_level='warning',
        )
        record_failure(rate_key)
        return None, {
            'code': 'forbidden', 'message': 'Your account has been banned.', 'category': 'error'
        }

    clear_failures(rate_key)
    clear_failures(login_rate_key(ip, None))
    log_system_event(
        f"User {username} logged in successfully.", event_type='login', event_level='information'
    )
    return user, None


@login_bp.route('/demo', methods=['GET'])
def public_demo_login():
    """Issue a member session for the isolated, opt-in public demo instance."""
    if os.getenv('ONEIRODEX_PUBLIC_DEMO', '').strip().lower() not in {'1', 'true', 'yes', 'on'}:
        abort(404)

    demo_user = db.session.execute(
        select(User).filter_by(name='demo-visitor', role='user', state=True)
    ).scalar_one_or_none()
    if demo_user is None:
        abort(503)

    login_user(demo_user, remember=False, fresh=True)
    return redirect(url_for('discover.discover'))

def is_smtp_configured():
    """Check if SMTP settings are properly configured."""
    settings = global_settings_row()
    if not settings:
        return False
    return bool(settings.smtp_server and 
                settings.smtp_port and 
                settings.smtp_username and 
                settings.smtp_password)

@login_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('discover.discover'))

    form = LoginForm()
    if request.method == 'POST' and form.validate_on_submit():
        user, failure = _check_login_credentials(form.username.data, form.password.data)
        if failure:
            flash(failure['message'], failure['category'])
            return redirect(url_for('login.login'))
        return sign_in_and_redirect(user)

    if request.method == 'POST':
        for field, errors in form.errors.items():
            for error in errors:
                flash(f'{getattr(form, field).label.text}: {error}', 'error')
    return render_member_auth_spa()


@login_bp.route('/api/auth/runtime-bootstrap', methods=['GET'])
def auth_runtime_bootstrap():
    """Bootstrap the static auth shell with CSRF and non-secret OIDC labels."""
    from flask_wtf.csrf import generate_csrf

    settings_record = global_settings_row()
    oidc_config = build_oidc_config(settings_record)
    response = current_app.make_response(api_ok({
        'csrf_token': generate_csrf(),
        'oidc_enabled': oidc_config is not None,
        'oidc_display_name': oidc_config.display_name if oidc_config else 'Sign in with SSO',
        'runtime': 'flask-session-compat',
    }))
    response.headers['Cache-Control'] = 'no-store'
    return response


@login_bp.route('/api/auth/login', methods=['POST'])
@validate_body(LoginBody)
def api_login(body: LoginBody):
    """JSON login contract for the React first-run/member shell.

    This deliberately shares the classic route's credential checks and rate
    limiter so the migration cannot create a weaker parallel sign-in path.
    Flask-WTF's app-wide CSRF protection still applies to this session route.
    """
    if current_user.is_authenticated:
        return api_ok({'next_url': safe_next_url(request.args.get('next'))})

    user, failure = _check_login_credentials(body.username, body.password)
    if failure:
        return api_error(failure['message'], code=failure['code'])

    user.lastlogin = datetime.now(timezone.utc)
    db.session.commit()
    login_user(user, remember=True)
    return api_ok({'next_url': safe_next_url(request.args.get('next'))})


@login_bp.route('/api/auth/register', methods=['POST'])
@validate_body(RegistrationBody)
def api_register(body: RegistrationBody):
    """Create an invited or allow-listed member through the JSON contract.

    The existing Flask form and its URL remain available. RegistrationForm
    still owns the established username/email/password rules, and invite use
    is claimed in the same transaction as the new user row.
    """
    invite_token = request.args.get('token')
    if current_user.is_authenticated:
        if invite_token:
            logout_user()
        else:
            return api_error('Sign out before creating an account.', code='conflict')

    invite = None
    if invite_token:
        invite = db.session.execute(
            select(InviteToken).filter_by(token=invite_token, used=False)
        ).scalar_one_or_none()
        now = datetime.now(timezone.utc)
        expiry = invite.expires_at if invite else None
        if expiry is not None and expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if invite is None or expiry is None or expiry < now:
            return api_error('The invite is invalid or has expired.', code='bad_request')

    form = RegistrationForm(
        formdata=MultiDict(body.model_dump()),
        meta={'csrf': False},
    )
    if not form.validate():
        errors = {
            field: [str(message) for message in messages]
            for field, messages in form.errors.items()
        }
        return api_error('Invalid registration details.', code='unprocessable', detail=errors)

    username = form.username.data
    email_address = form.email.data.lower()
    if db.session.execute(
        select(User).filter(func.lower(User.email) == email_address)
    ).scalar_one_or_none():
        return _registration_ack()

    if invite is None:
        whitelisted = db.session.execute(
            select(Whitelist).filter(func.lower(Whitelist.email) == email_address)
        ).scalar_one_or_none()
        if whitelisted is None:
            return _registration_ack()

    existing_user = db.session.execute(
        select(User).filter(func.lower(User.name) == username.lower())
    ).scalars().first()
    if existing_user is not None:
        return _registration_ack()

    user_uuid = str(uuid4())
    user = User(
        user_id=user_uuid,
        name=username,
        email=email_address,
        role='user',
        is_email_verified=False,
        email_verification_token=get_serializer().dumps(email_address, salt='email-confirm'),
        token_creation_time=datetime.now(timezone.utc),
        created=datetime.now(timezone.utc),
    )
    user.set_password(form.password.data)
    db.session.add(user)
    try:
        if invite is not None:
            db.session.flush()
            claimed = db.session.execute(
                update(InviteToken)
                .where(InviteToken.id == invite.id, InviteToken.used.is_(False))
                .values(used=True, used_by=user_uuid, used_at=datetime.now(timezone.utc))
            ).rowcount
            if claimed != 1:
                db.session.rollback()
                return api_error('The invite is invalid or has expired.', code='conflict')
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        log_system_event(
            'Registration failed because a unique account value was claimed concurrently.',
            event_type='registration', event_level='warning',
        )
        return _registration_ack()

    log_system_event(f"New user registered: {user.name}", event_type='audit', event_level='information')
    confirm_path = url_for('login.confirm_email', token=user.email_verification_token)
    confirm_url = f'{public_origin()}{confirm_path}'
    html = _registration_confirmation_email(confirm_url)
    send_email(user.email, 'Please confirm your email', html)
    return _registration_ack()


def _password_reset_user(token: str):
    """Resolve a live reset token using the same 15-minute UTC rule everywhere."""
    user = db.session.execute(
        select(User).filter_by(password_reset_token=token)
    ).scalar_one_or_none()
    issued_at = user.token_creation_time if user else None
    if issued_at is not None and issued_at.tzinfo is None:
        issued_at = issued_at.replace(tzinfo=timezone.utc)
    if not user or issued_at is None or issued_at + timedelta(minutes=15) < datetime.now(timezone.utc):
        return None
    return user


@login_bp.route('/api/auth/password-reset/request', methods=['POST'])
@validate_body(PasswordResetRequestBody)
def api_password_reset_request(body: PasswordResetRequestBody):
    """Request a reset email without disclosing whether the email exists."""
    if current_user.is_authenticated:
        return api_error('Sign out before requesting a password reset.', code='conflict')

    form = ResetPasswordRequestForm(
        data={'email': body.email}, meta={'csrf': False}
    )
    if not form.validate():
        errors = {
            field: [str(message) for message in messages]
            for field, messages in form.errors.items()
        }
        return api_error('Invalid email address.', code='unprocessable', detail=errors)

    reset_key = auth_endpoint_key('pwd_reset', client_ip_from_request(request))
    if is_rate_limited(reset_key):
        return api_error(
            'Too many password reset requests. Please wait and try again.',
            code='rate_limited',
        )
    user = db.session.execute(
        select(User).filter_by(email=form.email.data.lower())
    ).scalar_one_or_none()
    # Count requests for both known and unknown accounts; the response body is
    # intentionally identical to prevent email-address enumeration.
    record_failure(reset_key)
    if user:
        token = get_serializer().dumps(user.email, salt='password-reset-salt')
        user.password_reset_token = token
        user.token_creation_time = datetime.now(timezone.utc)
        log_system_event(
            f"Password reset requested for user: {user.email}",
            event_type='password_reset', event_level='information',
        )
        db.session.commit()
        send_password_reset_email(user.email, token)
        # The classic mail helper uses flash for form pages. This JSON endpoint
        # returns its own neutral message and must not leave a stale flash for a
        # later page navigation.
        get_flashed_messages()
    return api_ok({
        'requested': True,
        'message': 'If that email is registered, password reset instructions were sent.',
    })


@login_bp.route('/api/auth/password-reset/<token>', methods=['POST'])
@validate_body(PasswordResetConfirmBody)
def api_password_reset_confirm(token: str, body: PasswordResetConfirmBody):
    """Set a new password with a valid reset token; do not create a session."""
    if current_user.is_authenticated:
        return api_error('Sign out before resetting a password.', code='conflict')
    form = UserPasswordForm(data=body.model_dump(), meta={'csrf': False})
    if not form.validate():
        errors = {
            field: [str(message) for message in messages]
            for field, messages in form.errors.items()
        }
        return api_error('Invalid password details.', code='unprocessable', detail=errors)

    user = _password_reset_user(token)
    if user is None:
        return api_error('The password reset link is invalid or has expired.', code='bad_request')
    user.set_password(form.password.data)
    user.password_reset_token = None
    db.session.commit()
    return api_ok({'reset': True, 'next_url': url_for('login.login')})


@login_bp.route('/login/oidc')
def oidc_start():
    """Begin OIDC authorization code + PKCE flow."""
    if current_user.is_authenticated:
        return redirect(url_for('discover.discover'))

    settings_record = global_settings_row()
    config = build_oidc_config(settings_record)
    if not config:
        flash('Single sign-on is not enabled.', 'warning')
        return redirect(url_for('login.login'))

    if not AUTHLIB_AVAILABLE:
        flash('SSO is configured but authlib is not installed. Contact an administrator.', 'error')
        return redirect(url_for('login.login'))

    code_verifier, code_challenge = generate_pkce_pair()
    state = uuid.uuid4().hex
    store_oidc_session(session, state, code_verifier)

    init_oauth(current_app)
    register_oidc_provider(current_app, config)
    oauth_client = get_oauth_client()
    if oauth_client is None:
        flash('SSO client failed to initialize.', 'error')
        return redirect(url_for('login.login'))

    redirect_uri = config.redirect_uri or url_for('login.oidc_callback', _external=True)
    return oauth_client.oidc.authorize_redirect(
        redirect_uri=redirect_uri,
        state=state,
        code_challenge=code_challenge,
        code_challenge_method='S256',
    )


@login_bp.route('/login/oidc/callback')
def oidc_callback():
    """Handle OIDC callback, JIT-provision user, and establish session."""
    if current_user.is_authenticated:
        return redirect(url_for('discover.discover'))

    settings_record = global_settings_row()
    config = build_oidc_config(settings_record)
    if not config:
        flash('Single sign-on is not enabled.', 'warning')
        return redirect(url_for('login.login'))

    if not AUTHLIB_AVAILABLE:
        flash('SSO is configured but authlib is not installed.', 'error')
        return redirect(url_for('login.login'))

    idp_error = request.args.get('error')
    if idp_error:
        flash(
            format_oidc_idp_error(idp_error, request.args.get('error_description')),
            'error',
        )
        return redirect(url_for('login.login'))

    expected_state, code_verifier = pop_oidc_session(session)
    callback_state = request.args.get('state')
    if not expected_state or expected_state != callback_state:
        flash('Invalid SSO state. Please try again.', 'error')
        return redirect(url_for('login.login'))

    init_oauth(current_app)
    register_oidc_provider(current_app, config)
    oauth_client = get_oauth_client()
    if oauth_client is None:
        flash('SSO client failed to initialize.', 'error')
        return redirect(url_for('login.login'))

    try:
        token = oauth_client.oidc.authorize_access_token(code_verifier=code_verifier)
        claims = token.get('userinfo')
        if not claims:
            claims = oauth_client.oidc.parse_id_token(token)
        user = provision_or_update_user(db.session, claims, config)
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
        return redirect(url_for('login.login'))
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('OIDC callback failed: %s', exc)
        flash(format_oidc_callback_error(exc), 'error')
        return redirect(url_for('login.login'))

    login_user(user, remember=True)
    log_system_event(
        f"User {user.name} logged in via OIDC SSO.",
        event_type='login',
        event_level='information',
    )

    return redirect(safe_next_url(request.args.get('next')))


@login_bp.route('/register', methods=['GET', 'POST'])
def register():
    # Attempt to get the invite token from the query parameters
    invite_token_from_url = request.args.get('token')

    if current_user.is_authenticated:
        # A shared/admin browser session must not swallow an invite link — the
        # guest needs Create your account, not "Welcome back" as the inviter.
        if invite_token_from_url:
            logout_user()
        else:
            return redirect(url_for('login.login'))

    invite = None
    if invite_token_from_url:
        invite = db.session.execute(select(InviteToken).filter_by(token=invite_token_from_url, used=False)).scalar_one_or_none()
        if invite:
            # Handle timezone comparison safely
            current_time = datetime.now(timezone.utc)
            if invite.expires_at.tzinfo:
                # Timezone-aware comparison
                is_valid = invite.expires_at >= current_time
            else:
                # Timezone-naive comparison
                naive_current = current_time.replace(tzinfo=None)
                is_valid = invite.expires_at >= naive_current
            
            if is_valid:
                # The invite is valid; skip the whitelist check later
                pass
            else:
                invite = None  # Invalidate
                flash('The invite is invalid or has expired.', 'warning')
                return redirect(url_for('login.register'))
        else:
            invite = None  # Invalidate
            flash('The invite is invalid or has expired.', 'warning')
            return redirect(url_for('login.register'))
    form = RegistrationForm()
    if form.validate_on_submit():
        try:
            email_address = form.email.data.lower()
            existing_user_email = db.session.execute(select(User).filter(func.lower(User.email) == email_address)).scalar_one_or_none()
            if existing_user_email:
                flash(_REGISTRATION_ACK, 'message')
                return redirect(url_for('site.index'))
                    # Proceed with the whitelist check only if no valid invite token is provided
            if not invite:
                whitelist = db.session.execute(select(Whitelist).filter(func.lower(Whitelist.email) == email_address)).scalar_one_or_none()
                if not whitelist:
                    flash(_REGISTRATION_ACK, 'message')
                    return redirect(url_for('site.index'))

            # Case-insensitive: "Admin" next to "admin" made login pick either row.
            existing_user = db.session.execute(
                select(User).filter(func.lower(User.name) == (form.username.data or '').lower())
            ).scalars().first()
            if existing_user is not None:
                flash(_REGISTRATION_ACK, 'message')
                return redirect(url_for('site.index'))

            user_uuid = str(uuid4())
            existing_uuid = db.session.execute(select(User).filter_by(user_id=user_uuid)).scalar_one_or_none()
            if existing_uuid is not None:
                flash('An error occurred while registering. Please try again.')
                return redirect(url_for('login.register'))

            user = User(
                user_id=user_uuid,
                name=form.username.data,
                email=form.email.data.lower(),
                role='user',
                is_email_verified=False,
                email_verification_token=get_serializer().dumps(email_address, salt='email-confirm'),
                token_creation_time=datetime.now(timezone.utc),
                created=datetime.now(timezone.utc)
            )
            user.set_password(form.password.data)
            db.session.add(user)
            if invite:
                # Claim the invite in the same transaction as the account, and
                # only if nobody else has: one link, one account. It used to be
                # marked used after the commit, and never saved at all when no
                # mail went out, so one link could register many accounts.
                # The user row is flushed first: used_by references it.
                db.session.flush()
                claimed = db.session.execute(
                    update(InviteToken)
                    .where(InviteToken.id == invite.id, InviteToken.used.is_(False))
                    .values(used=True, used_by=user_uuid, used_at=datetime.now(timezone.utc))
                ).rowcount
                if claimed != 1:
                    db.session.rollback()
                    flash('The invite is invalid or has expired.', 'warning')
                    return redirect(url_for('login.register'))
            db.session.commit()

            log_system_event(f"New user registered: {user.name}", event_type='audit', event_level='information')

            # Verification email
            verification_token = user.email_verification_token
            confirm_path = url_for('login.confirm_email', token=verification_token)
            confirm_url = f'{public_origin()}{confirm_path}'
            html = _registration_confirmation_email(confirm_url)
            subject = "Please confirm your email"
            send_email(user.email, subject, html)


            flash(_REGISTRATION_ACK, 'message')
            return redirect(url_for('site.index'))
            return redirect(url_for('site.index'))
        except IntegrityError as exc:
            db.session.rollback()
            log_system_event(f'Registration failed with a database integrity error ({type(exc).__name__}).',
                             event_type='registration', event_level='error')
            flash(_REGISTRATION_ACK, 'message')

    for field, errors in form.errors.items():
        for error in errors:
            flash(f'{getattr(form, field).label.text}: {error}', 'error')
    return render_member_auth_spa()


def _confirm_email_token(token: str):
    """Verify a confirmation link and return a stable transition outcome."""
    try:
        email = get_serializer().loads(token, salt='email-confirm', max_age=900)  # 15 minutes
    except SignatureExpired:
        return None, 'expired'
    except BadSignature:
        return None, 'invalid'

    user = db.session.execute(
        select(User).where(func.lower(User.email) == email.lower())
    ).scalar_one_or_none()
    if user is None:
        return None, 'not_found'
    if user.is_email_verified:
        return user, 'already_confirmed'
    user.is_email_verified = True
    db.session.add(user)
    db.session.commit()
    return user, 'confirmed'


@login_bp.route('/confirm/<token>')
def confirm_email(token):
    # The React auth shell calls the existing confirmation API, which owns the
    # one-time token transition and presents valid, expired and invalid states.
    return render_member_auth_spa()


@login_bp.route('/api/auth/confirm/<token>')
def api_confirm_email(token: str):
    """JSON confirmation state for the static authentication shell."""
    _user, outcome = _confirm_email_token(token)
    if outcome == 'expired':
        return api_error('The confirmation link has expired.', code='bad_request')
    if outcome == 'invalid':
        return api_error('The confirmation link is invalid.', code='bad_request')
    if outcome == 'not_found':
        return api_error('The account for this confirmation link was not found.', code='not_found')
    return api_ok({'confirmed': True, 'already_confirmed': outcome == 'already_confirmed'})


@login_bp.route('/reset_password_request', methods=['GET', 'POST'])
def reset_password_request():
    if current_user.is_authenticated:
        return redirect(url_for('login.login'))
    form = ResetPasswordRequestForm()
    if form.validate_on_submit():
        ip = client_ip_from_request(request)
        reset_key = auth_endpoint_key('pwd_reset', ip)
        if is_rate_limited(reset_key):
            flash('Too many password reset requests. Please wait and try again.', 'error')
            return redirect(url_for('login.reset_password_request'))
        user = db.session.execute(select(User).filter_by(email=form.email.data.lower())).scalar_one_or_none()
        # Always record attempt (even unknown email) to slow enumeration
        record_failure(reset_key)
        if user:
            # Generate a unique token
            token = get_serializer().dumps(user.email, salt='password-reset-salt')
            user.password_reset_token = token
            user.token_creation_time = datetime.now(timezone.utc)
            
            log_system_event(f"Password reset requested for user: {user.email}", event_type='password_reset', event_level='information')
            
            db.session.commit()

            # Send reset email
            send_password_reset_email(user.email, token)
        # Same response whether or not the email exists (anti-enumeration)
        flash('If that email is registered, password reset instructions were sent.')
        return redirect(url_for('login.login'))

    if request.method == 'POST':
        for field, errors in form.errors.items():
            for error in errors:
                flash(f'{getattr(form, field).label.text}: {error}', 'error')
    return render_member_auth_spa()

@login_bp.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for('login.login'))

    user = _password_reset_user(token)
    if user is None:
        flash('The password reset link is invalid or has expired.')
        return redirect(url_for('login.login'))

    form = UserPasswordForm()

    if form.validate_on_submit():
        user.set_password(form.password.data)
        user.password_reset_token = None
        db.session.commit()
        flash('Your password has been reset.')
        return redirect(url_for('login.login'))

    if request.method == 'POST':
        for field, errors in form.errors.items():
            for error in errors:
                flash(f'{getattr(form, field).label.text}: {error}', 'error')
    return render_member_auth_spa()


@login_bp.route('/user/invites', methods=['GET', 'POST'])
@login_required
@require_browser_session
def invites():
    if not site_url_is_configured() and current_user.role == 'admin':
        flash(
            'Set a public Site URL in admin settings so invite links are not '
            'tied to localhost. Until then, links use the address you are browsing from.',
            'warning',
        )
    if request.method == 'GET':
        return redirect(url_for('library.library', account='invites'))

    form = InviteForm()
    if form.validate_on_submit():
        email = request.form.get('email')
        # Ensure the user has invites left to send
        current_invites = db.session.scalar(select(func.count(InviteToken.id)).filter_by(creator_user_id=current_user.user_id, used=False))
        if is_admin(current_user) or current_user.invite_quota > current_invites:
            token = str(uuid.uuid4())
            invite_token = InviteToken(
                token=token, 
                creator_user_id=current_user.user_id,
                recipient_email=email
            )
            db.session.add(invite_token)
            db.session.commit()

            send_invite_email(email, build_invite_url(token))

            flash('Invite sent successfully. The invite expires after 48 hours.', 'success')
        else:
            flash('You have reached your invite limit.', 'danger')
        return redirect(url_for('library.library', account='invites'))

    for field, errors in form.errors.items():
        for error in errors:
            flash(f'{getattr(form, field).label.text}: {error}', 'error')
    return redirect(url_for('library.library', account='invites'))

@login_bp.route('/delete_invite/<token>', methods=['POST'])
@login_required
@require_browser_session
def delete_invite(token):
    try:
        invite = db.session.execute(select(InviteToken).filter_by(token=token, creator_user_id=current_user.user_id)).scalar_one_or_none()
        if invite:
            db.session.delete(invite)
            db.session.commit()
            return api_ok()
        return api_error(
            'Invite not found or you do not have permission to delete it.',
            code='not_found',
            status=200,
        )
    except Exception as e:
        db.session.rollback()
        log_system_event(f'Invite delete failed: {e}',
                         event_type='invite', event_level='error')
        return api_error('An error occurred while deleting the invite.', code='internal')
