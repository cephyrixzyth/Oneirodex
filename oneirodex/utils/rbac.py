"""Role helpers for Oneirodex RBAC v1.

Roles (ordered by privilege):
  admin > librarian > user > child

Legacy installs only had admin/user; librarian and child are additive.
"""

from __future__ import annotations

from functools import wraps

from flask import flash, redirect, request, url_for
from flask_login import current_user

from oneirodex.utils.api_response import api_error

VALID_ROLES = ('admin', 'librarian', 'user', 'child')

ROLE_RANK = {
    'child': 10,
    'user': 20,
    'librarian': 30,
    'admin': 40,
}


def normalize_role(role: str | None) -> str:
    value = (role or 'user').strip().lower()
    return value if value in ROLE_RANK else 'user'


def role_at_least(role: str | None, minimum: str) -> bool:
    return ROLE_RANK.get(normalize_role(role), 0) >= ROLE_RANK.get(minimum, 99)


def is_admin(user=None) -> bool:
    user = user or current_user
    return bool(getattr(user, 'is_authenticated', False) and normalize_role(user.role) == 'admin')


def is_librarian(user=None) -> bool:
    """Librarian or admin — can manage library ops without full admin."""
    user = user or current_user
    return bool(
        getattr(user, 'is_authenticated', False)
        and role_at_least(user.role, 'librarian')
    )


def can_request_games(user=None) -> bool:
    """Children cannot create wishlist requests."""
    user = user or current_user
    if not getattr(user, 'is_authenticated', False):
        return False
    return normalize_role(user.role) != 'child'


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
        if (not current_user.is_authenticated or not is_librarian(current_user)
                or token_lacks_admin_scope()):
            if request.path.startswith('/api/'):
                return api_error('Librarian or admin required', code='forbidden')
            flash('You need librarian or admin access for that page.', 'danger')
            return redirect(url_for('login.login'))
        return f(*args, **kwargs)

    return decorated
