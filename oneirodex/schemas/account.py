"""Request models for ``oneirodex/routes_apis/account.py``."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator

# Stock ids are looked up after ``.strip()`` in ``stock_avatar``. A
# whitespace-only id was already "not one of the avatars we ship".
_RequiredId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
# Passwords are compared as sent — do not strip.
_RequiredSecret = Annotated[str, StringConstraints(min_length=1)]
_MAX_CURRENT_PASSWORD_BYTES = 16 * 1024
_MAX_NEW_PASSWORD_BYTES = 4 * 1024


def password_exceeds_byte_limit(field_name: str, value: str) -> bool:
    """Return whether one password value exceeds its storage/verify input cap."""
    limit = (
        _MAX_CURRENT_PASSWORD_BYTES
        if field_name == 'current_password'
        else _MAX_NEW_PASSWORD_BYTES
    )
    try:
        return len(value.encode('utf-8')) > limit
    except UnicodeEncodeError:
        return True


class StockAvatarBody(BaseModel):
    """``POST /api/account/avatar/stock``.

    Replaces ``set_stock_avatar(data.get('id'), ...)`` treating a missing id
    as 400 "not one of the avatars we ship". Unknown ids still 400 from the
    helper. Avatar upload is multipart, not JSON.
    """

    model_config = ConfigDict(extra='forbid')

    id: _RequiredId


class ChangePasswordBody(BaseModel):
    """``POST /api/account/password``.

    Replaces missing/empty fields falling through to 401 (empty current) or
    the min-length 422. The 8-character floor, mismatch, and reuse checks
    stay in the view. Invites are not modelled: ``email`` is optional and
    ``{}`` is a valid create.
    """

    model_config = ConfigDict(extra='forbid')

    current_password: _RequiredSecret
    new_password: _RequiredSecret
    confirm_password: _RequiredSecret

    @field_validator('current_password', 'new_password', 'confirm_password')
    @classmethod
    def bound_password_bytes(cls, value: str, info):
        if password_exceeds_byte_limit(info.field_name, value):
            raise ValueError(f'{info.field_name} exceeds the maximum supported length')
        return value
