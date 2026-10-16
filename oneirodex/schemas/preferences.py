"""Typed payload for the member preferences API."""

from pydantic import BaseModel, ConfigDict, Field


class MemberPreferencesBody(BaseModel):
    model_config = ConfigDict(extra='forbid')

    items_per_page: int | None = Field(default=None, ge=1, le=1000)
    default_sort: str | None = Field(default=None, max_length=50)
    default_sort_order: str | None = Field(default=None, max_length=4)
    theme: str | None = Field(default=None, max_length=50)
    icon_pack: str | None = Field(default=None, max_length=50)
    font: str | None = Field(default=None, max_length=64)
    tile_size: str | None = Field(default=None, max_length=8)
    show_tile_titles: bool | None = None
    browser_player_engine: str | None = Field(default=None, max_length=16)
    preferred_game_locale: str | None = Field(default=None, max_length=16)
