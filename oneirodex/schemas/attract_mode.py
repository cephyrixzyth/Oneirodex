"""Strict admin configuration; member override compatibility stays separate."""
from pydantic import BaseModel, ConfigDict, Field, model_validator


class AttractFilters(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    library_uuid: str | None = Field(default=None, pattern=r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
    genres: list[int] = Field(default_factory=list, max_length=500)
    themes: list[int] = Field(default_factory=list, max_length=500)
    date_from: int | None = Field(default=None, ge=1, le=9999)
    date_to: int | None = Field(default=None, ge=1, le=9999)

    @model_validator(mode='after')
    def valid_filters(self):
        if any(value < 1 for value in self.genres + self.themes):
            raise ValueError('Genre and theme IDs must be positive integers')
        if len(set(self.genres)) != len(self.genres) or len(set(self.themes)) != len(self.themes):
            raise ValueError('Genre and theme selections must be unique')
        if self.date_from is not None and self.date_to is not None and self.date_from > self.date_to:
            raise ValueError('From year must not exceed to year')
        return self


class AttractAutoplay(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    enabled: bool = True
    skipFirst: int = Field(default=0, ge=0, le=300)
    skipAfter: int = Field(default=0, ge=0, le=600)


class AttractModeBody(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    enabled: bool
    idle_timeout: int = Field(ge=10, le=300)
    filters: AttractFilters = Field(default_factory=AttractFilters)
    autoplay: AttractAutoplay = Field(default_factory=AttractAutoplay)
