from oneirodex.utils.api_tokens import require_browser_session
import os
import uuid
from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app, abort, session
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
from oneirodex.utils.smtp import send_email, send_password_reset_email, send_invite_email
from oneirodex.utils.processors import get_global_settings
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
from oneirodex import cache
from datetime import datetime, timedelta, timezone
from sqlalchemy import func, select, update
from urllib.parse import urlparse
from itsdangerous import SignatureExpired, BadSignature
from uuid import uuid4
from sqlalchemy.exc import IntegrityError

from oneirodex.utils.tokens import get_serializer
from oneirodex.utils.rbac import is_admin


login_bp = Blueprint('login', __name__)

_INVALID_CREDS = 'Invalid username or password. USERNAMES ARE CASE SENSITIVE!'


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

@login_bp.context_processor
@cache.cached(timeout=500, key_prefix='global_settings')
def inject_settings():
    """Context processor to inject global settings into templates"""
    return get_global_settings()

@login_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('discover.discover'))

    form = LoginForm()
    if request.method == 'POST' and form.validate_on_submit():
        username = form.username.data
        password = form.password.data
        ip = client_ip_from_request(request)
        rate_key = login_rate_key(ip, username)

        if is_rate_limited(rate_key) or is_rate_limited(login_rate_key(ip, None)):
            flash('Too many login attempts. Please wait a few minutes and try again.', 'error')
            log_system_event(
                f'Login rate-limited for IP {ip}',
                event_type='login',
                event_level='warning',
            )
            return redirect(url_for('login.login'))

        user = db.session.execute(select(User).filter_by(name=username)).scalar_one_or_none()

        # Password first, for every account: telling a visitor "not activated"
        # or "banned" before checking the password confirms the username
        # exists, and skipping the hash for unknown names showed in the timing.
        if user is None:
            burn_password_check(password)
        if user is None or not user.check_password(password):
            flash(_INVALID_CREDS, 'error')
            if user is None:
                log_system_event(f"Failed login for unknown user from {ip}", event_type='login', event_level='warning')
            else:
                log_system_event(
                    f"User {username} attempted to log in with invalid credentials.",
                    event_type='login',
                    event_level='warning',
                )
            record_failure(rate_key)
            record_failure(login_rate_key(ip, None))
            return redirect(url_for('login.login'))

        # Accounts an admin created without an email carry an unroutable
        # `no-email.invalid` placeholder and are never marked verified —
        # there is nothing to verify. The activation gate is about real
        # addresses that have not been confirmed yet, so skip it for them.
        if not user.is_email_verified and not is_placeholder_email(user.email):
            flash('Your account is not activated, check your email.', 'warning')
            log_system_event(f"User {username} attempted to log in with an unverified account.", event_type='login', event_level='warning')
            record_failure(rate_key)
            return redirect(url_for('login.login'))

        if not user.state:
            flash('Your account has been banned.', 'error')
            log_system_event(f"User {username} attempted to log in with a banned account.", event_type='login', event_level='warning')
            record_failure(rate_key)
            return redirect(url_for('login.login'))

        clear_failures(rate_key)
        clear_failures(login_rate_key(ip, None))
        log_system_event(f"User {username} logged in successfully.", event_type='login', event_level='information')
        return sign_in_and_redirect(user)

    settings_record = global_settings_row()
    oidc_config = build_oidc_config(settings_record)
    return render_template(
        'login/login.html',
        form=form,
        oidc_enabled=oidc_config is not None,
        oidc_display_name=oidc_config.display_name if oidc_config else 'Sign in with SSO',
    )


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
                flash('This email is already in use. Please use a different email or log in.')
                return redirect(url_for('login.register'))
                    # Proceed with the whitelist check only if no valid invite token is provided
            if not invite:
                whitelist = db.session.execute(select(Whitelist).filter(func.lower(Whitelist.email) == email_address)).scalar_one_or_none()
                if not whitelist:
                    flash('Your email is not whitelisted.')
                    return redirect(url_for('login.register'))

            # Case-insensitive: "Admin" next to "admin" made login pick either row.
            existing_user = db.session.execute(
                select(User).filter(func.lower(User.name) == (form.username.data or '').lower())
            ).scalars().first()
            if existing_user is not None:
                flash('User already exists. Please Log in.')
                return redirect(url_for('login.register'))

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
            html = render_template('login/registration_activate.html', confirm_url=confirm_url)
            subject = "Please confirm your email"
            send_email(user.email, subject, html)


            flash('A confirmation email has been sent via email.', 'success')
            return redirect(url_for('site.index'))
        except IntegrityError as e:
            db.session.rollback()
            log_system_event(f'Registration failed with a database integrity error: {e}',
                             event_type='registration', event_level='error')
            flash('error while registering. Please try again.')

    return render_template('login/registration.html', title='Register', form=form)


