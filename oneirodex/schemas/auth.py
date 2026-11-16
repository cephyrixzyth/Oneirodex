"""Request models for browser authentication APIs."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


class LoginBody(BaseModel):
    """Credentials accepted by ``POST /api/auth/login``.

    Usernames follow the classic ``StringField`` behavior and are trimmed.
    Passwords are compared exactly as entered.
    """

    model_config = ConfigDict(extra='forbid')

    username: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    password: Annotated[str, StringConstraints(min_length=1)]


class EmailConfirmationBody(BaseModel):
    """Mailbox-owner credentials, preserving the classic confirmation rules."""

    model_config = ConfigDict(extra='ignore', strict=True)

    password: Annotated[str, StringConstraints(min_length=8)] = Field(repr=False)
    confirm_password: str | None = Field(default=None, repr=False)

    @field_validator('password')
    @classmethod
    def bounded_password(cls, value: str) -> str:
        try:
            valid = bool(value.strip()) and 0 < len(value.encode('utf-8')) <= 1024
        except UnicodeEncodeError:
            valid = False
        if not valid:
            raise ValueError('Invalid confirmation password.')
        return value
