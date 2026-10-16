"""Framework-independent password checks shared by native auth routes."""

from __future__ import annotations

from argon2.exceptions import VerifyMismatchError

from oneirodex.models.users import ph

_BURN_HASH: str | None = None


def burn_password_check(password: str | None) -> None:
    """Spend an Argon2 verification for unknown usernames to limit enumeration."""
    global _BURN_HASH
    if _BURN_HASH is None:
        _BURN_HASH = ph.hash('not-a-real-password')
    try:
        ph.verify(_BURN_HASH, password or '')
    except VerifyMismatchError:
        pass
