"""Request models for administrator integration settings."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, field_validator


class OidcAdminBody(BaseModel):
    model_config = ConfigDict(extra='forbid')

    oidc_enabled: StrictBool
    oidc_display_name: Annotated[StrictStr, Field(max_length=120)]
    oidc_issuer_url: Annotated[StrictStr, Field(max_length=512)]
    oidc_client_id: Annotated[StrictStr, Field(max_length=255)]
    oidc_client_secret: Annotated[StrictStr, Field(max_length=512)]
    oidc_redirect_uri: Annotated[StrictStr, Field(max_length=512)]
    oidc_scopes: Annotated[StrictStr, Field(max_length=255)]
    oidc_role_claim: Annotated[StrictStr, Field(max_length=64)]
    oidc_role_map: dict[StrictStr, StrictStr] = Field(max_length=128)

    @field_validator(
        'oidc_display_name', 'oidc_issuer_url', 'oidc_client_id',
        'oidc_client_secret', 'oidc_redirect_uri', 'oidc_scopes', 'oidc_role_claim',
    )
    @classmethod
    def reject_control_characters(cls, value: str) -> str:
        if any(ord(character) < 32 and character != '\t' for character in value):
            raise ValueError('Text contains control characters')
        return value

    @field_validator('oidc_role_map')
    @classmethod
    def validate_role_map(cls, values: dict[str, str]) -> dict[str, str]:
        allowed = {'admin', 'librarian', 'user', 'child'}
        if any(not key.strip() or len(key) > 120 for key in values):
            raise ValueError('Role names must be nonempty and at most 120 characters')
        if any(value.strip().lower() not in allowed for value in values.values()):
            raise ValueError('Role values must name a supported role')
        return values


class CommunityChatBody(BaseModel):
    model_config = ConfigDict(extra='forbid')

    community_chat_url: Annotated[StrictStr, Field(max_length=2048)]
    community_chat_label: Annotated[StrictStr, Field(max_length=120)]

    @field_validator('community_chat_label')
    @classmethod
    def reject_label_controls(cls, value: str) -> str:
        if any(ord(character) < 32 for character in value):
            raise ValueError('Label contains control characters')
        return value
