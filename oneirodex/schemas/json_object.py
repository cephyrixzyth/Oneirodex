"""A JSON object whose route keeps its existing semantic field validation."""

from __future__ import annotations

from typing import Any

from pydantic import RootModel


class JsonObjectBody(RootModel[dict[str, Any]]):
    """Require an object while allowing a route-specific partial field set."""
