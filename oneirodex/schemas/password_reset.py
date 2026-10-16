"""Request models for browser password-reset APIs."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints


class PasswordResetRequestBody(BaseModel):
    model_config = ConfigDict(extra='forbid')

    email: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class PasswordResetConfirmBody(BaseModel):
    model_config = ConfigDict(extra='forbid')

    password: Annotated[str, StringConstraints(min_length=1)]
    confirm_password: Annotated[str, StringConstraints(min_length=1)]
