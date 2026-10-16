"""Validated JSON transitions for the first-run setup wizard."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SetupTransitionBody(BaseModel):
    model_config = ConfigDict(extra='forbid')

    step: int = Field(ge=1, le=6)
    skip: bool = False
    username: str = Field(default='', max_length=64)
    email: str = Field(default='', max_length=120)
    password: str = Field(default='', max_length=256)
    confirm_password: str = Field(default='', max_length=256)
    smtp_server: str = Field(default='', max_length=255)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str = Field(default='', max_length=255)
    smtp_password: str = Field(default='', max_length=512)
    smtp_use_tls: bool = False
    smtp_default_sender: str = Field(default='', max_length=255)
    smtp_enabled: bool = False
    enable_game_updates: bool = True
    enable_game_extras: bool = True
    attract_mode_enabled: bool = True
    enable_arr_module: bool = True
    enable_ai_assist: bool = True
    enable_malware_scan: bool = True
    igdb_client_id: str = Field(default='', max_length=255)
    igdb_client_secret: str = Field(default='', max_length=512)
    steam_web_api_key: str = Field(default='', max_length=512)
    steamgriddb_api_key: str = Field(default='', max_length=512)
    giantbomb_api_key: str = Field(default='', max_length=512)
    mobygames_api_key: str = Field(default='', max_length=512)
    thegamesdb_api_key: str = Field(default='', max_length=512)
    enable_hltb_integration: bool = False
    configure_oidc: bool = False
    oidc_issuer_url: str = Field(default='', max_length=512)
    oidc_client_id: str = Field(default='', max_length=255)
    oidc_client_secret: str = Field(default='', max_length=512)
    oidc_redirect_uri: str = Field(default='', max_length=512)
    oidc_scopes: str = Field(default='openid email profile', max_length=255)
    oidc_role_claim: str = Field(default='', max_length=64)
    library_name: str = Field(default='', max_length=255)
    platform: str = Field(default='', max_length=32)
    folder_path: str = Field(default='', max_length=2048)
    scan_mode: Literal['folders', 'files'] = 'folders'
    scan_depth: int = Field(default=1, ge=1, le=2)

    @model_validator(mode='after')
    def validate_admin_password_confirmation(self):
        if self.step == 1 and not self.skip and self.password != self.confirm_password:
            raise ValueError('Passwords do not match.')
        return self
