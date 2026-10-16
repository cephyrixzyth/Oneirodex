# /oneirodex/routes_admin_ext/igdb.py
from flask import current_app, request
from flask_login import login_required
from oneirodex import db, cache
from datetime import datetime, timezone
from . import admin2_bp
from oneirodex.utils.api_response import api_error, api_ok
from oneirodex.utils.igdb_api import make_igdb_api_request
from oneirodex.utils.auth import admin_required
from oneirodex.utils.global_settings import (
    global_settings_row,
    global_settings_row_or_create,
)
from oneirodex.utils.admin_spa import render_admin_spa
from oneirodex.utils.igdb_settings import igdb_public_state, validate_igdb_data
from oneirodex.schemas.json_object import JsonObjectBody
from oneirodex.utils.validation import validate_body


def _invalid_igdb_settings_body(_exc):
    try:
        validate_igdb_data(None)
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    return api_error('A JSON object containing only the client ID and secret is required', code='bad_request')


@admin2_bp.route('/api/admin/igdb/settings', methods=['GET', 'PUT'])
@login_required
@admin_required
@validate_body(JsonObjectBody, methods={'PUT'}, on_error=_invalid_igdb_settings_body)
def igdb_settings_api(body: JsonObjectBody | None = None):
    try:
        settings = global_settings_row()
    except Exception:
        current_app.logger.warning('IGDB settings API load failed')
        return api_error('Could not load IGDB settings', code='internal')
    if request.method == 'PUT':
        try:
            data = validate_igdb_data(body.root)
        except ValueError as exc:
            return api_error(str(exc), code='bad_request')
        try:
            settings = settings or global_settings_row_or_create()
            settings.igdb_client_id = data['igdb_client_id']
            if data['igdb_client_secret']:
                settings.igdb_client_secret = data['igdb_client_secret']
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.warning('IGDB settings API save failed')
            return api_error('Could not save IGDB settings', code='internal')
        cache.delete('global_settings')
    response = current_app.make_response(api_ok({'settings': igdb_public_state(settings)}))
    response.headers['Cache-Control'] = 'no-store'
    return response


@admin2_bp.route('/api/admin/igdb/test', methods=['POST'])
@login_required
@admin_required
def igdb_test_api():
    settings = global_settings_row()
    if not settings or not settings.igdb_client_id or not settings.igdb_client_secret:
        return api_error('Save a client ID and secret before testing the connection', code='bad_request')
    try:
        result = make_igdb_api_request('https://api.igdb.com/v4/games', 'fields name; limit 1;')
        if not isinstance(result, list):
            return api_error('IGDB connection failed. Check the saved credentials and provider access.', code='bad_gateway')
        settings.igdb_last_tested = datetime.now(timezone.utc)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.warning('IGDB connection test failed')
        return api_error('IGDB connection test failed', code='bad_gateway')
    response = current_app.make_response(api_ok({'settings': igdb_public_state(settings), 'message': 'IGDB connection successful.'}))
    response.headers['Cache-Control'] = 'no-store'
    return response

@admin2_bp.route('/admin/igdb_settings', methods=['GET', 'POST'])
@login_required
@admin_required
def igdb_settings():
    if request.method == 'GET':
        return render_admin_spa(title='IGDB metadata · Oneirodex Admin')

    settings = global_settings_row()
    if request.method == 'POST':
        data = request.json
        settings = global_settings_row_or_create()
        
        settings.igdb_client_id = data.get('igdb_client_id')
        # The page never shows the saved secret; blank keeps it.
        if data.get('igdb_client_secret'):
            settings.igdb_client_secret = data.get('igdb_client_secret')
        
        try:
            db.session.commit()
            # `status: 'success'` is payload: admin_manage_igdb_settings.js
            # branches on `data.status === 'success'`.
            return api_ok({
                'status': 'success',
                'message': 'IGDB settings updated successfully',
            })
        except Exception as e:
            db.session.rollback()
            current_app.logger.warning('IGDB settings save failed: %s', e)
            return api_error('Could not save IGDB settings', code='internal')
    
    return api_error('Method not allowed', code='bad_request', status=405)

@admin2_bp.route('/admin/test_igdb', methods=['POST'])
@login_required
@admin_required
def test_igdb():
    print("Testing IGDB connection...")
    settings = global_settings_row()
    if not settings or not settings.igdb_client_id or not settings.igdb_client_secret:
        return api_error('IGDB settings not configured', code='bad_request')

    try:
        # Test the IGDB API with a simple query
        response = make_igdb_api_request('https://api.igdb.com/v4/games', 'fields name; limit 1;')
        if isinstance(response, list):
            print("IGDB API test successful")
            settings.igdb_last_tested = datetime.now(timezone.utc)
            db.session.commit()
            return api_ok({
                'status': 'success',
                'message': 'IGDB API test successful',
            })
        print("IGDB API test failed")
        return api_error('Invalid API response', code='internal')
    except Exception as e:
        current_app.logger.warning('IGDB API test failed: %s', e)
        return api_error('IGDB API test failed', code='internal')
