"""Scan locations ("library roots") an operator can point Oneirodex at.

Oneirodex scans whatever it can open as a local path, and that is not the same
thing as "a path on the box the service runs on": an SMB/NFS share, an Unraid
user share, a second internal disk, or an extra Docker bind mount all become
scannable the moment the host — or the container — mounts them. What was
missing was a way to *declare* those mounts, because the folder browser and the
path allowlist both keyed off a single ``BASE_FOLDER_*``.

``ONEIRODEX_LIBRARY_ROOTS`` / ``ONEIRODEX_LIBRARY_ROOTS`` is that declaration. Entries
are separated by ``|`` and each one is an optional ``Label=`` followed by the
path Oneirodex sees:

    ONEIRODEX_LIBRARY_ROOTS=NAS ROMs=/mnt/nas/roms|Archive=/mnt/archive/games

The label is cosmetic (it names the root in the admin folder browser); the path
is what matters. Mounting the share is still the operator's job — see
docs/runbooks/remote-scan-locations.md.
"""

from __future__ import annotations

import os
import re
import sys

ROOT_SEPARATOR = '|'
LABEL_SEPARATOR = '='

# Bounded so a malformed env var cannot turn into thousands of stat() calls
# every time the folder browser opens.
MAX_ROOTS = 32
MAX_PATH_LENGTH = 4096


def _normalize_path(raw: str) -> str:
    """Trim quotes/whitespace and normalize separators without resolving links.

    Symlinks are deliberately left alone: ``is_safe_path`` resolves both the
    candidate and the base, so resolving here as well would only make the
    configured value harder to recognise in logs and in Ops.
    """
    path = (raw or '').strip().strip('"').strip("'")
    if not path:
        return ''
    path = os.path.expanduser(os.path.expandvars(path))
    try:
        return os.path.normpath(path)
    except (OSError, ValueError):
        return path


def _looks_like_path(candidate: str) -> bool:
    """True when text before an ``=`` is really the start of a path, not a label."""
    return bool(re.search(r'[\\/]', candidate)) or candidate.endswith(':')


def same_path(left: str, right: str) -> bool:
    """Do two configured paths name the same directory?

    Normalized on both sides — one may come from an env var the operator typed
    and the other from a default — and case-folded on Windows, where they do
    not differ.
    """
    left, right = _normalize_path(left), _normalize_path(right)
    if os.name == 'nt':
        return left.lower() == right.lower()
    return left == right


def parse_library_roots(raw: str | None) -> list[dict]:
    """Parse ``ONEIRODEX_LIBRARY_ROOTS`` / ``ONEIRODEX_LIBRARY_ROOTS`` into ``[{'label', 'path'}, …]``.

    Unlabelled entries take the last path segment as their label so the picker
    always has something to show. Blank and over-long entries are dropped
    rather than raising — a typo in one root must not stop the app booting.
    """
    if not raw or not isinstance(raw, str):
        return []

    roots: list[dict] = []
    for entry in raw.split(ROOT_SEPARATOR):
        entry = entry.strip()
        if not entry:
            continue

        label, separator, remainder = entry.partition(LABEL_SEPARATOR)
        if separator and not _looks_like_path(label):
            # "Label=" with nothing after it names a root that does not exist.
            # Dropping it beats inventing a path out of the label text.
            if not remainder.strip():
                continue
            label = label.strip()
            path = _normalize_path(remainder)
        else:
            label = ''
            path = _normalize_path(entry)

        if not path or len(path) > MAX_PATH_LENGTH or '\x00' in path:
            continue
        if not label:
            label = os.path.basename(path.rstrip('\\/')) or path

        if any(same_path(path, existing['path']) for existing in roots):
            continue

        roots.append({'label': label, 'path': path})
        if len(roots) >= MAX_ROOTS:
            break

    return roots


