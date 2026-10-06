# /oneirodex/routes_admin_ext/images.py
import os
from datetime import datetime, timezone

from oneirodex.utils.api_response import api_error, api_ok
from flask import render_template, request, jsonify, current_app, url_for
from flask_login import login_required
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import Game, Image
from oneirodex.schemas.admin_images import ApplyCoverBody, CoverSearchBody, GenerateArtworkBody
from oneirodex.utils.auth import admin_required
from oneirodex.utils.cover_art_studio import apply_pack_to_game, save_pack
from oneirodex.utils.functions import download_stored_image
from oneirodex.utils.cover_selection import (
    batch_apply_covers,
    batch_search_covers,
    image_save_path_status,
    resolve_policy,
    search_cover_candidates,
)
from oneirodex.utils.image_kinds import (
    IMAGE_KIND_ORDER,
    image_kinds_error_message,
    parse_image_kind,
)
from oneirodex.utils.validation import validate_body
from . import admin2_bp


@admin2_bp.route('/admin/images', methods=['GET'])
@login_required
@admin_required
def images_page():
    """Shell for the React image queue and artwork management page."""
    return render_template('admin/admin_images.html')


# The /admin/api/image_queue_list endpoint below stays — it is what the React
# image queue reads.


def _image_status(img):
    """Classify an image row for the admin queue UI (pending/downloaded/failed)."""
    if img.is_downloaded:
        return 'downloaded'
    if img.last_error:
        return 'failed'
    return 'pending'


@admin2_bp.route('/admin/api/image_queue_list')
@login_required
@admin_required
def image_queue_list():
    """Get paginated list of images in queue.

    Query: status, type|kind (all | cover|screenshot|box|cart|disc|logo|hero|fanart).
    """
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    status_filter = request.args.get('status', 'all')  # all, pending, downloaded, failed
    raw_kind = request.args.get('kind') or request.args.get('type') or 'all'
    try:
        type_filter = parse_image_kind(raw_kind, default=None, allow_all=True)
    except ValueError:
        return api_error(image_kinds_error_message(), code='bad_request')

    query = select(Image).join(Game)

    if status_filter == 'pending':
        query = query.filter(Image.is_downloaded.is_(False), Image.last_error.is_(None))
    elif status_filter == 'failed':
        query = query.filter(Image.is_downloaded.is_(False), Image.last_error.isnot(None))
    elif status_filter == 'downloaded':
        query = query.filter(Image.is_downloaded.is_(True))

    if type_filter != 'all':
        query = query.filter(Image.image_type == type_filter)

    query = query.order_by(Image.is_downloaded.asc(), Image.created_at.desc())

    pagination = db.paginate(query, page=page, per_page=per_page, error_out=False)
    images = pagination.items

    image_save_path = current_app.config.get('IMAGE_SAVE_PATH')
    path_status = image_save_path_status()

    image_list = []
    for img in images:
        file_exists = bool(
            img.is_downloaded and img.url and image_save_path
            and os.path.isfile(os.path.join(image_save_path, img.url))
        )
        failure_reason = None
        if not img.is_downloaded and img.last_error:
            failure_reason = img.last_error
        elif img.is_downloaded and not file_exists:
            failure_reason = 'Marked downloaded but file missing under IMAGE_SAVE_PATH'
            if path_status.get('error'):
                failure_reason = f"{failure_reason} ({path_status['error']})"
        image_list.append({
            'id': img.id,
            'game_uuid': img.game_uuid,
            'game_name': img.game.name if img.game else 'Unknown',
            'image_type': img.image_type,
            'kind': img.image_type,
            'download_url': img.download_url,
            'is_downloaded': img.is_downloaded,
            'status': _image_status(img),
            'last_error': img.last_error,
            'failure_reason': failure_reason,
            'last_attempt_at': img.last_attempt_at.strftime('%Y-%m-%d %H:%M:%S') if img.last_attempt_at else None,
            'created_at': img.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'local_url': url_for('static', filename=f'library/images/{img.url}') if file_exists else None,
            'file_missing': bool(img.is_downloaded and not file_exists),
        })

    return jsonify({
        'images': image_list,
        'image_save_path': path_status,
        'allowed_kinds': list(IMAGE_KIND_ORDER),
        'kind_filter': type_filter,
        'pagination': {
            'page': page,
            'pages': pagination.pages,
            'per_page': pagination.per_page,
            'total': pagination.total,
            'has_next': pagination.has_next,
            'has_prev': pagination.has_prev,
        },
    })


