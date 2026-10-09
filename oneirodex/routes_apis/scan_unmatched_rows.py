"""Row and glance payload builders for the unmatched-folder API.

Split out of ``routes_apis/scan.py`` in the v11 cycle (H-D.4) as a pure move:
no route lives here, only the pure-ish functions that turn an
``UnmatchedFolder`` (and its matched ``Game``) into the dicts the admin SPA
renders -- disk metadata, why-unmatched reasons, duplicate compare glance.
"""
# /oneirodex/routes_apis/scan.py

from oneirodex import db
from oneirodex.models import UnmatchedFolder, Game, Image
from sqlalchemy import select
from oneirodex.utils.cover_url import resolve_game_cover_url
from oneirodex.utils.duplicate_check import (
    explain_duplicate_match,
    folder_basename,
)
from oneirodex.utils.functions import igdb_platform_id_for
from oneirodex.utils.scan_match_settings import resolve_scan_match_policy


def _soft_name(value) -> str | None:
    text = (value or '').strip() if value is not None else ''
    return text or None


def _iso_dt(value) -> str | None:
    """Null-safe ISO-8601 for DateTime columns (UID-016 compare soft-reads)."""
    if value is None:
        return None
    try:
        return value.isoformat()
    except Exception:
        return None


def _unmatched_disk_meta_fields(folder: UnmatchedFolder) -> dict:
    """Size/mtime for unmatched folder rows — null when unknown (no disk I/O).

    UnmatchedFolder has no size column; failed_time is the only cheap mtime signal.
    Aliases match admin UI pickDiskSizeBytes / pickDiskDate soft-reads.
    """
    failed_iso = _iso_dt(getattr(folder, 'failed_time', None))
    # No denormalized folder size on UnmatchedFolder — key present, value null.
    size_bytes = None
    return {
        'size_bytes': size_bytes,
        'folder_size_bytes': size_bytes,
        'folder_mtime': failed_iso,
        'mtime': failed_iso,
        'modified_at': failed_iso,
        'failed_time': failed_iso,
    }


def _game_disk_meta_fields(game: Game) -> dict:
    """Size/date from existing Game columns for matched_game / duplicate candidates."""
    raw_size = getattr(game, 'size', None)
    size_bytes = int(raw_size) if raw_size is not None else None
    date_identified = _iso_dt(getattr(game, 'date_identified', None))
    date_created = _iso_dt(getattr(game, 'date_created', None))
    # Prefer identify time for compare mtime; fall back to create.
    mtime_iso = date_identified or date_created
    return {
        'size_bytes': size_bytes,
        'date_identified': date_identified,
        'date_created': date_created,
        'folder_mtime': mtime_iso,
        'mtime': mtime_iso,
    }


def _effective_search_name(folder: UnmatchedFolder) -> str | None:
    """Librarian soft search_name, else disk basename (never renames disk)."""
    return _soft_name(getattr(folder, 'search_name', None)) or (
        folder_basename(folder.folder_path) or None
    )


def _rom_language_fields_from_path(path_or_name: str | None) -> dict:
    """Parse dump region/lang from a folder/file path for Unmatched trail honesty."""
    from oneirodex.utils.rom_language import parse_rom_language_tags

    label = folder_basename(path_or_name) if path_or_name else ''
    if not label:
        return {'rom_region': None, 'rom_languages': None}
    parsed = parse_rom_language_tags(label)
    return {
        'rom_region': parsed.get('rom_region'),
        'rom_languages': parsed.get('rom_languages'),
    }


def _suggested_kind_fields(folder: UnmatchedFolder) -> dict:
    """Cheap list/export hint fields denormalized on UnmatchedFolder (no sidecar I/O)."""
    from oneirodex.utils.match_proposal import SUGGESTED_KIND_LABELS

    kind = getattr(folder, 'suggested_kind', None) or None
    if kind:
        kind = str(kind).strip().lower() or None
    label = SUGGESTED_KIND_LABELS.get(kind) if kind else None
    candidate = getattr(folder, 'suggested_candidate_name', None) or None
    if candidate:
        candidate = str(candidate).strip() or None
    return {
        'suggested_kind': kind,
        'suggested_kind_label': label,
        'suggested_candidate_name': candidate,
    }


def _stage_e_fields(folder: UnmatchedFolder) -> dict:
    """Stage E propose-only fields denormalized on UnmatchedFolder (soft-omit when absent)."""
    out = {}
    candidates = getattr(folder, 'stage_e_candidates', None)
    if isinstance(candidates, list) and candidates:
        out['stage_e_candidates'] = candidates
    meta = getattr(folder, 'stage_e', None)
    if isinstance(meta, dict) and meta:
        out['stage_e'] = meta
    return out


def _label_transforms(folder: UnmatchedFolder) -> list:
    """Ordered Stage A0–A14 peels for the disk folder basename (no disk rename)."""
    from oneirodex.utils.game_name_parse import parse_game_label

    label = folder_basename(getattr(folder, 'folder_path', None) or '')
    if not label:
        return []
    return list(parse_game_label(label).get('transforms') or [])


