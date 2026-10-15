"""Whitelist request contract matching the existing email form."""
from pydantic import BaseModel, ConfigDict, Field, field_validator
from email_validator import validate_email, EmailNotValidError


class AddWhitelistBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: str = Field(min_length=1, max_length=120)

    @field_validator('email')
    @classmethod
    def validate_address(cls, value):
        value = value.strip().lower()
        try:
            validate_email(value, check_deliverability=False)
        except EmailNotValidError:
            raise ValueError('Enter a valid email address.') from None
        return value
