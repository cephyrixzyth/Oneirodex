"""Describe what the server can establish about the browser launch route."""
from __future__ import annotations

NEXT_ACTIONS = {
    'missing_game_file': 'Ask a librarian to attach the game file.',
    'unsupported_archive': 'Ask a librarian for a supported archive or extracted game.',
    'no_browser_core': 'Check the installed cores in Admin → Emulators.',
    'catalog_only': 'Use a compatible companion or external player.',
    'missing_firmware': 'Ask an administrator to install the required firmware.',
    'unknown_platform': 'Check the library platform and available play methods.',
}


def browser_readiness(fields):
    if fields.get('firmware_missing'):
        reason = 'missing_firmware'
    elif fields.get('can_play_in_browser') and fields.get('play_url'):
        reason = 'ready'
    else:
        reason = fields.get('play_blocker') or 'unknown_platform'
    return {'device': 'browser', 'available': reason == 'ready', 'reason': reason,
            'next_action': NEXT_ACTIONS.get(reason, 'Open the game.' if reason == 'ready' else 'Check the game setup.'),
            'core': fields.get('emulator_core') or None}
