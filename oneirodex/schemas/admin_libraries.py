"""Request models for ``oneirodex/routes_admin_ext/libraries.py``."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from oneirodex.utils.image_upload_limits import LIBRARY_PREVIEW_MAX_BODY_BYTES


class PreviewCroppedImageBody(BaseModel):
    """``POST /api/library/preview-cropped-image``.

    Replaces ``if not data or 'image_data' not in data``. The value is not
    stripped — a data URL must keep its prefix. Decode / PIL failures stay
    500 from the view.
    """

    model_config = ConfigDict(extra='forbid')

    image_data: str = Field(max_length=LIBRARY_PREVIEW_MAX_BODY_BYTES)