@login_bp.route('/confirm/<token>')
def confirm_email(token):
    try:
        email = get_serializer().loads(token, salt='email-confirm', max_age=900)  # 15 minutes
    except SignatureExpired:
        return render_template('login/confirmation_expired.html'), 400
    except BadSignature:
        return render_template('login/confirmation_invalid.html'), 400

    user = db.session.execute(
        select(User).where(func.lower(User.email) == email.lower())
    ).scalar_one_or_none() or abort(404)
    if user.is_email_verified:
        return render_template('login/registration_already_confirmed.html')
    else:
        user.is_email_verified = True
        db.session.add(user)
        db.session.commit()
        return render_template('login/confirmation_success.html')


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

    return render_template('login/reset_password_request.html', title='Reset Password', form=form)

@login_bp.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for('login.login'))

    user = db.session.execute(select(User).filter_by(password_reset_token=token)).scalar_one_or_none()
    # The column is a plain DateTime, so Postgres hands the stored UTC value
    # back naive; comparing that with an aware "now" raised a TypeError and
    # turned every reset link into a 500.
    issued_at = user.token_creation_time if user else None
    if issued_at is not None and issued_at.tzinfo is None:
        issued_at = issued_at.replace(tzinfo=timezone.utc)
    if not user or issued_at is None or issued_at + timedelta(minutes=15) < datetime.now(timezone.utc):
        flash('The password reset link is invalid or has expired.')
        return redirect(url_for('login.login'))

    form = UserPasswordForm()

    if form.validate_on_submit():
        user.set_password(form.password.data)
        user.password_reset_token = None
        db.session.commit()
        flash('Your password has been reset.')
        return redirect(url_for('login.login'))

    return render_template('login/reset_password.html', form=form, token=token)


@login_bp.route('/user/invites', methods=['GET', 'POST'])
@login_required
@require_browser_session
def invites():
    site_url = public_origin()
    smtp_enabled = is_smtp_configured()
    if not site_url_is_configured() and current_user.role == 'admin':
        flash(
            'Set a public Site URL in admin settings so invite links are not '
            'tied to localhost. Until then, links use the address you are browsing from.',
            'warning',
        )
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
        return redirect(url_for('login.invites'))

    invites = db.session.execute(select(InviteToken).filter_by(creator_user_id=current_user.user_id, used=False)).scalars().all()
    current_invites_count = len(invites)
    unlimited = current_user.role == 'admin'
    remaining_invites = None if unlimited else max(0, current_user.invite_quota - current_invites_count)

    return render_template('/login/user_invites.html', 
                         form=form, 
                         invites=invites, 
                         invite_quota=None if unlimited else current_user.invite_quota, 
                         invites_unlimited=unlimited,
                         site_url=site_url, 
                         smtp_enabled=smtp_enabled,
                         current_invites_count=current_invites_count, 
                         remaining_invites=remaining_invites, 
                         current_datetime=datetime.now(timezone.utc))

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
