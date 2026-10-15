"""Framework-independent install manifest payload for the member app."""

from __future__ import annotations

from oneirodex.product import PRODUCT_NAME


def build_app_manifest(site_name: str | None = None) -> dict:
    """Build the browser install manifest using the configured site label."""
    name = str(site_name or '').strip() or PRODUCT_NAME
    return {
        'id': '/library',
        'name': name,
        'short_name': name[:12] or PRODUCT_NAME[:12],
        'description': f'{name} — your household game library',
        'start_url': '/library',
        'scope': '/',
        'display': 'standalone',
        'display_override': ['window-controls-overlay', 'standalone', 'minimal-ui'],
        'orientation': 'any',
        'background_color': '#0b0f14',
        'theme_color': '#0b0f14',
        'categories': ['games', 'entertainment', 'utilities'],
        'icons': [
            {'src': '/static/icons/icon-192.png', 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any'},
            {'src': '/static/icons/gametheca-256.png', 'sizes': '256x256', 'type': 'image/png', 'purpose': 'any'},
            {'src': '/static/icons/gametheca-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any'},
            {'src': '/static/icons/gametheca-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'maskable'},
        ],
        'shortcuts': [
            {'name': 'Library', 'url': '/library'},
            {'name': 'Discover', 'url': '/discover'},
            {'name': 'Big Picture', 'url': '/bigpicture'},
        ],
    }
