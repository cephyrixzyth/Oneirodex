"""The packaged companion needs all three native commands to finish a resumed download."""

import json
import tomllib
from pathlib import Path


TAURI = Path(__file__).resolve().parents[1] / 'clients/desktop/src-tauri'
ARCHIVE_COMMANDS = {'append_file_bytes', 'archive_checkpoint', 'publish_archive_checkpoint'}


def test_archive_commands_belong_only_to_the_full_main_window():
    permissions = {}
    for path in (TAURI / 'permissions').glob('*.toml'):
        for permission in tomllib.loads(path.read_text(encoding='utf-8')).get('permission', []):
            permissions[permission['identifier']] = set(permission['commands'].get('allow', []))

    for filename in ('tauri.conf.json', 'tauri.thin.conf.json'):
        config = json.loads((TAURI / filename).read_text(encoding='utf-8'))
        by_window = {}
        for name in config['app']['security']['capabilities']:
            capability = json.loads((TAURI / 'capabilities' / f'{name}.json').read_text(encoding='utf-8'))
            for window in capability['windows']:
                commands = by_window.setdefault(window, set())
                for permission in capability['permissions']:
                    if permission in permissions:
                        commands.update(permissions[permission])
        assert 'main' in by_window
        for window, commands in by_window.items():
            expected = ARCHIVE_COMMANDS if (filename, window) == ('tauri.conf.json', 'main') else set()
            assert commands & ARCHIVE_COMMANDS == expected
