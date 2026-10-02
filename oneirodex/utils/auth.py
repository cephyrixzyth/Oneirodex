from datetime import datetime, timezone
from functools import wraps
from flask import request, redirect, url_for, flash
from urllib.parse import urlparse as url_parse
from flask_login import current_user, login_user
from sqlalchemy import func, select
from oneirodex.models import User, db
from oneirodex import login_manager
from oneirodex.utils.rbac import librarian_required, normalize_role, token_lacks_admin_scope  # noqa: F401 — re-export

@login_manager.user_loader
def load_user(user_id):
    """The signed-in user, or None when the session no longer holds.

    A session names ``<id>:<fingerprint>`` (User.get_id). It stops working when
    the account is disabled or the password changes, including remember
    cookies issued before that. A bare ``<id>`` comes from a session made
    before fingerprints existed: refused, except under the test config, where
    tests fake a login that way.
    """
    import hmac

    from flask import current_app

    uid, sep, fingerprint = str(user_id or '').partition(':')
    try:
        user = db.session.get(User, int(uid))
    except (TypeError, ValueError):
        return None
    if user is None or not user.is_active:
        return None
    if sep:
        return user if hmac.compare_digest(fingerprint, user.session_fingerprint()) else None
    return user if current_app.testing else None


def safe_next_url(next_page, *, fallback_endpoint='discover.discover'):
    """Return *next_page* if it is a same-site path, else the fallback.

    The previous check was ``urlparse(next).netloc != ''``, which passes
    ``/\\evil.com`` — empty netloc, but browsers normalise the leading ``/\\``
    to ``//`` and treat it as protocol-relative. So the rule is positive
    instead: it must be a path starting with exactly one ``/``, and carry no
    scheme or authority of its own.
    """
    fallback = url_for(fallback_endpoint)
    if not next_page or not isinstance(next_page, str):
        return fallback

    candidate = next_page.strip()
    if not candidate.startswith('/'):
        return fallback
    # '//host' and '/\host' are both authority forms to a browser.
    if candidate[1:2] in ('/', '\\'):
        return fallback

    parsed = url_parse(candidate)
    if parsed.scheme or parsed.netloc:
        return fallback
    return candidate

_BURN_HASH = None


def burn_password_check(password) -> None:
    """Spend the same argon2 time on an unknown username as on a known one,
    so response time does not reveal which usernames exist."""
    global _BURN_HASH
    from argon2.exceptions import VerifyMismatchError
    from oneirodex.models.users import ph

    if _BURN_HASH is None:
        _BURN_HASH = ph.hash('not-a-real-password')
    try:
        ph.verify(_BURN_HASH, password or '')
    except VerifyMismatchError:
        pass


def sign_in_and_redirect(user):
    """Sign in an account whose password was just checked, and continue to ``next``.

    Takes the user row rather than looking the name up again: a second,
    case-insensitive lookup could land on a different account when two
    usernames differ only in case.
    """
    user.lastlogin = datetime.now(timezone.utc)
    db.session.commit()
    login_user(user, remember=True)
    return redirect(safe_next_url(request.args.get('next')))


def _authenticate_and_redirect(username, password):
    user = db.session.execute(select(User).filter(func.lower(User.name) == func.lower(username))).scalars().first()
    
    if user and user.check_password(password):
        user.lastlogin = datetime.now(timezone.utc)
        db.session.commit()
        login_user(user, remember=True)
        
        return redirect(safe_next_url(request.args.get('next')))
    else:
        flash('Invalid username or password', 'error')
        return redirect(url_for('login.login'))

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        role = normalize_role(getattr(current_user, 'role', None) or '') if current_user.is_authenticated else ''
        if current_user.is_authenticated and role == 'admin' and token_lacks_admin_scope():
            from oneirodex.utils.api_response import api_error
            return api_error('This token does not have the admin scope', code='forbidden')
        if not current_user.is_authenticated or role != 'admin':
            flash("You must be an admin to access this page.", "danger")
            return redirect(url_for('login.login'))
        return f(*args, **kwargs)
    return decorated_function
