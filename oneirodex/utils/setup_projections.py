"""Safe setup-state projections shared by legacy and native APIs."""
from __future__ import annotations


def state_settings() -> dict:
    from oneirodex.utils.global_settings import global_settings_row

    row = global_settings_row()
    if row is None:
        return {}
    return {
        'smtp_server': row.smtp_server or '',
        'smtp_port': row.smtp_port or 587,
        'smtp_username': row.smtp_username or '',
        'smtp_default_sender': row.smtp_default_sender or '',
        'smtp_use_tls': bool(row.smtp_use_tls),
        'smtp_enabled': bool(row.smtp_enabled),
        'smtp_password_configured': bool(row.smtp_password),
        'features': {
            'enable_game_updates': bool(row.enable_game_updates),
            'enable_game_extras': bool(row.enable_game_extras),
            'attract_mode_enabled': bool(row.attract_mode_enabled),
            'enable_arr_module': bool(row.enable_arr_module),
            'enable_ai_assist': bool(row.enable_ai_assist),
            'enable_malware_scan': bool(row.enable_malware_scan),
        },
        'igdb_client_id': row.igdb_client_id or '',
        'igdb_secret_configured': bool(row.igdb_client_secret),
        'provider_keys': {
            key: bool(getattr(row, key, None))
            for key in (
                'steam_web_api_key', 'steamgriddb_api_key', 'giantbomb_api_key',
                'mobygames_api_key', 'thegamesdb_api_key',
            )
        },
        'enable_hltb_integration': bool(row.enable_hltb_integration),
        'oidc': {
            'issuer_url': row.oidc_issuer_url or '',
            'client_id': row.oidc_client_id or '',
            'redirect_uri': row.oidc_redirect_uri or '',
            'scopes': row.oidc_scopes or 'openid email profile',
            'role_claim': row.oidc_role_claim or '',
            'secret_configured': bool(row.oidc_client_secret),
            'enabled': False,
        },
    }
