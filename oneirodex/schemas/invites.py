"""Validated admin invite quota adjustments."""
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class AdjustInviteQuotaBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    user_id: UUID
    invites_number: int = Field(strict=True, ge=-1000, le=1000)
