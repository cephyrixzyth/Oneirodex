"""Admin UI for household custom chat emoji."""

from __future__ import annotations

from flask import flash, redirect, request, url_for, current_app
from flask_login import current_user, login_required

from oneirodex.utils.auth import admin_required
from oneirodex.utils.custom_emoji import (
    MAX_CUSTOM_EMOJI,
    MAX_UPLOAD_BYTES,
    MAX_EDGE_PX,
    ALLOWED_EXT,
    normalize_slug,
    delete_custom_emoji,
    list_custom_emoji,
    upload_custom_emoji,
)

from . import admin2_bp
from oneirodex import db
from oneirodex.utils.api_response import api_ok, api_error
from oneirodex.utils.admin_spa import render_admin_spa


@admin2_bp.route('/api/admin/chat-emoji', methods=['GET', 'POST'])
@login_required
@admin_required
def chat_emoji_api():
    if request.method == 'GET':
        try:
            response = current_app.make_response(api_ok({
                'emojis': list_custom_emoji(), 'max_custom': MAX_CUSTOM_EMOJI,
                'limits': {'max_upload_bytes': MAX_UPLOAD_BYTES, 'max_edge_px': MAX_EDGE_PX,
                           'extensions': sorted(ALLOWED_EXT)},
            }))
            response.headers['Cache-Control'] = 'no-store'
            return response
        except Exception:
            current_app.logger.warning('Could not load custom chat emoji')
            return api_error('Could not load custom chat emoji', code='internal')
    try:
        row = upload_custom_emoji(slug=request.form.get('slug') or '',
                                 label=request.form.get('label') or '',
                                 file=request.files.get('file'), uploader=current_user)
        return api_ok({'emoji': row.to_dict(), 'message': 'Custom emoji uploaded.'}, status=201)
    except ValueError as exc:
        text = str(exc)
        if text.startswith('Invalid image:'):
            text = 'The file could not be read as an image'
        return api_error(text, code='bad_request')
    except Exception:
        db.session.rollback()
        current_app.logger.warning('Custom emoji upload failed')
        return api_error('Could not upload custom emoji', code='internal')


@admin2_bp.route('/api/admin/chat-emoji/<slug>', methods=['DELETE'])
@login_required
@admin_required
def delete_chat_emoji_api(slug):
    try:
        slug = normalize_slug(slug)
    except ValueError:
        return api_error('Invalid emoji slug', code='bad_request')
    try:
        if not delete_custom_emoji(slug):
            return api_error('Custom emoji not found', code='not_found')
        return api_ok({'message': 'Custom emoji deleted.'})
    except Exception:
        db.session.rollback()
        current_app.logger.warning('Custom emoji deletion failed')
        return api_error('Could not delete custom emoji', code='internal')


@admin2_bp.route('/admin/chat_emoji', methods=['GET', 'POST'])
@login_required
@admin_required
def chat_emoji_admin():
    if request.method == 'POST':
        action = (request.form.get('action') or 'upload').strip()
        if action == 'delete':
            slug = request.form.get('slug') or ''
            if delete_custom_emoji(slug):
                flash(f'Deleted :{slug}:', 'success')
            else:
                flash('Emoji not found', 'error')
            return redirect(url_for('admin2.chat_emoji_admin'))
        try:
            row = upload_custom_emoji(
                slug=request.form.get('slug') or '',
                label=request.form.get('label') or '',
                file=request.files.get('file'),
                uploader=current_user,
            )
            flash(f'Uploaded {row.reaction_key()}', 'success')
        except ValueError as exc:
            flash(str(exc), 'error')
        return redirect(url_for('admin2.chat_emoji_admin'))

    return render_admin_spa(title='Chat emoji - Oneirodex Admin')
