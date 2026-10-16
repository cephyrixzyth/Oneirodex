"""Role helpers for Oneirodex RBAC v1.

Roles (ordered by privilege):
  admin > librarian > user > child

Legacy installs only had admin/user; librarian and child are additive.
"""

from __future__ import annotations

from functools import wraps

from oneirodex.utils.api_response import api_error
from oneirodex.utils.role_catalog import (
    ROLE_RANK,
    VALID_ROLES,
    can_request_games as _can_request_games,
    is_librarian as _is_librarian,
    normalize_role,
    role_at_least,
)


def _current_user():
    from flask_login import current_user

    return current_user


def _limited_by_token(user) -> bool:
    """The role check is about the caller, who came in on a token without the
    admin scope. Routes that check the role in their body (not through
    admin_required) get the same rule as the decorators this way."""
    from flask import has_request_context

    if not has_request_context():
        return False
    try:
        same = getattr(user, 'id', None) is not None and getattr(user, 'id', None) == getattr(_current_user(), 'id', None)
    except Exception:  # noqa: BLE001 — no current user to compare against
        return False
    return same and token_lacks_admin_scope()


def is_admin(user=None) -> bool:
    user = user or _current_user()
    return bool(
        getattr(user, 'is_authenticated', False)
        and normalize_role(user.role) == 'admin'
        and not _limited_by_token(user)
    )


def is_librarian(user=None) -> bool:
    """Librarian or admin — can manage library ops without full admin."""
    user = user or _current_user()
    return bool(
        _is_librarian(user)
        and not _limited_by_token(user)
    )


def can_request_games(user=None) -> bool:
    """Children cannot create wishlist requests."""
    user = user or _current_user()
    return _can_request_games(user)


def token_lacks_admin_scope() -> bool:
    """True when this request came in on an API token without the ``admin`` scope.

    A token signs its owner in fully, so the role checks alone let a leaked
    desktop-companion token (read:library, write:download) owned by an admin
    reach every admin route. Elevated routes also need the token's consent.
    Browser sessions carry no token and are unaffected.
    """
    from flask import g

    token = g.get('api_token')
    return token is not None and not token.has_scope('admin')


def librarian_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        from flask import flash, redirect, request, url_for

        current_user = _current_user()
        if (not current_user.is_authenticated or not is_librarian(current_user)
                or token_lacks_admin_scope()):
            if request.path.startswith('/api/'):
                return api_error('Librarian or admin required', code='forbidden')
            flash('You need librarian or admin access for that page.', 'danger')
            return redirect(url_for('login.login'))
        return f(*args, **kwargs)

    return decorated
