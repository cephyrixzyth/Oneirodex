"""Request models for ``oneirodex/routes_apis/ownership.py``.

The GOG / Epic / Amazon connect bodies are a bag of optional, aliased fields;
they are modelled with every alias declared so ``extra='forbid'`` and length
limits apply (LIB-04). The ``*/csv`` routes read form-data or a file upload as
well as JSON and are not migrated (see docs/dev/pydantic-adoption.md).
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

_RequiredSteamId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ConnectSteamBody(BaseModel):
    """``POST /api/ownership/steam``.

    Replaces ``steam_id = (data.get('steam_id') or '').strip(); if not steam_id``.
    ``connect_steam_account`` still raises ``ValueError`` for a malformed id and
    the view still turns that into ``code='bad_request'``.
    """

    model_config = ConfigDict(extra='forbid')

    steam_id: _RequiredSteamId


_Id = Annotated[str, StringConstraints(max_length=120)]
_Token = Annotated[str, StringConstraints(max_length=16384)]


class GogConnectBody(BaseModel):
    """``POST /api/ownership/gog``. Aliases are the names the route has always
    read; tokens are stored on the member's account, never returned or logged."""

    model_config = ConfigDict(extra='forbid')

    gog_user_id: _Id | None = None
    user_id: _Id | None = None
    note: _Id | None = None
    refresh_token: _Token | None = None
    token: _Token | None = None
    access_token: _Token | None = None


class EpicConnectBody(BaseModel):
    """``POST /api/ownership/epic``. ``device_auth`` is Legendary/Heroic device-auth JSON."""

    model_config = ConfigDict(extra='forbid')

    epic_account_id: _Id | None = None
    user_id: _Id | None = None
    note: _Id | None = None
    device_auth: _Token | dict | None = None
    token: _Token | dict | None = None


class AmazonConnectBody(BaseModel):
    """``POST /api/ownership/amazon``. ``credential`` is the Nile/Heroic user.json or a refresh token."""

    model_config = ConfigDict(extra='forbid')

    amazon_user_id: _Id | None = None
    user_id: _Id | None = None
    note: _Id | None = None
    credential: _Token | dict | None = None
    token: _Token | dict | None = None
    nile_json: _Token | dict | None = None
    refresh_token: _Token | None = None
    access_token: _Token | None = None
    device_serial: _Id | None = None
    device_serial_number: _Id | None = None


class XboxConnectBody(BaseModel):
    """``POST /api/ownership/xbox`` (INSP-42). The credential is the JSON the
    unofficial client's own ``xbox-authenticate`` wrote; stored on the member's
    account, never logged. Register-only."""

    model_config = ConfigDict(extra='forbid')

    xuid: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=120)
    credential: str | dict | None = None


class PsnConnectBody(BaseModel):
    """``POST /api/ownership/psn`` (INSP-42). ``npsso`` is the member's own
    session token; stored on their account, never logged. Register-only."""

    model_config = ConfigDict(extra='forbid')

    online_id: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=120)
    npsso: str | None = Field(default=None, max_length=256)
