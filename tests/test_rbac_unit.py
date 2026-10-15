"""RBAC v1 pure unit tests (no database)."""

from oneirodex.utils.rbac import (
    VALID_ROLES,
    can_request_games,
    is_admin,
    is_librarian,
    normalize_role,
    role_at_least,
)
from oneirodex.utils.role_catalog import (
    can_request_games as catalog_can_request_games,
    is_librarian as catalog_is_librarian,
)


class _User:
    def __init__(self, role, authenticated=True):
        self.role = role
        self.is_authenticated = authenticated


def test_valid_roles_include_librarian_and_child():
    assert set(VALID_ROLES) >= {'admin', 'librarian', 'user', 'child'}


def test_normalize_and_rank():
    assert normalize_role('ADMIN') == 'admin'
    assert normalize_role('nope') == 'user'
    assert role_at_least('librarian', 'user')
    assert role_at_least('admin', 'librarian')
    assert not role_at_least('user', 'librarian')


def test_is_librarian_and_admin():
    assert is_admin(_User('admin'))
    assert not is_admin(_User('librarian'))
    assert is_librarian(_User('librarian'))
    assert is_librarian(_User('admin'))
    assert not is_librarian(_User('user'))


def test_child_cannot_request_games():
    assert can_request_games(_User('user'))
    assert can_request_games(_User('librarian'))
    assert not can_request_games(_User('child'))
    assert not can_request_games(_User('user', authenticated=False))


def test_framework_independent_role_catalog_matches_native_role_rules():
    assert catalog_is_librarian(_User('librarian'))
    assert catalog_is_librarian(_User('admin'))
    assert not catalog_is_librarian(_User('user'))
    assert catalog_can_request_games(_User('user'))
    assert not catalog_can_request_games(_User('child'))
    assert not catalog_can_request_games(_User('user', authenticated=False))
