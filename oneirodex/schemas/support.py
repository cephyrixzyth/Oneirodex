"""Request models for ``oneirodex/routes_apis/support.py``."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

_RequiredTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class CreateSupportTicketBody(BaseModel):
    """``POST /api/support/tickets``.

    Replaces ``title = (data.get('title') or '').strip(); if not title``.
    Area / kind / severity stay coerced in the view (unknown values become
    ``other`` / ``issue`` / ``P2``) rather than 422 — that was the previous
    contract. Truncation of body and logs also stays in the view.
    """

    model_config = ConfigDict(extra='forbid')

    title: _RequiredTitle
    body: str | None = None
    symptom: str | None = None
    kind: str | None = None
    area: str | None = None
    severity: str | None = None
    logs: str | None = None
    deploy_hint: str | None = None
    deploy: str | None = None
    client_hint: str | None = None
    client: str | None = None
    url_hint: str | None = None
    url: str | None = None
    sync_to_github: bool = False