def _why_unmatched_fields(
    folder: UnmatchedFolder,
    kind_fields: dict | None = None,
    *,
    match_reason=None,
    match_score=None,
    use_overrides: bool = False,
    include_transforms: bool = True,
) -> dict:
    """Deterministic one-liner + folder basename for UI explainer (no disk I/O)."""
    from oneirodex.utils.match_proposal import format_why_unmatched

    kind_fields = kind_fields if kind_fields is not None else _suggested_kind_fields(folder)
    name = folder_basename(folder.folder_path) or None
    summary = format_why_unmatched(
        status=getattr(folder, 'status', None),
        match_reason=match_reason if use_overrides else getattr(folder, 'match_reason', None),
        match_score=match_score if use_overrides else getattr(folder, 'match_score', None),
        suggested_kind=kind_fields.get('suggested_kind'),
        suggested_kind_label=kind_fields.get('suggested_kind_label'),
        suggested_candidate_name=kind_fields.get('suggested_candidate_name'),
        folder_name=name,
    )
    out = {
        'folder_name': name,
        'why_unmatched': summary,
        'unmatched_reason': summary,  # alias for UI
        **_rom_language_fields_from_path(getattr(folder, 'folder_path', None)),
    }
    # Peel transforms are CPU-heavy across large lists — skip unless asked.
    if include_transforms:
        out['transforms'] = _label_transforms(folder)
    else:
        out['transforms'] = []
    return out


def _matched_game_payload(game: Game | None, cover_by_uuid: dict | None = None) -> dict | None:
    if game is None:
        return None
    cover_url = None
    if cover_by_uuid is not None:
        cover_img = cover_by_uuid.get(game.uuid)
        try:
            cover_url = resolve_game_cover_url(game, cover_img)
        except Exception:
            cover_url = None
    else:
        cover_url = _cover_for_game(game)
    return {
        'uuid': game.uuid,
        'name': game.name,
        'path': game.full_disk_path,
        'cover_url': cover_url,
        'igdb_id': game.igdb_id,
        'rom_region': getattr(game, 'rom_region', None),
        'rom_languages': getattr(game, 'rom_languages', None),
        'disc_index': getattr(game, 'disc_index', None),
        'disc_count': getattr(game, 'disc_count', None),
        **_game_disk_meta_fields(game),
    }


def _prefetch_matched_game_maps(folders: list) -> tuple[dict, dict]:
    """Batch-load games + cover images for list/export (no N+1)."""
    uuids = list({
        getattr(f, 'matched_game_uuid', None)
        for f in folders
        if getattr(f, 'matched_game_uuid', None)
    })
    games_by_uuid: dict = {}
    cover_by_uuid: dict = {}
    if not uuids:
        return games_by_uuid, cover_by_uuid
    for game in db.session.execute(select(Game).filter(Game.uuid.in_(uuids))).scalars().all():
        games_by_uuid[game.uuid] = game
    for image in db.session.execute(
        select(Image).filter(Image.game_uuid.in_(uuids), Image.image_type == 'cover')
    ).scalars().all():
        cover_by_uuid.setdefault(image.game_uuid, image)
    return games_by_uuid, cover_by_uuid


def _unmatched_list_row(
    folder: UnmatchedFolder,
    library_name,
    platform,
    *,
    games_by_uuid: dict | None = None,
    cover_by_uuid: dict | None = None,
    include_transforms: bool = False,
) -> dict:
    from oneirodex.utils.game_name_parse import parse_game_label
    from oneirodex.utils.game_name_parse import looks_like_patch_package

    kind_fields = _suggested_kind_fields(folder)
    disk_name = folder_basename(getattr(folder, 'folder_path', None) or '') or ''
    parsed_name = parse_game_label(disk_name)
    matched_uuid = getattr(folder, 'matched_game_uuid', None)
    include_matched = bool(getattr(folder, 'status', None) == 'Duplicate' or matched_uuid)
    matched_game = None
    if include_matched and matched_uuid:
        if games_by_uuid is not None:
            matched_game = _matched_game_payload(games_by_uuid.get(matched_uuid), cover_by_uuid)
        else:
            game = db.session.execute(select(Game).filter_by(uuid=matched_uuid)).scalars().first()
            matched_game = _matched_game_payload(game)

    row = {
        'id': folder.id,
        'folder_path': folder.folder_path,
        'status': folder.status,
        'library_uuid': getattr(folder, 'library_uuid', None),
        'library_name': library_name,
        'platform_name': platform.name if platform else '',
        'platform_id': igdb_platform_id_for(platform),
        'matched_game_uuid': matched_uuid,
        'match_reason': getattr(folder, 'match_reason', None),
        'match_score': getattr(folder, 'match_score', None),
        'search_name': _soft_name(getattr(folder, 'search_name', None)),
        'display_name': _soft_name(getattr(folder, 'display_name', None)),
        'suggested_search_name': (parsed_name.get('cleaned_name') or '').strip() or None,
        'update_folder_hint': bool(parsed_name.get('update_folder_hint')),
        'is_bare_update_package': bool(
            parsed_name.get('is_bare_update_package') or looks_like_patch_package(disk_name)
        ),
        'update_match_reason': parsed_name.get('update_match_reason'),
        'matched_game': matched_game if include_matched else None,
        # UX-C5 feedback state. Without these the triage UI cannot show that a
        # row is already flagged, so an operator has no way to see their own
        # earlier judgement — or to clear one set by mistake.
        'bad_match_reason': getattr(folder, 'bad_match_reason', None),
        'bad_match_note': getattr(folder, 'bad_match_note', None),
    }
    row.update(_unmatched_disk_meta_fields(folder))
    row.update(kind_fields)
    row.update(_why_unmatched_fields(
        folder,
        kind_fields,
        include_transforms=include_transforms,
    ))
    row.update(_stage_e_fields(folder))
    return row


