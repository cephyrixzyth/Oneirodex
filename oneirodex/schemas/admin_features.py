"""Request models for ``routes_admin_ext/features.py``."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator


class FeaturePreferencesBody(BaseModel):
    """All seven database feature preferences must be supplied as booleans."""

    model_config = ConfigDict(extra='forbid')

    enable_arr_module: StrictBool
    enable_ai_assist: StrictBool
    enable_malware_scan: StrictBool
    enable_game_updates: StrictBool
    enable_game_extras: StrictBool
    attract_mode_enabled: StrictBool
    allow_children_in_household_lobby: StrictBool


class ChallengeSolverBody(BaseModel):
    """One persisted challenge-solver connection configuration."""

    model_config = ConfigDict(extra='forbid')

    enabled: StrictBool
    url: Annotated[str, Field(max_length=2048)]
    provider: Literal['flaresolverr_compat', 'trawl', 'token_api']
    max_tier: Annotated[StrictInt, Field(gt=0)]

    @field_validator('url')
    @classmethod
    def reject_control_characters(cls, value: str) -> str:
        if any(ord(character) < 32 for character in value):
            raise ValueError('URL contains control characters')
        return value
