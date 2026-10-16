"""Framework-independent validation rules for admin-created user profiles."""
from __future__ import annotations

import re

from oneirodex.utils.rbac import VALID_ROLES as _RBAC_VALID_ROLES

VALID_ROLES = list(_RBAC_VALID_ROLES)
RESERVED_USERNAMES = ['system']


def validate_username(username):
    if not username or not isinstance(username, str):
        return False, 'Username is required'
    if username.lower() in RESERVED_USERNAMES:
        return False, f"'{username}' is a reserved username and cannot be used"
    if not re.match(r'^[\w.]+$', username):
        return False, 'Username can only contain letters, numbers, dots and underscores'
    if len(username) < 3 or len(username) > 64:
        return False, 'Username must be between 3 and 64 characters long'
    return True, ''


def validate_email(email):
    if not email or not isinstance(email, str):
        return False, 'Email is required'
    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
        return False, 'Invalid email format'
    if len(email) > 120:
        return False, 'Email address too long'
    return True, ''


def validate_role(role):
    if not role or not isinstance(role, str):
        return False, 'Role is required'
    if role not in VALID_ROLES:
        return False, f"Role must be one of: {', '.join(VALID_ROLES)}"
    return True, ''


def validate_about(about):
    if about is not None:
        if not isinstance(about, str):
            return False, 'About field must be a string'
        if len(about) > 256:
            return False, 'About field cannot exceed 256 characters'
    return True, ''
