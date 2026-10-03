"""Safe rename planning for confirmed game folders (root + top-level media)."""

from __future__ import annotations

import os
import re
from pathlib import Path

from oneirodex.utils.security import is_safe_path_strict

WINDOWS_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
TOP_LEVEL_MEDIA_EXTS = {'.iso', '.img', '.rar', '.zip', '.7z', '.exe'}
LETTER_BUCKET_RE = re.compile(r'^_[a-z#]$', re.IGNORECASE)


def sanitize_fs_name(name: str) -> str:
    cleaned = WINDOWS_FORBIDDEN.sub('', name or '').strip(' .')
    cleaned = re.sub(r'\s+', ' ', cleaned)
    return cleaned or 'Untitled'


def apply_rename_template(template: str, *, title: str, year: str | int | None = None) -> str:
    year_str = '' if year in (None, '') else str(year)
    result = (template or '{title}').replace('{title}', title or '').replace('{year}', year_str)
    result = re.sub(r'\(\s*\)', '', result)
    return sanitize_fs_name(result.strip())


def detect_letter_bucket_parent(game_root: str) -> str | None:
    parent = Path(game_root).parent.name
    if LETTER_BUCKET_RE.match(parent):
        return parent
    return None


def letter_bucket_for_title(title: str) -> str:
    for ch in (title or '').strip():
        if ch.isalpha():
            return f'_{ch.lower()}'
        if ch.isdigit():
            return '_#'
    return '_#'


def build_rename_plan(
    game_root: str,
    *,
    title: str,
    year: str | int | None = None,
    template: str = '{title}',
    rename_root: bool = True,
    rename_top_level_media: bool = False,
    move_letter_bucket: bool = False,
) -> list[dict]:
    """
    Build a list of rename operations (not applied).

    Each item: {kind, from_path, to_path, enabled_default}
    kinds: root_folder | top_level_media | letter_bucket_move
    """
    root = Path(game_root)
    if not root.exists():
        return []

    new_base = apply_rename_template(template, title=title, year=year)
    plan: list[dict] = []

    dest_parent = root.parent
    if move_letter_bucket and detect_letter_bucket_parent(str(root)):
        dest_parent = root.parent.parent / letter_bucket_for_title(new_base)

    new_root = dest_parent / new_base

    if rename_root and new_root.resolve() != root.resolve():
        plan.append({
            'kind': 'root_folder',
            'from_path': str(root),
            'to_path': str(new_root),
        })

    if rename_top_level_media and root.is_dir():
        for entry in root.iterdir():
            if not entry.is_file():
                continue
            if entry.suffix.lower() not in TOP_LEVEL_MEDIA_EXTS:
                continue
            # Only rename when basename loosely matches old folder name
            old_stem = root.name
            if entry.stem.lower().startswith(old_stem.lower()[: min(8, len(old_stem))].lower()) or entry.stem.lower() == old_stem.lower():
                new_name = f'{new_base}{entry.suffix.lower()}'
                # Media stays inside the (possibly renamed) root
                media_parent = new_root if rename_root else root
                plan.append({
                    'kind': 'top_level_media',
                    'from_path': str(entry),
                    'to_path': str(media_parent / new_name),
                })

    return plan