@admin2_bp.route('/admin/api/download_images', methods=['POST'])
@login_required
@admin_required
def download_images():
    """Download specific images, retry failed images, or batch download pending ones."""
    data = request.json or {}
    path_status = image_save_path_status()
    if not path_status.get('writable') and (
        'image_ids' in data or data.get('retry_failed') or 'batch_size' in data
    ):
        writable = path_status.get('error') or 'IMAGE_SAVE_PATH is not writable'
        return api_error(
            writable,
            code='unavailable',
            image_save_path=path_status,
            downloaded=0,
            failed=0,
            errors=[{'error': writable}],
        )

    try:
        if 'image_ids' in data or data.get('retry_failed'):
            if data.get('retry_failed'):
                failed_images = db.session.execute(
                    select(Image).filter(
                        Image.is_downloaded.is_(False), Image.last_error.isnot(None)
                    )
                ).scalars().all()
            else:
                image_ids = data['image_ids']
                failed_images = [
                    img for img in (db.session.get(Image, image_id) for image_id in image_ids)
                    if img is not None
                ]

            downloaded = 0
            failed = 0
            errors = []
            for image in failed_images:
                if image.is_downloaded:
                    continue
                if not image.download_url:
                    image.last_error = 'No download URL on record for this image.'
                    image.last_attempt_at = datetime.now(timezone.utc)
                    failed += 1
                    errors.append({'image_id': image.id, 'error': image.last_error})
                    continue
                image.last_attempt_at = datetime.now(timezone.utc)
                try:
                    save_path = os.path.join(current_app.config['IMAGE_SAVE_PATH'], image.url)
                    success, error = download_stored_image(image, save_path)
                except Exception as e:
                    success, error = False, str(e)

                if success:
                    image.is_downloaded = True
                    image.last_error = None
                    downloaded += 1
                else:
                    image.last_error = error or 'Download failed for an unknown reason.'
                    failed += 1
                    errors.append({'image_id': image.id, 'error': image.last_error})
                    print(f"Failed to download image {image.id}: {image.last_error}")

            db.session.commit()
            message = f'Downloaded {downloaded} images'
            if failed:
                message += f', {failed} failed'
            return api_ok({
                'downloaded': downloaded,
                'failed': failed,
                'errors': errors,
                'message': message,
                'image_save_path': path_status,
            })

        if 'batch_size' in data:
            from oneirodex.utils.game_core import download_pending_images
            batch_size = data.get('batch_size', 10)
            downloaded = download_pending_images(
                batch_size=batch_size, delay_between_downloads=0.1, app=current_app
            )
            return api_ok({
                'downloaded': downloaded,
                'message': f'Downloaded {downloaded} images',
                'image_save_path': path_status,
            })

        return api_error('No valid parameters provided', code='bad_request')

    except Exception as e:
        current_app.logger.warning('image download failed: %s', e)
        return api_error(
            'Could not download the images',
            code='internal',
            image_save_path=path_status,
        )


