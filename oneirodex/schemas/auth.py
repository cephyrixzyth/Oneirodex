"""Request models for browser authentication APIs."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints


class LoginBody(BaseModel):
    """Credentials accepted by ``POST /api/auth/login``.

    Usernames follow the classic ``StringField`` behavior and are trimmed.
    Passwords are compared exactly as entered.
    """

    model_config = ConfigDict(extra='forbid')

    username: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    password: Annotated[str, StringConstraints(min_length=1)]
