"""Request model for browser account registration."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints


class RegistrationBody(BaseModel):
    """Basic shape for registration; ``RegistrationForm`` remains the
    authority for the existing username and email validation rules.
    """

    model_config = ConfigDict(extra='forbid')

    username: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
    email: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    password: Annotated[str, StringConstraints(min_length=1)]
