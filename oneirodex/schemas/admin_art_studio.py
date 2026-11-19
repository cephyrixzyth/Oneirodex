"""Request models for ``oneirodex/routes_admin_ext/art_studio.py``."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

_RequiredTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]


Composition = Literal['auto', 'workbench', 'cartridge', 'marquee', 'crt', 'pixel', 'boxart', 'neon']


class ArtStudioPreviewBody(BaseModel):
    """``POST /admin/api/art-studio/preview``.

    Replaces empty ``title`` 400. Size / format / artistic handling stays
    in the view. Stock generate and batch still use ``_json_body()``.
    """

    model_config = ConfigDict(extra='forbid')

    composition: Composition = 'auto'
    title: _RequiredTitle
    system: str | None = None
    width: Any = None
    height: Any = None
    format: str | None = None
    artistic: Any = True
    headline: Any = None
    subtitle: Any = None
    title_scale: Any = None


class ArtStudioGenerateBody(BaseModel):
    """``POST /admin/api/art-studio/generate``.

    Replaces empty ``title`` 400. Disk errors stay in the view.
    """

    model_config = ConfigDict(extra='forbid')

    composition: Composition = 'auto'
    title: _RequiredTitle
    system: str | None = None
    format: str | None = None
    headline: Any = None
    subtitle: Any = None
    title_scale: Any = None


class ArtStudioApplyBody(BaseModel):
    """``POST /admin/api/art-studio/apply``.

    Replaces empty ``pack_id`` / ``id`` 400. Mode-dependent ``game_uuid`` /
    ``library_uuid`` checks stay in the view.
    """

    model_config = ConfigDict(extra='forbid')

    pack_id: str | None = None
    id: str | None = None
    mode: str | None = None
    library_uuid: str | None = None
    game_uuid: str | None = None
    filename: str | None = None

    @model_validator(mode='after')
    def require_pack_id_or_id(self) -> Self:
        if not (self.pack_id or self.id or '').strip():
            raise ValueError('pack_id is required')
        return self