@admin2_bp.route('/admin/api/delete_image/<int:image_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_image(image_id):
    """Delete a specific image from queue."""
    try:
        image = db.session.get(Image, image_id)
        if not image:
            return api_error('Image not found', code='not_found')

        if image.is_downloaded and image.url:
            file_path = os.path.join(current_app.config['IMAGE_SAVE_PATH'], image.url)
            if os.path.exists(file_path):
                os.remove(file_path)

        db.session.delete(image)
        db.session.commit()

        return api_ok({'message': 'Image deleted successfully'})
    except Exception as e:
        db.session.rollback()
        current_app.logger.warning('image download failed: %s', e)
        return api_error('Could not download the images', code='internal')


def _parse_providers_arg(raw) -> list[str] | None:
    if raw is None:
        return None
    if isinstance(raw, list):
        return [str(p).strip() for p in raw if str(p).strip()]
    text = str(raw).strip()
    if not text:
        return None
    return [p.strip() for p in text.split(',') if p.strip()]


@admin2_bp.route('/admin/api/covers/search', methods=['POST'])
@login_required
@admin_required
@validate_body(CoverSearchBody)
def covers_search_single(body: CoverSearchBody):
    """Search cover candidates across providers for one title (or game UUID)."""
    game_uuid = (body.game_uuid or '').strip() or None
    query = (body.query or body.q or body.name or '').strip()
    if game_uuid and not query:
        game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
        if not game:
            return api_error('Game not found', code='not_found', game_uuid=game_uuid)
        query = game.name or ''
    if not query:
        return api_error('query or game_uuid is required', code='bad_request')

    providers = _parse_providers_arg(body.providers)
    try:
        limit = min(int(body.limit or body.limit_per_provider or 8), 20)
    except (TypeError, ValueError):
        limit = 8

    result = search_cover_candidates(query, providers=providers, limit_per_provider=limit)
    return jsonify({
        **result,
        'game_uuid': game_uuid,
        'image_save_path': image_save_path_status(),
    })


@admin2_bp.route('/admin/api/covers/apply', methods=['POST'])
@login_required
@admin_required
@validate_body(ApplyCoverBody)
def covers_apply_single(body: ApplyCoverBody):
    """Apply one cover URL from a provider to a game."""
    from oneirodex.utils.artwork_apply import apply_cover_from_url

    game_uuid = body.game_uuid
    image_url = body.url
    provider_id = (body.provider or 'steamgriddb').strip().lower() or 'steamgriddb'

    path_status = image_save_path_status()
    if not path_status.get('writable'):
        return api_error(
            path_status.get('error') or 'IMAGE_SAVE_PATH is not writable',
            code='unavailable',
            image_save_path=path_status,
        )

    try:
        result = apply_cover_from_url(
            game_uuid,
            image_url,
            provider_id=provider_id,
            image_type='cover',
        )
    except ValueError as exc:
        return api_error(str(exc), code='bad_request', game_uuid=game_uuid)
    except LookupError as exc:
        return api_error(str(exc), code='not_found', game_uuid=game_uuid)
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        return api_error(str(exc), code='bad_gateway', game_uuid=game_uuid)

    return jsonify({**result, 'image_save_path': path_status})


@admin2_bp.route('/admin/api/covers/batch/search', methods=['POST'])
@login_required
@admin_required
def covers_batch_search():
    """Mass cover search: filter by library/platform/service/missing-cover."""
    data = request.get_json(silent=True) or {}
    try:
        limit_games = min(int(data.get('limit_games') or data.get('limit') or 25), 100)
    except (TypeError, ValueError):
        limit_games = 25
    try:
        limit_per = min(int(data.get('limit_per_provider') or 5), 15)
    except (TypeError, ValueError):
        limit_per = 5

    result = batch_search_covers(
        library_uuid=(data.get('library_uuid') or '').strip() or None,
        platform=(data.get('platform') or data.get('system') or '').strip() or None,
        service=(data.get('service') or '').strip() or None,
        missing_cover=bool(data.get('missing_cover', True)),
        limit_games=limit_games,
        providers=_parse_providers_arg(data.get('providers')),
        limit_per_provider=limit_per,
    )
    return jsonify(result)


def _cover_generate_fn(game: Game) -> dict:
    system = None
    if game.library and game.library.platform:
        system = game.library.platform.value
    manifest = save_pack(game.name or 'Untitled', system=system)
    return apply_pack_to_game(manifest['pack_id'], game.uuid)


def _parse_game_uuids(raw) -> list[str] | None:
    if isinstance(raw, str):
        return [u.strip() for u in raw.split(',') if u.strip()]
    if isinstance(raw, list):
        return [str(u).strip() for u in raw if str(u).strip()]
    return None


@admin2_bp.route('/admin/api/covers/batch/apply', methods=['POST'])
@login_required
@admin_required
def covers_batch_apply():
    """Mass apply covers by policy (sgdb→igdb→generate) or explicit provider."""
    data = request.get_json(silent=True) or {}
    policy = (data.get('policy') or 'sgdb_then_igdb_then_generate').strip()
    game_uuids = _parse_game_uuids(data.get('game_uuids'))

    try:
        limit_games = min(int(data.get('limit_games') or data.get('limit') or 25), 100)
    except (TypeError, ValueError):
        limit_games = 25

    result = batch_apply_covers(
        game_uuids=game_uuids,
        library_uuid=(data.get('library_uuid') or '').strip() or None,
        platform=(data.get('platform') or data.get('system') or '').strip() or None,
        service=(data.get('service') or '').strip() or None,
        missing_cover=bool(data.get('missing_cover', True)),
        limit_games=limit_games,
        policy=policy,
        generate_fn=_cover_generate_fn,
    )
    return jsonify(result)


@admin2_bp.route('/admin/api/artwork/auto-pick', methods=['POST'])
@login_required
@admin_required
def artwork_auto_pick():
    """
    Mass auto-pick covers for games missing art (Admin ImagesPage).

    Body JSON:
      policy: best_available | sgdb_then_igdb_then_generate | … (default best_available)
      library_uuid, platform/system, service, status, image_type (filters; optional)
      game_uuids: optional explicit list
      limit_games: max titles (default 25, max 100)
      missing_cover: bool (default true)

    Returns applied/failed counts + per-game status with clear error strings.
    """
    data = request.get_json(silent=True) or {}
    policy = (data.get('policy') or 'best_available').strip() or 'best_available'
    game_uuids = _parse_game_uuids(data.get('game_uuids'))

    try:
        limit_games = min(int(data.get('limit_games') or data.get('limit') or 25), 100)
    except (TypeError, ValueError):
        limit_games = 25

    # status / image_type are queue filters from the UI — map to missing_cover default.
    status_filter = (data.get('status') or '').strip().lower()
    missing_cover = bool(data.get('missing_cover', True))
    if status_filter in ('downloaded',):
        missing_cover = False

    path_status = image_save_path_status()
    if not path_status.get('writable'):
        return api_error(
            path_status.get('error') or 'IMAGE_SAVE_PATH is not writable',
            code='unavailable',
            applied=0,
            failed=0,
            results=[],
            policy=list(resolve_policy(policy)),
            image_save_path=path_status,
        )

    result = batch_apply_covers(
        game_uuids=game_uuids,
        library_uuid=(data.get('library_uuid') or '').strip() or None,
        platform=(data.get('platform') or data.get('system') or '').strip() or None,
        service=(data.get('service') or '').strip() or None,
        missing_cover=missing_cover,
        limit_games=limit_games,
        policy=policy,
        generate_fn=_cover_generate_fn,
    )
    return api_ok({
        'message': (
            f"Auto-pick finished: applied={result.get('applied', 0)} "
            f"failed={result.get('failed', 0)}"
        ),
        **result,
    })


@admin2_bp.route('/admin/api/artwork/generate', methods=['POST'])
@login_required
@admin_required
@validate_body(GenerateArtworkBody)
def artwork_generate(body: GenerateArtworkBody):
    """Generate cover art for one game (FEAT-D3).

    Off unless ``ENABLE_AI_ARTWORK`` is set and an endpoint is configured — a
    disabled or unconfigured install gets a clear reason, not a stack trace.
    Failure never disturbs the game's existing artwork.
    """
    from oneirodex.utils.ai_artwork import (
        ArtworkGenerationError,
        ai_artwork_enabled,
        generate_and_store_cover,
    )

    if not ai_artwork_enabled():
        return api_error(
            'Generated artwork is off. Set ENABLE_AI_ARTWORK=true and AI_ARTWORK_URL.',
            code='forbidden',
        )

    game_uuid = body.game_uuid

    try:
        result = generate_and_store_cover(
            game_uuid, image_type=body.image_type or 'cover',
        )
    except LookupError:
        return api_error('Game not found', code='not_found')
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    except ArtworkGenerationError as exc:
        # 502: our config is fine, the generation endpoint is what failed.
        return api_error(str(exc), code='bad_gateway')

    return api_ok(result)


@admin2_bp.route('/admin/api/theme/fonts', methods=['POST'])
@login_required
@admin_required
def theme_font_upload():
    """Upload a font for theming.

    Untrusted input: extension allowlist, size cap, and a magic-byte check, so
    a file served back to browsers is what it claims to be.
    """
    from oneirodex.utils.theme_fonts import store_font_file

    if 'file' not in request.files:
        return api_error('Choose a font file to upload.', code='bad_request')
    try:
        stored = store_font_file(request.files['file'])
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    except OSError as exc:
        return api_error(f'Could not write to the font folder: {exc}', code='unavailable')
    return api_ok(stored, status=201)


@admin2_bp.route('/admin/api/theme/fonts/<path:filename>', methods=['DELETE'])
@login_required
@admin_required
def theme_font_delete(filename: str):
    """Remove an operator-uploaded font. Built-ins are refused."""
    from oneirodex.utils.theme_fonts import delete_font_file

    try:
        removed = delete_font_file(filename)
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    if not removed:
        return api_error('Font not found', code='not_found')
    return api_ok({'removed': filename})


@admin2_bp.route('/admin/api/images/batch_upload', methods=['POST'])
@login_required
@admin_required
def images_batch_upload():
    """Upload several artwork files at once.

    Each file is matched to a game by ``<game_uuid>`` or ``<game_uuid>_<kind>``
    in its filename, so a folder of prepared art can be dropped in one go.
    Per-file outcomes are reported individually — one bad file must not sink
    the batch.
    """
    import os as _os
    import uuid as _uuid

    from werkzeug.utils import secure_filename

    from oneirodex.models import Game
    from oneirodex.utils.image_kinds import SINGULAR_IMAGE_KINDS, parse_image_kind

    files = request.files.getlist('files') or request.files.getlist('file')
    if not files:
        return api_error('Choose one or more image files.', code='bad_request')

    default_kind = request.form.get('image_type') or request.form.get('kind') or 'cover'
    explicit_uuid = (request.form.get('game_uuid') or '').strip()

    allowed_ext = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
    max_bytes = 10 * 1024 * 1024
    save_dir = current_app.config['IMAGE_SAVE_PATH']
    _os.makedirs(save_dir, exist_ok=True)

    stored, errors = [], []
    for item in files:
        raw = getattr(item, 'filename', '') or ''
        name = secure_filename(raw)
        stem, ext = _os.path.splitext(name)
        ext = ext.lower()
        if ext not in allowed_ext:
            errors.append({'file': raw, 'error': 'Unsupported image type'})
            continue

        item.stream.seek(0, _os.SEEK_END)
        size = item.stream.tell()
        item.stream.seek(0)
        if size <= 0:
            errors.append({'file': raw, 'error': 'Empty file'})
            continue
        if size > max_bytes:
            errors.append({'file': raw, 'error': 'Larger than the 10MB limit'})
            continue

        # <uuid> or <uuid>_<kind> — fall back to the form-wide target.
        parts = stem.split('_')
        candidate_uuid = explicit_uuid or (parts[0] if parts else '')
        kind_hint = parts[1] if (not explicit_uuid and len(parts) > 1) else default_kind
        try:
            kind = parse_image_kind(kind_hint, default=default_kind)
        except ValueError:
            kind = parse_image_kind(default_kind, default='cover')

        game = db.session.execute(
            select(Game).filter_by(uuid=candidate_uuid)
        ).scalars().first()
        if not game:
            errors.append({'file': raw, 'error': 'No game matched this filename'})
            continue

        file_name = secure_filename(
            f'{game.uuid}_{kind}_{_uuid.uuid4().hex[:8]}{ext}'
        )
        try:
            item.save(_os.path.join(save_dir, file_name))
        except OSError as exc:
            errors.append({'file': raw, 'error': f'Could not write: {exc}'})
            continue

        if kind in SINGULAR_IMAGE_KINDS:
            for row in db.session.execute(
                select(Image).filter_by(game_uuid=game.uuid, image_type=kind)
            ).scalars().all():
                db.session.delete(row)

        db.session.add(Image(
            game_uuid=game.uuid,
            image_type=kind,
            url=file_name,
            is_downloaded=True,
        ))
        stored.append({
            'file': raw,
            'game_uuid': game.uuid,
            'game_name': game.name,
            'kind': kind,
            'filename': file_name,
        })

    if stored:
        db.session.commit()

    return api_ok({
        'stored': len(stored),
        'failed': len(errors),
        'images': stored,
        'errors': errors,
    })


@admin2_bp.route('/admin/api/artwork/generate/batch', methods=['POST'])
@login_required
@admin_required
def artwork_generate_batch():
    """Fill missing covers with generated art (FEAT-D3).

    Only touches titles that have **no cover at all** — generated art is a
    better placeholder, never a replacement for a cover someone chose. Capped
    per call because each title is a full generation (seconds to minutes), and
    per-title failures are reported rather than aborting the run.
    """
    from oneirodex.models import Game
    from oneirodex.utils.ai_artwork import (
        ArtworkGenerationError,
        ai_artwork_enabled,
        generate_and_store_cover,
    )

    if not ai_artwork_enabled():
        return api_error(
            'Generated artwork is off. Set ENABLE_AI_ARTWORK=true and AI_ARTWORK_URL.',
            code='forbidden',
        )

    data = request.get_json(silent=True) or {}
    try:
        limit = min(max(int(data.get('limit') or 10), 1), 50)
    except (TypeError, ValueError):
        return api_error('limit must be a number', code='bad_request')

    query = select(Game)
    if data.get('library_uuid'):
        query = query.filter(Game.library_uuid == data['library_uuid'])

    candidates = db.session.execute(query).scalars().all()

    generated, skipped, errors = [], 0, []
    for game in candidates:
        if len(generated) >= limit:
            break

        has_cover = db.session.execute(
            select(Image).filter_by(game_uuid=game.uuid, image_type='cover')
        ).scalars().first()
        if has_cover is not None:
            # Includes previously generated covers — re-running must not churn.
            skipped += 1
            continue

        try:
            result = generate_and_store_cover(game.uuid, image_type='cover')
        except ArtworkGenerationError as exc:
            errors.append({'uuid': game.uuid, 'name': game.name, 'error': str(exc)})
            continue
        except Exception as exc:  # noqa: BLE001
            errors.append({'uuid': game.uuid, 'name': game.name, 'error': str(exc)})
            continue

        generated.append({
            'uuid': game.uuid,
            'name': game.name,
            'filename': result.get('filename'),
        })

    return api_ok({
        'considered': len(candidates),
        'generated': len(generated),
        'skipped': skipped,
        'failed': len(errors),
        'games': generated,
        'errors': errors[:20],
    })
