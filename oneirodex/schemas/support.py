"""Request models for ``oneirodex/routes_apis/support.py``."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

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
    request_id: UUID | None = None
    preview_token: Annotated[str, StringConstraints(max_length=2048)] | None = None
    retry_github: bool = False
    retry_id: UUID | None = None

    @model_validator(mode='after')
    def retry_requires_existing_external_report(self):
        if self.retry_github and (not self.request_id or not self.sync_to_github):
            raise ValueError('Retry requires an existing report reference and explicit GitHub opt-in.')
        return self


class ReconcileSupportDeliveryBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    issue_number: Annotated[int, Field(strict=True, gt=0, le=2_147_483_647)]
