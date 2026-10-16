"""Validated payload for the native admin manual-identify workflow."""

from __future__ import annotations

from datetime import date
from urllib.parse import urlparse
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ManualIdentifyBody(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    igdb_id: int = Field(ge=1, le=9_999_999_999)
    name: str = Field(min_length=1, max_length=500)
    full_disk_path: str = Field(min_length=1, max_length=4096)
    library_uuid: str = Field(min_length=1, max_length=36)
    summary: str = Field(default='', max_length=100_000)
    storyline: str = Field(default='', max_length=100_000)
    url: str = Field(default='', max_length=2048)
    video_urls: str = Field(default='', max_length=10_000)
    aggregated_rating: float | None = Field(default=None, ge=0, le=100)
    first_release_date: date | None = None
    status: str = ''
    category: str = ''
    developer: str = Field(default='', max_length=255)
    publisher: str = Field(default='', max_length=255)
    genre_ids: list[int] = Field(default_factory=list, max_length=100)
    game_mode_ids: list[int] = Field(default_factory=list, max_length=100)
    theme_ids: list[int] = Field(default_factory=list, max_length=100)
    platform_ids: list[int] = Field(default_factory=list, max_length=100)
    player_perspective_ids: list[int] = Field(default_factory=list, max_length=100)
    item_kind: str = Field(default='', max_length=32)
    provider_urls: dict[str, str] = Field(default_factory=dict, max_length=9)

    @field_validator('url')
    @classmethod
    def safe_http_url(cls, value: str) -> str:
        if value:
            parsed = urlparse(value)
            if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
                raise ValueError('URL must be a valid HTTP or HTTPS address')
        return value

    @field_validator('video_urls')
    @classmethod
    def valid_video_urls(cls, value: str) -> str:
        for candidate in (url.strip() for url in value.split(',')):
            if candidate:
                parsed = urlparse(candidate)
                if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
                    raise ValueError('Video URLs must be valid HTTP or HTTPS addresses')
        return value

    @field_validator('provider_urls')
    @classmethod
    def valid_provider_urls(cls, value: dict[str, str]) -> dict[str, str]:
        allowed = {'steam', 'gog', 'epicgames', 'itch', 'rawg', 'mobygames', 'thegamesdb', 'official', 'wikipedia'}
        if set(value) - allowed:
            raise ValueError('Provider link type is not supported')
        for url in value.values():
            parsed = urlparse(url.strip()) if url.strip() else None
            if parsed and (parsed.scheme not in {'http', 'https'} or not parsed.netloc):
                raise ValueError('Provider links must be valid HTTP or HTTPS addresses')
        return value

    @field_validator('status')
    @classmethod
    def valid_status(cls, value: str) -> str:
        from oneirodex.models import Status
        if value and value not in Status.__members__:
            raise ValueError('Select a valid status')
        return value

    @field_validator('category')
    @classmethod
    def valid_category(cls, value: str) -> str:
        from oneirodex.models import Category
        if value and value not in Category.__members__:
            raise ValueError('Select a valid category')
        return value