def _slugify(label: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', (label or '').lower()).strip('-')
    return slug or 'root'


def _runtime_config(app=None):
    if app is not None:
        return app.config
    flask_module = sys.modules.get('flask')
    if flask_module is not None and flask_module.has_app_context():
        return flask_module.current_app.config
    raise RuntimeError('Library-root configuration requires an app or active Flask context')


def library_roots(app=None) -> list[dict]:
    """Every scan location this install exposes, in picker order.

    The built-in games folder and the OS base folder come first so an install
    that never sets ``ONEIRODEX_LIBRARY_ROOTS`` behaves exactly as it did before;
    declared roots follow in the order they were written. Paths that repeat are
    folded into the first entry that claimed them.
    """
    config = _runtime_config(app)
    base_key = 'BASE_FOLDER_WINDOWS' if os.name == 'nt' else 'BASE_FOLDER_POSIX'

    candidates = [
        {'label': 'Games', 'path': config.get('DATA_FOLDER_GAMES'), 'source': 'DATA_FOLDER_GAMES'},
        {'label': 'Server', 'path': config.get(base_key), 'source': base_key, 'default': True},
    ]
    for root in config.get('LIBRARY_ROOTS') or []:
        candidates.append({
            'label': root.get('label') or '',
            'path': root.get('path') or '',
            'source': 'ONEIRODEX_LIBRARY_ROOTS',
        })

    roots: list[dict] = []
    used_ids: set[str] = set()
    for candidate in candidates:
        path = _normalize_path(candidate.get('path') or '')
        if not path or any(same_path(path, existing['path']) for existing in roots):
            continue

        root_id = _slugify(candidate['label'])
        if root_id in used_ids:
            suffix = 2
            while f'{root_id}-{suffix}' in used_ids:
                suffix += 1
            root_id = f'{root_id}-{suffix}'
        used_ids.add(root_id)

        roots.append({
            'id': root_id,
            'label': candidate['label'] or path,
            'path': path,
            'source': candidate['source'],
            'default': bool(candidate.get('default')),
        })

    if roots and not any(root['default'] for root in roots):
        roots[0]['default'] = True
    return roots


def resolve_library_root(root_id: str | None, app=None) -> dict | None:
    """Look a root up by id, or return the default root when id is blank."""
    roots = library_roots(app)
    if not roots:
        return None
    if not root_id:
        return next((root for root in roots if root['default']), roots[0])
    return next((root for root in roots if root['id'] == root_id), None)


def library_root_paths(app=None) -> list[str]:
    """Just the declared extra paths — what the path allowlist needs to add."""
    config = _runtime_config(app)
    paths = []
    for root in config.get('LIBRARY_ROOTS') or []:
        path = _normalize_path(root.get('path') or '')
        if path and path not in paths:
            paths.append(path)
    return paths


def root_availability(root: dict) -> dict:
    """Probe one root. A dead NFS mount must read as unavailable, not as empty.

    ``os.path.exists`` on a severed mount can raise rather than return False,
    which is exactly the case Ops needs to surface, so the probe is guarded.
    """
    path = root.get('path') or ''
    try:
        exists = os.path.isdir(path)
        readable = exists and os.access(path, os.R_OK)
        writable = exists and os.access(path, os.W_OK)
    except OSError:
        exists = readable = writable = False
    return {**root, 'exists': exists, 'read': readable, 'write': writable}


def resolve_scan_path(folder_path: str | None, root_id: str | None = None, app=None):
    """Resolve a browser-relative folder path against its declared scan location.

    The admin folder browser has always handed back a path relative to the root
    it was browsing, so the join has to happen somewhere; doing it here means
    auto scan and manual scan agree on what an empty path and an absolute path
    each mean. ``os.path.join`` keeps an absolute ``folder_path`` intact, so an
    operator who types a full path still gets exactly that path.

    Returns ``(path, error)``. ``error`` is set when the caller named a root
    that no longer exists — that must fail loudly rather than silently scanning
    the default location.
    """
    # Anything that is not a string is "not specified": a form field only ever
    # yields None or str, so coercing here costs nothing and keeps a stray
    # value from being reported as a root that went missing.
    if not isinstance(root_id, str):
        root_id = ''
    root_id = root_id.strip()

    root = resolve_library_root(root_id, app)
    if root_id and not root:
        return None, 'That scan location is no longer configured.'
    if not root:
        return None, 'No scan location is configured for this OS.'

    folder_path = (folder_path or '').strip()
    if not folder_path:
        return root['path'], None
    return os.path.join(root['path'], folder_path), None
