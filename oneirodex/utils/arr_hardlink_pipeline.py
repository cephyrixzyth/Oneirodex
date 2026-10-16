"""arr → hardlink pipeline: completed qBittorrent items → library hardlinks."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import urljoin

import requests

from oneirodex.utils.arr_connectors import DEFAULT_TIMEOUT, get_arr_config
from oneirodex.utils.event_logging import log_system_event
from oneirodex.utils.hardlinks import apply_hardlink, preview_hardlink
from oneirodex.utils.http_safe import safe_request
from oneirodex.utils.security import (
    get_allowed_base_directories,
    is_safe_path,
    validate_connector_http_url,
)
from oneirodex.utils.runtime_config import get_runtime_config


def _config(config=None):
    if config is not None:
        return config
    active = get_runtime_config()
    if active is not None:
        return active
    from flask import current_app

    return current_app.config


def _legacy_app():
    from flask import current_app

    return current_app._get_current_object()


def pipeline_enabled(*, config=None) -> bool:
    app_config = _config(config)
    return str(app_config.get('ENABLE_ARR_HARDLINK_PIPELINE', '')).lower() in (
        '1', 'true', 'yes', 'on',
    )


def hardlink_helpers_enabled(*, config=None) -> bool:
    app_config = _config(config)
    return str(app_config.get('ENABLE_HARDLINK_HELPERS', '')).lower() in (
        '1', 'true', 'yes', 'on',
    )


def hardlink_apply_allowed(*, config=None) -> bool:
    app_config = _config(config)
    return hardlink_helpers_enabled(config=app_config) and str(
        app_config.get('ALLOW_HARDLINK_APPLY', ''),
    ).lower() in ('1', 'true', 'yes', 'on')


def _qb_session(*, config=None) -> tuple[requests.Session, dict[str, Any]]:
    cfg = get_arr_config(config=config)
    if not cfg['qbittorrent_url']:
        raise RuntimeError('qBittorrent URL is not configured')
    session = requests.Session()
    login = safe_request(
        'POST',
        urljoin(cfg['qbittorrent_url'] + '/', 'api/v2/auth/login'),
        validator=validate_connector_http_url,
        session=session,
        data={
            'username': cfg['qbittorrent_username'],
            'password': cfg['qbittorrent_password'],
        },
        timeout=DEFAULT_TIMEOUT,
    )
    if login.status_code >= 400 or (login.text or '').strip().lower() == 'fails.':
        raise RuntimeError('qBittorrent login failed')
    return session, cfg


def list_completed_torrents(*, limit: int = 50, config=None) -> list[dict[str, Any]]:
    """Return completed torrents with content paths from qBittorrent."""
    session, cfg = _qb_session(config=config)
    resp = safe_request(
        'GET',
        urljoin(cfg['qbittorrent_url'] + '/', 'api/v2/torrents/info'),
        validator=validate_connector_http_url,
        session=session,
        params={'filter': 'completed'},
        timeout=DEFAULT_TIMEOUT,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f'qBittorrent torrents/info failed ({resp.status_code})')
    rows = resp.json() if resp.content else []
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for item in rows[: max(1, min(limit, 200))]:
        content_path = (item.get('content_path') or item.get('save_path') or '').strip()
        name = (item.get('name') or '').strip() or os.path.basename(content_path) or 'torrent'
        out.append({
            'hash': item.get('hash'),
            'name': name,
            'content_path': content_path,
            'save_path': item.get('save_path'),
            'size': item.get('size') or item.get('total_size'),
            'progress': item.get('progress'),
        })
    return out


def parse_remote_path_map(raw: str | None) -> list[tuple[str, str]]:
    """Parse ``ARR_REMOTE_PATH_MAP`` into ordered (remote, local) prefix pairs.

    Format: ``remote=>local`` pairs separated by ``|``, e.g.::

        /downloads=>/storage/downloads|/data/torrents=>/mnt/user/torrents

    ``=>`` rather than ``:`` because Windows paths contain colons, and ``|``
    rather than ``,`` because paths may contain commas.

    Sorted longest-remote-first so a more specific prefix wins over a shorter
    one that also matches.
    """
    pairs: list[tuple[str, str]] = []
    for chunk in (raw or '').split('|'):
        chunk = chunk.strip()
        if not chunk or '=>' not in chunk:
            continue
        remote, _, local = chunk.partition('=>')
        remote, local = remote.strip(), local.strip()
        if remote and local:
            pairs.append((remote, local))
    pairs.sort(key=lambda pair: len(pair[0]), reverse=True)
    return pairs


def _configured_path_map(*, config=None) -> list[tuple[str, str]]:
    app_config = _config(config)
    return parse_remote_path_map(app_config.get('ARR_REMOTE_PATH_MAP'))


def _normalise(path: str) -> str:
    """Compare with forward slashes and no trailing separator."""
    return (path or '').replace('\\', '/').rstrip('/')


def map_remote_path(path: str, mappings: list[tuple[str, str]] | None = None, *, config=None) -> str:
    """Rewrite a download client's path into one this process can actually see.

    The client and Oneirodex usually run in different containers, so
    qBittorrent reports something like ``/downloads/x`` while we have the same
    bytes mounted at ``/storage/downloads/x``. Without this the pipeline stats a
    path that does not exist here and reports "no source file found" — correct
    but baffling, since the file is plainly there.

    Returns ``path`` unchanged when nothing matches, which is the right
    behaviour for the single-container case where no mapping is needed.
    """
    if not path:
        return path
    pairs = _configured_path_map(config=config) if mappings is None else mappings
    if not pairs:
        return path

    candidate = _normalise(path)
    for remote, local in pairs:
        prefix = _normalise(remote)
        # Strip the local side too — a trailing slash in config would otherwise
        # survive into the joined result and mix separators.
        target = local.rstrip('/\\') or local
        if not prefix:
            continue
        # Prefix must end at a separator, so /downloads does not match
        # /downloads-old.
        if candidate == prefix:
            return target
        if candidate.startswith(prefix + '/'):
            remainder = candidate[len(prefix):].lstrip('/')
            return os.path.join(target, *remainder.split('/')) if remainder else target
    return path


def _pick_source_file(content_path: str) -> str | None:
    """If path is a file use it; if directory, pick the largest file (one level deep + walk)."""
    path = os.path.abspath(content_path or '')
    if not path:
        return None
    if os.path.isfile(path):
        return path
    if not os.path.isdir(path):
        return None
    best = None
    best_size = -1
    for root, _dirs, files in os.walk(path):
        for fname in files:
            full = os.path.join(root, fname)
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            if size > best_size:
                best_size = size
                best = full
        # Prefer shallow large files; still walk fully for correctness
    return best


def propose_hardlinks(
    library_dest_dir: str,
    *,
    limit: int = 50,
    torrents: list[dict[str, Any]] | None = None,
    app=None,
) -> dict[str, Any]:
    """Preview hardlinks from completed torrents into a library destination directory."""
    app_config = app.config if app is not None else None
    if not pipeline_enabled(config=app_config):
        raise PermissionError('Arr→hardlink pipeline is disabled')
    if not hardlink_helpers_enabled(config=app_config):
        raise PermissionError('Hardlink helpers are disabled')

    dest_dir = os.path.abspath((library_dest_dir or '').strip())
    if not dest_dir or not os.path.isdir(dest_dir):
        raise ValueError('library_dest_dir must be an existing directory')

    app = app if app is not None else _legacy_app()
    bases = get_allowed_base_directories(app)
    ok_d, err_d = is_safe_path(dest_dir, bases)
    if not ok_d:
        raise PermissionError(err_d or 'Unsafe destination directory')

    items = torrents if torrents is not None else list_completed_torrents(limit=limit, config=app.config)
    proposals: list[dict[str, Any]] = []
    path_map = _configured_path_map(config=app.config)
    for item in items:
        raw_path = item.get('content_path') or ''
        # Rewrite the client's view of the path into ours before touching disk.
        local_path = map_remote_path(raw_path, path_map, config=app.config)
        source = _pick_source_file(local_path)
        if not source:
            reason = 'no source file found'
            if raw_path and not path_map:
                # The overwhelmingly common cause: client and app in separate
                # containers with different mounts. Say so instead of leaving
                # the operator to guess.
                reason = (
                    f'no source file found at {local_path!r} — if your download '
                    'client runs in another container, set ARR_REMOTE_PATH_MAP '
                    '(e.g. "/downloads=>/storage/downloads")'
                )
            elif local_path != raw_path:
                reason = (
                    f'no source file found at {local_path!r} (mapped from '
                    f'{raw_path!r}) — check ARR_REMOTE_PATH_MAP'
                )
            proposals.append({
                **item,
                'source': None,
                'dest': None,
                'mapped_path': local_path if local_path != raw_path else None,
                'preview': {'ok': False, 'would_succeed': False, 'reasons': [reason]},
            })
            continue
        ok_s, err_s = is_safe_path(source, bases)
        if not ok_s:
            proposals.append({
                **item,
                'source': source,
                'dest': None,
                'preview': {'ok': False, 'would_succeed': False, 'reasons': [err_s or 'Unsafe source']},
            })
            continue
        dest = os.path.join(dest_dir, os.path.basename(source))
        preview = preview_hardlink(source, dest)
        proposals.append({
            **item,
            'source': source,
            'dest': dest,
            'preview': preview,
        })
    return {
        'library_dest_dir': dest_dir,
        'apply_allowed': hardlink_apply_allowed(config=app.config),
        'count': len(proposals),
        'proposals': proposals,
    }


def apply_proposals(
    proposals: list[dict[str, Any]],
    *,
    only_ok: bool = True,
    app=None,
) -> dict[str, Any]:
    app_config = app.config if app is not None else None
    if not pipeline_enabled(config=app_config):
        raise PermissionError('Arr→hardlink pipeline is disabled')
    if not hardlink_apply_allowed(config=app_config):
        raise PermissionError(
            'Hardlink apply is disabled. Set ALLOW_HARDLINK_APPLY=true '
            '(and ENABLE_HARDLINK_HELPERS / ENABLE_ARR_HARDLINK_PIPELINE).',
        )
    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    app = app if app is not None else _legacy_app()
    bases = get_allowed_base_directories(app)

    for item in proposals:
        source = (item.get('source') or '').strip()
        dest = (item.get('dest') or '').strip()
        if not source or not dest:
            skipped.append({**item, 'reason': 'missing source/dest'})
            continue
        preview = item.get('preview') or preview_hardlink(source, dest)
        if only_ok and not preview.get('would_succeed'):
            skipped.append({**item, 'reason': 'preview would not succeed', 'preview': preview})
            continue
        ok_s, err_s = is_safe_path(source, bases)
        ok_d, err_d = is_safe_path(dest, bases)
        if not ok_s or not ok_d:
            errors.append({**item, 'error': err_s or err_d or 'Unsafe path'})
            continue
        try:
            result = apply_hardlink(source, dest)
            applied.append(result)
            try:
                log_system_event(
                    f'Arr hardlink: {source} -> {dest}',
                    event_type='audit',
                    event_level='information',
                )
            except Exception:
                pass
        except (ValueError, OSError) as exc:
            errors.append({**item, 'error': str(exc)})

    return {
        'applied_count': len(applied),
        'skipped_count': len(skipped),
        'error_count': len(errors),
        'applied': applied,
        'skipped': skipped,
        'errors': errors,
    }
