"""DB-free boundary tests for storage hardlink path policy."""
from __future__ import annotations

from flask import Flask

from oneirodex.runtime_native.storage_hardlinks import StorageHardlinksData


def test_hardlink_path_policy_uses_configured_roots_without_flask_context(tmp_path):
    app = Flask(__name__)
    library = tmp_path / 'library'
    outside = tmp_path / 'outside'
    app.config.update(
        DATA_FOLDER_GAMES=str(library),
        BASE_FOLDER_POSIX='',
        BASE_FOLDER_WINDOWS='',
        LIBRARY_ROOTS=[{'label': 'Library', 'path': str(library)}],
    )
    data = StorageHardlinksData()

    allowed = data.paths_allowed(
        str(library / 'source.rom'), str(library / 'covers' / 'cover.jpg'), app=app,
    )
    rejected = data.paths_allowed(
        str(outside / 'source.rom'), str(library / 'destination.rom'), app=app,
    )

    assert allowed == (True, None)
    assert rejected[0] is False
    assert rejected[1] == 'Access denied - path outside allowed directories'
