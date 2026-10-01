"""Helpers for serving static assets outside the WSGI bridge."""

from __future__ import annotations

from pathlib import Path

from oneirodex.utils.library_paths import STATIC_OVERRIDES, relocated_library_dir


#: Library folders holding members' private files, or files another route
#: serves with its own checks (saves, attachments, extracted ROMs, the
#: companion's command queues). Never served as static files.
PRIVATE_LIBRARY_FOLDERS = frozenset({
    'saves', 'client_commands', 'client_lifecycle', 'wanted_updates', 'rom_cache',
    'chat-attachments', 'mods', 'cheats', 'zips', 'assists', 'temp_theme', 'save_paths',
})
#: Served only to a signed-in member: operator-supplied firmware for browser play.
MEMBER_LIBRARY_FOLDERS = frozenset({'bios'})


def _static_parts(url_path: str) -> list[str]:
    return [p for p in url_path[len('/static/'):].replace('\\', '/').split('/') if p not in ('', '.')]


def library_access(url_path: str) -> str:
    """``'public'``, ``'member'`` or ``'private'`` for a /static/... URL.

    Classified on normalised, case-folded segments, so no other spelling of a
    private folder slips through (a case-insensitive disk would serve it).
    """
    if not url_path.startswith('/static/'):
        return 'public'
    parts = _static_parts(url_path)
    if len(parts) < 2 or parts[0].casefold() != 'library':
        return 'public'
    folder = parts[1].casefold()
    if folder in PRIVATE_LIBRARY_FOLDERS:
        return 'private'
    if folder in MEMBER_LIBRARY_FOLDERS:
        return 'member'
    return 'public'


def resolve_static_path(static_root: Path, url_path: str) -> Path | None:
    """Resolve a /static/... URL to a file under static_root, or None if invalid."""
    if not url_path.startswith('/static/'):
        return None
    return _resolve_under(static_root, url_path[len('/static/'):])


def resolve_served_static(static_root: Path, url_path: str) -> Path | None:
    """The file a /static/... URL serves, following a moved library.

    With ``ONEIRODEX_LIBRARY_DIR`` set, ``/static/library/…`` comes only from
    that folder, and any other static path prefers an override written under
    ``<library>/static-overrides/`` to the shipped file (see library_paths).
    """
    relocated = relocated_library_dir()
    if relocated and url_path.startswith('/static/'):
        # Classify on normalised segments: '/static//library/x',
        # '/static/./library/x' and (on a case-insensitive disk)
        # '/static/LIBRARY/x' all name the install's library folder too.
        parts = _static_parts(url_path)
        if parts and parts[0].casefold() == 'library':
            return _resolve_under(Path(relocated), '/'.join(parts[1:]))
        override = _resolve_under(Path(relocated) / STATIC_OVERRIDES, '/'.join(parts))
        if override is not None and override.is_file():
            return override
    return resolve_static_path(static_root, url_path)


def serve_relocated_static(app) -> None:
    """Make Flask's own /static/ view follow a moved library, as asgi.py does.

    Production serves /static/ in asgi.py before Flask sees it; this keeps the
    Flask view (dev server, test client) returning the same files.
    """
    from flask import abort, send_file

    def static(filename):
        path = resolve_served_static(Path(app.static_folder or ''), f'/static/{filename}')
        if path is None or not path.is_file():
            abort(404)
        return send_file(path, max_age=app.get_send_file_max_age(str(path)))

    app.view_functions['static'] = static


def _resolve_under(root: Path, rel: str) -> Path | None:
    rel = rel.lstrip('/')
    if not rel or '..' in rel.split('/'):
        return None
    root = root.resolve()
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate
