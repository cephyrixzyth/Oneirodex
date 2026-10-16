"""Shared game-details payload for SPA API and (legacy) Jinja."""

from __future__ import annotations

import os
import re

from sqlalchemy import and_, exists, select

from oneirodex.runtime_native.db_session import native_db as db
from oneirodex.models import (
    GameExtra,
    GameUpdate,
    UserGameProgress,
    get_status_info,
    user_favorites,
    user_game_status,
)
from oneirodex.utils.client_lifecycle import load_lifecycle_map
from oneirodex.utils.cover_url import resolve_game_cover_url
from oneirodex.utils.functions import format_size, get_url_icon, sanitize_string_input
from oneirodex.utils.lifecycle import web_lifecycle_fields
from oneirodex.utils.play_url import browse_play_fields, library_platform_key
from oneirodex.utils.role_catalog import normalize_role, role_at_least
from oneirodex.utils.runtime_config import get_runtime_config
from oneirodex.utils.static_urls import static_asset_url
from oneirodex.utils.rom_language import preferred_locale_matches
from oneirodex.utils.multi_disc import disc_browse_fields
from oneirodex.utils.secondary_scrapers import game_card_flags
from oneirodex.utils.steam_store_specs import public_store_specs


def _config_value(key: str, default=None):
    config = get_runtime_config()
    if config is not None:
        return config.get(key, default)
    return os.getenv(key, default)


def _rom_patch_apply_enabled() -> bool:
    return str(_config_value('ENABLE_ROM_PATCH_APPLY', 'true')).lower() in (
            '1',
            'true',
            'yes',
            'on',
    )


def _rom_ai_translate_enabled() -> bool:
    return str(_config_value('ENABLE_ROM_AI_TRANSLATE', 'true')).lower() in (
            '1',
            'true',
            'yes',
            'on',
    )


def _patch_catalog_enabled() -> bool:
    return str(_config_value('ENABLE_PATCH_CATALOG', 'true')).lower() in (
            '1',
            'true',
            'yes',
            'on',
    )


def _ai_target_lang_hint(preferred_locale: str | None) -> str:
    pref = (preferred_locale or 'en-US').strip().lower() or 'en-us'
    if pref.startswith('en'):
        return 'en'
    if pref.startswith('ja'):
        return 'ja'
    if pref.startswith('es'):
        return 'es'
    if pref.startswith('fr'):
        return 'fr'
    if pref.startswith('de'):
        return 'de'
    return pref.split('-')[0] or 'en'


_YOUTUBE_ID_PATTERNS = (
    r'youtube\.com/watch\?v=([a-zA-Z0-9_-]{6,})',
    r'youtube\.com/embed/([a-zA-Z0-9_-]{6,})',
    r'youtu\.be/([a-zA-Z0-9_-]{6,})',
)
_DIRECT_VIDEO_SUFFIXES = ('.mp4', '.webm', '.ogv', '.ogg')


def _parse_video_urls(raw) -> list[str]:
    """Normalize Game.video_urls (CSV string or list) into a clean URL list."""
    if raw is None or raw == '':
        return []
    if isinstance(raw, list):
        return [str(u).strip() for u in raw if str(u).strip()]
    if isinstance(raw, str):
        return [part.strip() for part in raw.split(',') if part.strip()]
    return []


def _is_honest_http_url(url: str) -> bool:
    """True for http(s) URLs that are not markup (no Steam widget HTML)."""
    if not url or '<' in url or '>' in url:
        return False
    lowered = url.strip().casefold()
    return lowered.startswith('http://') or lowered.startswith('https://')


def _is_direct_video_url(url: str) -> bool:
    path = url.split('?', 1)[0].casefold()
    return path.endswith(_DIRECT_VIDEO_SUFFIXES)


def youtube_embed_url(video_url: str) -> str | None:
    """YouTube watch/short/embed → ``https://www.youtube.com/embed/<id>``.

    Returns None when the string is not a YouTube watch/embed URL. Does not
    invent a trailer from a Steam App ID, and does not pass through widget HTML.
    """
    if not _is_honest_http_url(video_url or ''):
        return None
    for pattern in _YOUTUBE_ID_PATTERNS:
        match = re.search(pattern, video_url, flags=re.IGNORECASE)
        if match:
            return f'https://www.youtube.com/embed/{match.group(1)}'
    return None


def _youtube_embed_url(video_url: str) -> str | None:
    embed = youtube_embed_url(video_url)
    if embed:
        return embed
    if video_url and ('youtube.com' in video_url or 'youtu.be' in video_url):
        return video_url
    return None


def first_trailer_embed_url(game) -> str | None:
    """First honest trailer URL for a browse tile, or None.

    Prefers a YouTube embed. Direct ``.mp4`` / ``.webm`` files are accepted so
    the tile can play a muted ``<video>``. Steam widget HTML and unknown pages
    are skipped. Fill-only: never synthesised from ``steam_app_id``.
    """
    for url in _parse_video_urls(getattr(game, 'video_urls', None)):
        if not _is_honest_http_url(url):
            continue
        embed = youtube_embed_url(url)
        if embed:
            return embed
        if _is_direct_video_url(url):
            return url
    return None


def browse_trailer_fields(game) -> dict:
    """Fill-only trailer signal for GameCard hover. Omit when there is none."""
    embed = first_trailer_embed_url(game)
    if not embed:
        return {}
    return {'trailer_embed_url': embed}


def _classify_extra_type(extra) -> str:
    kind = (getattr(extra, 'extra_kind', None) or '').strip().lower()
    if kind in ('dlc', 'extra', 'manual', 'translation_patch', 'disc'):
        return kind
    name = os.path.basename(getattr(extra, 'file_path', None) or '').lower()
    if 'dlc' in name:
        return 'dlc'
    if kind:
        return kind
    return 'extra'


def _extra_on_server(extra) -> bool:
    path = getattr(extra, 'file_path', None) or ''
    if not path:
        return False
    try:
        return os.path.exists(path)
    except OSError:
        return False


def local_image_on_disk(raw: str) -> bool:
    """Is the cached file actually on disk?

    `is_downloaded` is a database flag, and a flag can outlive the file it
    describes. The 2026-08-31 rename cutover repointed LIBRARY_HOST_PATH at a
    fresh directory: 36,481 rows still said downloaded, 65 files were actually
    present, and every page happily emitted /static/library/images/<name> for
    art that had been left behind at the old path. A details page laid out a
    1521x598 broken image as its backdrop and nothing anywhere reported a
    problem, because nothing ever asked the filesystem.

    Fails OPEN: when UPLOAD_FOLDER is not configured we cannot check, and
    hiding every image because of that would be worse than trusting the flag.
    """
    if not raw:
        return False
    folder = _config_value('UPLOAD_FOLDER') or ''
    if not folder:
        return True
    try:
        return os.path.exists(os.path.join(folder, 'images', os.path.basename(raw)))
    except OSError:
        return False


# Image kinds that are wide, title-free art, best first.
#
# `hero` and `fanart` are made for this — 16:9 key art with no wordmark burned
# in. `logo` and `box` are deliberately absent: both carry the title, which is
# the thing a backdrop must not repeat. A screenshot is the fallback because
# every title that has any art at all tends to have one, and gameplay behind
# gameplay reads as atmosphere rather than as a mistake.
BACKDROP_KINDS = ('hero', 'fanart')


def _servable_image_url(img) -> str | None:
    """A URL for an image row, or None when we cannot actually serve it.

    Same rule the screenshot list follows: a row whose file was never downloaded
    and has no remote source is not art we can show, and emitting its static
    path only produces a 404.
    """
    raw = getattr(img, 'url', None) or ''
    download_url = getattr(img, 'download_url', None) or ''
    if download_url.startswith('//'):
        download_url = f'https:{download_url}'
    if raw.startswith(('http://', 'https://', '/')):
        return raw
    if bool(getattr(img, 'is_downloaded', False)) and raw and local_image_on_disk(raw):
        return _static_image_url(raw)
    if download_url.startswith(('http://', 'https://')):
        return download_url
    return None


def _static_image_url(raw: str) -> str:
    """Build a static image URL in both Flask requests and native ASGI routes."""
    return static_asset_url(f'library/images/{raw}')


def _pick_backdrop(candidates: dict, screenshots: list) -> str | None:
    """Best available wide art, or None to leave the page on its flat surface."""
    for kind in BACKDROP_KINDS:
        if candidates.get(kind):
            return candidates[kind]
    return screenshots[0] if screenshots else None


def _save_paths(game):
    try:
        from oneirodex.utils.save_paths import save_paths_for

        return save_paths_for(game)
    except Exception:  # noqa: BLE001 -- a row never breaks the details page
        return None


def build_game_details_payload(game, user) -> dict:
    """JSON-safe details payload. Disk paths only for admin viewers."""
    user_id = getattr(user, 'id', None) if user is not None else None
    updates = db.session.execute(
        select(GameUpdate).filter_by(game_uuid=game.uuid)
    ).scalars().all()
    extras = db.session.execute(
        select(GameExtra).filter_by(game_uuid=game.uuid)
    ).scalars().all()
    lifecycle_map = load_lifecycle_map(user_id)

    preferred_locale = 'en-US'
    prefs = getattr(user, 'preferences', None) if user is not None else None
    if prefs is not None:
        preferred_locale = getattr(prefs, 'preferred_game_locale', None) or 'en-US'

    rom_languages_raw = getattr(game, 'rom_languages', None) or ''
    rom_lang_list = [part.strip() for part in rom_languages_raw.split(',') if part.strip()]
    rom_region = getattr(game, 'rom_region', None)
    locale_matches = preferred_locale_matches(
        preferred_locale, rom_lang_list, region=rom_region
    )

    translation_patches = []
    for extra in extras:
        if getattr(extra, 'extra_kind', None) != 'translation_patch':
            continue
        translation_patches.append(
            {
                'uuid': extra.uuid,
                'label': os.path.basename(extra.file_path or '') or extra.uuid[:8],
                'patch_format': getattr(extra, 'patch_format', None),
                'target_language': getattr(extra, 'target_language', None),
                'source_url': getattr(extra, 'source_url', None),
                'download_url': f'/download_other/extra/{game.uuid}/{extra.uuid}',
            }
        )

    needs_translation = locale_matches is False
    patch_apply_enabled = _rom_patch_apply_enabled()
    has_translation_patch = bool(translation_patches)
    ai_translate_enabled = _rom_ai_translate_enabled()
    show_ai_translate = ai_translate_enabled and needs_translation and not has_translation_patch
    show_translations_block = (
        needs_translation or bool(translation_patches) or show_ai_translate
    )
    ai_service_url = (_config_value('RETROARCH_AI_SERVICE_URL') or '').strip() or None

    cover_image = None
    screenshots = []
    # Wide art for the page background — see `_servable_image_url` and the
    # BACKDROP_KINDS note below.
    backdrop_candidates: dict[str, str] = {}
    for img in game.images.all():
        image_type = getattr(img, 'image_type', None)
        if image_type in BACKDROP_KINDS and image_type not in backdrop_candidates:
            url = _servable_image_url(img)
            if url:
                backdrop_candidates[image_type] = url
        if image_type == 'cover' and cover_image is None:
            cover_image = img
        elif image_type == 'screenshot':
            raw = getattr(img, 'url', None) or ''
            download_url = getattr(img, 'download_url', None) or ''
            if download_url.startswith('//'):
                download_url = f'https:{download_url}'
            is_downloaded = bool(getattr(img, 'is_downloaded', False))
            if raw.startswith(('http://', 'https://', '/')):
                screenshots.append(raw)
            elif is_downloaded and raw and local_image_on_disk(raw):
                screenshots.append(_static_image_url(raw))
            elif download_url.startswith(('http://', 'https://')):
                # Pending / failed local download — still show remote IGDB art
                screenshots.append(download_url)
            # No final `elif raw:` fallback.
            #
            # It used to emit /static/library/images/<name> for a row that is
            # not downloaded and has no remote URL to fall back to — i.e. for a
            # file that is not on disk. Every one of those 404s, so a title
            # whose screenshots had failed to download rendered a Screenshots
            # section full of broken-image glyphs, and there was no way for the
            # page to tell that apart from a title with real art: the section is
            # shown when the list is non-empty, and the list was non-empty.
            #
            # An image row we cannot serve contributes nothing, so it is not
            # listed. A title with no servable screenshots now has an empty list
            # and the section correctly does not render at all.
    platform_key = library_platform_key(game)
    platform_label = None
    library = getattr(game, 'library', None)
    platform = getattr(library, 'platform', None) if library is not None else None
    if platform is not None:
        platform_label = getattr(platform, 'value', None) or platform_key

    steam_app_id = getattr(game, 'steam_app_id', None)
    steam_url = getattr(game, 'steam_url', None) or None
    if steam_app_id and not steam_url:
        steam_url = f'https://store.steampowered.com/app/{int(steam_app_id)}'

    is_favorite = False
    user_status = None
    status_icon = 'fa-circle'
    status_label = 'No Status'
    if user_id:
        is_favorite = bool(
            db.session.execute(
                select(
                    exists().where(
                        and_(
                            user_favorites.c.user_id == user_id,
                            user_favorites.c.game_uuid == game.uuid,
                        )
                    )
                )
            ).scalar()
        )
        status_row = db.session.execute(
            select(user_game_status.c.status).where(
                and_(
                    user_game_status.c.user_id == user_id,
                    user_game_status.c.game_uuid == game.uuid,
                )
            )
        ).first()
        if status_row:
            user_status = status_row[0]
        status_info = get_status_info(user_status)
        status_icon = status_info['icon']
        status_label = status_info['label']

    playtime = {
        'total_seconds': 0,
        'session_count': 0,
        'last_played_at': None,
    }
    if user_id:
        progress = db.session.execute(
            select(UserGameProgress).filter_by(user_id=user_id, game_uuid=game.uuid)
        ).scalars().first()
        if progress:
            playtime = {
                'total_seconds': int(progress.total_seconds or 0),
                'session_count': int(progress.session_count or 0),
                'last_played_at': (
                    progress.last_played_at.isoformat()
                    if progress.last_played_at
                    else None
                ),
            }

    video_urls = _parse_video_urls(getattr(game, 'video_urls', None))
    trailers = []
    for url in video_urls:
        embed = _youtube_embed_url(url)
        trailers.append({
            'url': url,
            'embed_url': embed or url,
            'provider': 'youtube' if embed else 'unknown',
        })

    youtube_demo_url = None
    if not trailers:
        for url_row in game.urls:
            url_type = (getattr(url_row, 'url_type', None) or '').lower()
            href = getattr(url_row, 'url', None) or ''
            if 'youtube' in url_type or 'youtu.be' in href or 'youtube.com' in href:
                youtube_demo_url = href
                break

    extras_list = []
    for extra in extras:
        extras_list.append({
            'uuid': extra.uuid,
            'type': _classify_extra_type(extra),
            'name': os.path.basename(extra.file_path or '') or extra.uuid[:8],
            'on_server': _extra_on_server(extra),
            'extra_kind': getattr(extra, 'extra_kind', None),
            'disc_index': getattr(extra, 'disc_index', None),
            'download_url': f'/download_other/extra/{game.uuid}/{extra.uuid}',
        })

    disc_fields = disc_browse_fields(game, extras=extras)

    role = normalize_role(getattr(user, 'role', None) if user is not None else None)
    is_admin = role == 'admin'
    # The page has read `game.can_edit` since the cheats panel shipped, but the
    # payload never sent it -- so every librarian control on Details (cheats,
    # mods, the headset record) was gated on `undefined` and could not appear.
    # Librarian or above, the same rule the routes behind those controls apply.
    can_edit = role_at_least(role, 'librarian')
    # Librarians/admins who can Edit Images also see full server disk paths.
    show_disk_paths = bool(user is not None and role_at_least(role, 'librarian'))
    payload = {
        'id': game.id,
        'uuid': game.uuid,
        'igdb_id': game.igdb_id,
        'name': game.name,
        'summary': game.summary,
        'storyline': game.storyline,
        'cover_url': resolve_game_cover_url(game, cover_image),
        'local_version': getattr(game, 'local_version', None),
        'remote_version_summary': getattr(game, 'remote_version_summary', None),
        'aggregated_rating': game.aggregated_rating,
        'aggregated_rating_count': game.aggregated_rating_count,
        'rating': game.rating,
        'rating_count': game.rating_count,
        'total_rating': game.total_rating,
        'total_rating_count': game.total_rating_count,
        'first_release_date': (
            game.first_release_date.isoformat() if game.first_release_date else None
        ),
        'date_identified': (
            game.date_identified.isoformat() if game.date_identified else None
        ),
        'last_updated': (
            game.last_updated.isoformat() if game.last_updated else None
        ),
        'slug': game.slug,
        'status': game.status.value if game.status else None,
        'category': game.category.value if game.category else None,
        'item_kind': getattr(game, 'item_kind', None) or 'game',
        'content_kind': getattr(game, 'item_kind', None) or 'game',
        'url_igdb': game.url_igdb,
        'url': game.url,
        # Frontend field map: video_urls (string list) + trailers (structured)
        'video_urls': video_urls,
        'trailers': trailers,
        'has_trailers': bool(trailers),
        'youtube_demo_url': youtube_demo_url,
        'genres': [genre.name for genre in game.genres],
        'game_modes': [mode.name for mode in game.game_modes],
        'themes': [theme.name for theme in game.themes],
        'platforms': [platform.name for platform in game.platforms],
        'player_perspectives': [p.name for p in game.player_perspectives],
        'developer': game.developer.name if game.developer else None,
        'publisher': game.publisher.name if game.publisher else None,
        'size': format_size(game.size),
        'size_bytes': int(game.size or 0),
        'times_downloaded': game.times_downloaded,
        'steam_app_id': steam_app_id,
        'steam_url': steam_url if steam_url and steam_url != 'Not available' else None,
        'hltb_id': game.hltb_id,
        'hltb_main_story': game.hltb_main_story,
        'hltb_main_extra': game.hltb_main_extra,
        'hltb_completionist': game.hltb_completionist,
        'hltb_all_styles': game.hltb_all_styles,
        'freshness_status': getattr(game, 'freshness_status', None),
        'freshness_confidence': getattr(game, 'freshness_confidence', None),
        'rom_region': rom_region,
        'rom_languages': getattr(game, 'rom_languages', None),
        'store_specs': public_store_specs(getattr(game, 'store_specs', None)),
        'has_english': getattr(game, 'has_english', None),
        'disc_index': disc_fields.get('disc_index'),
        'disc_count': disc_fields.get('disc_count'),
        'discs': disc_fields.get('discs') or [],
        'is_multi_disc': disc_fields.get('is_multi_disc'),
        'preferred_game_locale': preferred_locale,
        'preferred_locale_matches': locale_matches,
        'needs_translation': needs_translation,
        'show_translations_block': show_translations_block,
        'translation_patches': translation_patches,
        'has_translation_patch': has_translation_patch,
        'translation_howto_url': '/help#translations',
        'rom_patch_apply_enabled': patch_apply_enabled,
        'patch_catalog_enabled': _patch_catalog_enabled(),
        'rom_ai_translate': {
            'enabled': ai_translate_enabled,
            'show_panel': show_ai_translate,
            'service_url_hint': ai_service_url,
            'target_lang': _ai_target_lang_hint(preferred_locale),
            'runbook_url': '/help#translations',
            'note': (
                'Live OCR/MT overlay via RetroArch AI Service — gist quality, not a permanent patch. '
                'Browser WebRetro cannot use this; companion/native RetroArch only.'
            ),
        },
        'offline_translate_status': 'unsupported',
        'library_uuid': game.library_uuid,
        'library_platform': platform_key,
        'library_platform_label': platform_label,
        'updates_count': len(updates),
        'extras_count': len(extras),
        'extras': extras_list,
        'nfo_content': (
            sanitize_string_input(game.nfo_content, 10000) if game.nfo_content else None
        ),
        'urls': [
            {
                'type': url.url_type,
                'url': url.url,
                'icon': get_url_icon(url.url_type, url.url),
            }
            for url in game.urls
        ],
        'screenshots': screenshots,
        # Wide art for the page background. Never the cover: a cover carries the
        # title, and a title rendered huge and blurred behind the same title in
        # readable type is the page arguing with itself.
        'backdrop_url': _pick_backdrop(backdrop_candidates, screenshots),
        'screenshot_count': len(screenshots),
        'is_favorite': is_favorite,
        'user_status': user_status,
        'status_icon': status_icon,
        'status_label': status_label,
        'playtime': playtime,
        'is_admin': is_admin,
        'can_edit': can_edit,
        **browse_play_fields(game),
        **game_card_flags(game),
        # INSP-40 -- headset records behind the ways-to-play VR row (deep links only)
        'vr_profiles': [row.to_dict() for row in (getattr(game, 'vr_profiles', None) or [])],
        # INSP-1 -- where the saves live (templated paths; the companion expands them)
        'save_paths': _save_paths(game),
        **web_lifecycle_fields(
            game,
            updates_count=len(updates),
            user_id=user_id,
            client_state=lifecycle_map.get(game.uuid),
        ),
    }
    if show_disk_paths:
        disk = getattr(game, 'full_disk_path', None) or None
        payload['full_disk_path'] = disk
        payload['server_path'] = disk
    return payload
