"""Request model for the admin scan-filter editor."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class ScanFilterBody(BaseModel):
    """Keep historical coercion and validation in the route after object parsing."""

    model_config = ConfigDict(extra='allow')

    kind: Any = 'name'
    pattern: Any = ''
    case_sensitive: Any = False