def _cover_for_game(game) -> str | None:
    if game is None:
        return None
    cover = db.session.execute(
        select(Image).filter_by(game_uuid=game.uuid, image_type='cover').limit(1)
    ).scalars().first()
    try:
        return resolve_game_cover_url(game, cover)
    except Exception:
        return None


def _clone_parent_for_folder(folder: UnmatchedFolder, matched_game: Game | None) -> str | None:
    """Parent set name when a reference DAT marks this folder's title as a clone (1G1R)."""
    try:
        from oneirodex.utils.set_completion import clone_parent_for

        platform = getattr(getattr(matched_game, 'library', None), 'platform', None) if matched_game else None
        platform = getattr(platform, 'name', platform)
        parent = clone_parent_for(
            library_platform=platform,
            name=folder_basename(folder.folder_path) or None,
        )
        return parent or None
    except Exception:  # noqa: BLE001 -- a glance field never breaks the row
        return None


def _duplicate_compare_payload(folder: UnmatchedFolder, matched_game: Game | None) -> dict:
    """Build UI glance fields for a Duplicate unmatched row."""
    candidates = []
    match_reason = getattr(folder, 'match_reason', None)
    match_score = getattr(folder, 'match_score', None)

    clone_of = None
    if matched_game is not None:
        dupe_thr = resolve_scan_match_policy().get('dupe_title_threshold')
        explanation = explain_duplicate_match(
            matched_game,
            folder.folder_path or '',
            folder_basename(folder.folder_path),
            title_threshold=dupe_thr,
        )
        if match_reason is None:
            match_reason = explanation.get('match_reason')
        if match_score is None:
            match_score = explanation.get('match_score')
        # 1G1R (INSP-5): if an uploaded DAT lists this dump as a clone of the
        # matched game's title, say so -- advisory, nothing is marked on it.
        clone_of = _clone_parent_for_folder(folder, matched_game)
        if clone_of and match_reason in (None, 'title_vs_folder', 'title_vs_library_name'):
            match_reason = 'clone_of_owned_parent'
        candidates.append({
            'uuid': matched_game.uuid,
            'id': matched_game.id,
            'name': matched_game.name,
            'cover_url': _cover_for_game(matched_game),
            'path': matched_game.full_disk_path,
            'igdb_id': matched_game.igdb_id,
            'match_reason': match_reason,
            'match_score': match_score,
            **_game_disk_meta_fields(matched_game),
        })

    folder_title = (
        _soft_name(getattr(folder, 'display_name', None))
        or _soft_name(getattr(folder, 'search_name', None))
        or folder_basename(folder.folder_path)
        or folder.folder_path
    )
    kind_fields = _suggested_kind_fields(folder)
    why_fields = _why_unmatched_fields(
        folder,
        kind_fields,
        match_reason=match_reason,
        match_score=match_score,
        use_overrides=True,
    )
    folder_disk = _unmatched_disk_meta_fields(folder)
    return {
        'id': folder.id,
        'clone_of': clone_of,
        'folder_path': folder.folder_path,
        'status': folder.status,
        'library_uuid': folder.library_uuid,
        'matched_game_uuid': getattr(folder, 'matched_game_uuid', None),
        'match_reason': match_reason,
        'match_score': match_score,
        'search_name': _soft_name(getattr(folder, 'search_name', None)),
        'display_name': _soft_name(getattr(folder, 'display_name', None)),
        'matched_game': _matched_game_payload(matched_game),
        **folder_disk,
        **kind_fields,
        **why_fields,
        **_stage_e_fields(folder),
        'titles': [
            {
                'role': 'unmatched_folder',
                'uuid': None,
                'id': None,
                'name': folder_title,
                'cover_url': None,
                'path': folder.folder_path,
                'igdb_id': None,
                **folder_disk,
            },
            *[
                {
                    'role': 'library_game',
                    **c,
                }
                for c in candidates
            ],
        ],
        'candidates': candidates,
    }
