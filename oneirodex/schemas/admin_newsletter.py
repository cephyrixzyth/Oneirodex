"""Request models for admin newsletter delivery."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator


class NewsletterSendBody(BaseModel):
    """Validate the bounded message and explicit recipient list before sending."""

    model_config = ConfigDict(extra='forbid')

    subject: Annotated[StrictStr, Field(min_length=1, max_length=255)]
    content: Annotated[StrictStr, Field(min_length=1, max_length=1_048_576)]
    recipients: Annotated[list[StrictStr], Field(min_length=1)]

    @field_validator('subject', 'content')
    @classmethod
    def require_non_whitespace_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('Text must not be blank')
        return value

    @field_validator('subject', 'recipients')
    @classmethod
    def reject_header_newlines(cls, value):
        values = value if isinstance(value, list) else [value]
        if any('\r' in item or '\n' in item for item in values):
            raise ValueError('Header values cannot contain newlines')
        return value

    @field_validator('recipients')
    @classmethod
    def require_nonempty_addresses(cls, values: list[str]) -> list[str]:
        if any(not address for address in values):
            raise ValueError('Recipients must not be empty')
        return values
