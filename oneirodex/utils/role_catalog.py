"""Framework-independent role names and normalization."""
from __future__ import annotations

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


def is_librarian(user) -> bool:
    """Whether an authenticated user has librarian-level privileges."""
    return bool(
        getattr(user, 'is_authenticated', False)
        and role_at_least(getattr(user, 'role', None), 'librarian')
    )


def can_request_games(user) -> bool:
    """Children and anonymous users cannot create wishlist requests."""
    return bool(
        getattr(user, 'is_authenticated', False)
        and normalize_role(getattr(user, 'role', None)) != 'child'
    )