def _same_entry(a: str, b: str) -> bool:
    """True when *a* and *b* name one directory entry (a case-only rename on a
    case-insensitive filesystem: Windows, macOS, most SMB shares)."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def _rebase(path: str, old_root: str, new_root: str) -> str:
    """*path* moved from under *old_root* to under *new_root*, else unchanged."""
    try:
        rel = Path(path).relative_to(old_root)
    except ValueError:
        return path
    return str(Path(new_root) / rel)


def validate_plan_for_game(plan: list[dict], game_root: str) -> list[str]:
    """Reasons *plan* is not a rename of *game_root*; empty when it is.

    The apply route receives the plan back from the browser, so every item is
    checked against the game it claims to rename: the root item must move this
    game's folder within its parent (or into a sibling letter bucket), media
    items must be files directly inside this game's folder that stay inside it,
    and every new name must be one ``sanitize_fs_name`` would produce.
    """
    root = Path(game_root).resolve(strict=False)
    bucketed = detect_letter_bucket_parent(str(root)) is not None
    items = [item for item in plan if isinstance(item, dict)]
    if len(items) != len(plan):
        return ['Malformed rename item']

    new_root = root
    for item in items:
        if item.get('kind') == 'root_folder' and item.get('to_path'):
            new_root = Path(item['to_path']).resolve(strict=False)

    errors: list[str] = []
    for item in items:
        kind = item.get('kind')
        src, dst = item.get('from_path'), item.get('to_path')
        if not src or not dst:
            errors.append('Missing path')
            continue
        src_p = Path(src).resolve(strict=False)
        dst_p = Path(dst).resolve(strict=False)
        if dst_p.name != sanitize_fs_name(dst_p.name):
            errors.append(f'Unsafe new name: {dst_p.name}')
        elif kind == 'root_folder':
            same_parent = dst_p.parent == root.parent
            other_bucket = (
                bucketed
                and dst_p.parent.parent == root.parent.parent
                and LETTER_BUCKET_RE.match(dst_p.parent.name) is not None
            )
            if src_p != root or not (same_parent or other_bucket):
                errors.append('Folder rename does not belong to this game')
        elif kind == 'top_level_media':
            if src_p.parent != root or dst_p.parent not in (root, new_root):
                errors.append('Media rename does not belong to this game')
        else:
            errors.append(f'Unknown rename kind: {kind}')
    return errors


def _is_under(path: str, root: str) -> bool:
    """True when *path* is *root* or inside it (separator-aware, not a prefix match)."""
    try:
        p = Path(path).resolve(strict=False)
        r = Path(root).resolve(strict=False)
    except (OSError, ValueError):
        return False
    return p == r or r in p.parents


def apply_rename_plan(plan: list[dict], allowed_bases: list[str]) -> list[dict]:
    """
    Apply checked rename operations. Returns per-item results with ok/error.
    Caller must only pass items the user checked.

    The root folder is renamed first; once it has moved, every later item whose
    source sat inside the old folder is read from the new one. (Media items are
    planned against the old folder, so without this every media rename after a
    root rename failed with "No such file or directory".)
    """
    ordered = sorted(plan, key=lambda i: 0 if i.get('kind') == 'root_folder' else 1)
    moved: list[tuple[str, str]] = []
    results = []
    for item in ordered:
        src = item.get('from_path')
        dst = item.get('to_path')
        result = {'from_path': src, 'to_path': dst, 'kind': item.get('kind'), 'ok': False, 'error': None}

        if not src or not dst:
            result['error'] = 'Missing path'
            results.append(result)
            continue

        # A root folder that did not move leaves its media items planned into a
        # folder that does not exist; moving them would mkdir it and pull the
        # files out of the game's real folder.
        failed_roots = [
            r['to_path'] for r in results if r.get('kind') == 'root_folder' and not r.get('ok')
        ]
        if item.get('kind') != 'root_folder' and any(_is_under(dst, root) for root in failed_roots):
            result['error'] = 'Skipped: the game folder rename failed'
            results.append(result)
            continue

        for old_root, new_root in moved:
            src = _rebase(src, old_root, new_root)

        safe_src, err_src = is_safe_path_strict(src, allowed_bases)
        safe_dst, err_dst = is_safe_path_strict(dst, allowed_bases)
        if not safe_src:
            result['error'] = err_src or 'Unsafe source path'
            results.append(result)
            continue
        if not safe_dst:
            result['error'] = err_dst or 'Unsafe destination path'
            results.append(result)
            continue

        if os.path.exists(dst) and not _same_entry(src, dst):
            result['error'] = 'Destination already exists'
            results.append(result)
            continue

        try:
            Path(dst).parent.mkdir(parents=True, exist_ok=True)
            os.rename(src, dst)
            result['ok'] = True
            if item.get('kind') == 'root_folder':
                moved.append((src, dst))
        except OSError as exc:
            result['error'] = str(exc)
        results.append(result)

    return results
