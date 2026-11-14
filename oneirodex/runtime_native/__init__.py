"""Opt-in native routes; this manifest does not import the runtime framework."""

ADMIN_STATIC_ROUTES = (
    '/libraries',
    '/admin/library/add',
    '/scan_management',
    '/scan_manual_folder',
    '/admin/users',
    '/admin/announcements',
    '/admin/invites',
    '/admin/manage_invites',
    '/admin/ai',
    '/admin/arr',
    '/admin/extensions',
    '/admin/whitelist',
    '/admin/remote_play',
    '/admin/quality_profiles',
    '/admin/storage',
    '/admin/smtp_settings',
    '/admin/scan_match',
    '/admin/plugins',
    '/admin/settings',
    '/admin/detail_layout',
    '/admin/emulator_profiles',
    '/admin/support',
    '/admin/help',
    '/admin/ownership',
    '/admin',
    '/admin/dashboard',
    '/admin/ops',
    '/admin/art_studio',
    '/admin/images',
    '/admin/system/danger',
    '/admin/attract_mode_settings',
    '/admin/igdb_settings',
    '/admin/chat_emoji',
    '/admin/features',
    '/admin/reference_sets',
    '/admin/new_server_settings',
    '/admin/discovery_sections',
    '/admin/newsletter',
    '/admin/integrations/oidc',
    '/admin/manage-downloads',
    '/admin/statistics',
    '/admin/themes',
    '/admin/themes/readme',
    '/admin/integrations',
    '/admin/scan-jobs',
    '/admin/scan-controls',
    '/admin/unmatched',
    '/admin/edit_filters',
    '/add_game_manual',
)
ADMIN_BOOTSTRAP_ROUTE = '/admin/api/runtime-bootstrap'
ADMIN_REDIRECT_ROUTES = (
    '/admin/library_tools', '/admin/scan_management',
    '/admin/server_logs', '/admin/system_logs', '/admin/server_status_page',
)


def is_admin_redirect_path(path):
    return path in ADMIN_REDIRECT_ROUTES

# Anonymous account pages can move to the same reversible static-shell pilot
# independently of the authenticated member SPA. Existing Flask handlers and
# POST forms remain the rollback path while the new JSON contracts are accepted.
MEMBER_AUTH_STATIC_ROUTES = (
    '/login',
    '/register',
    '/reset_password_request',
)
MEMBER_SETUP_STATIC_ROUTES = (
    '/setup', '/setup/smtp', '/setup/features', '/setup/igdb',
    '/setup/integrations', '/setup/library',
)
MEMBER_AUTH_BOOTSTRAP_ROUTE = '/api/auth/runtime-bootstrap'


def is_member_auth_dynamic_route(path):
    """Match only the single-token confirmation/reset compatibility paths."""
    import re

    return re.fullmatch(r'/(?:confirm|reset_password)/[^/]+', path) is not None


def is_email_confirmation_page_route(path):
    """Match one token segment for the static, read-only confirmation shell."""
    import re

    return re.fullmatch(r'/confirm/[^/]+', path) is not None


def is_library_edit_route(path):
    """Match exactly one compatibility editor path segment."""
    import re
    return re.fullmatch(r'/admin/library/edit/[^/]+', path) is not None


def is_game_edit_route(path):
    """Match exactly one compatibility game editor path segment."""
    import re
    return re.fullmatch(r'/game_edit/[^/]+', path) is not None


def is_local_game_image_route(path):
    """Match the per-game local artwork route without accepting extra segments."""
    import re

    return re.fullmatch(r'/game/[^/]+/local_image/(?:cover|screenshot)', path) is not None


def is_game_image_refresh_route(path):
    """Match one game image-refresh action without extra path components."""
    import re

    return re.fullmatch(r'/refresh_game_images/[^/]+', path) is not None


def is_single_image_upload_route(path):
    """Match one per-game image upload action without extra path components."""
    import re

    return re.fullmatch(r'/upload_image/[^/]+', path) is not None


def is_game_images_edit_route(path):
    """Match exactly one per-game artwork editor path segment."""
    import re
    return re.fullmatch(r'/edit_game_images/[^/]+', path) is not None


def is_numeric_admin_detail(path):
    """Only the newsletter numeric detail URL is eligible for the shell."""
    import re
    return re.fullmatch(r'/admin/newsletter/[0-9]+', path) is not None
