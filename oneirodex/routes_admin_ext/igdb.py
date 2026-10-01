# /oneirodex/routes_admin_ext/igdb.py
from flask import current_app, render_template, request
from flask_login import login_required
from oneirodex import db
from datetime import datetime, timezone
from . import admin2_bp
from oneirodex.utils.api_response import api_error, api_ok
from oneirodex.utils.igdb_api import make_igdb_api_request
from oneirodex.utils.auth import admin_required
from oneirodex.utils.global_settings import (
    global_settings_row,
    global_settings_row_or_create,
)

@admin2_bp.route('/admin/igdb_settings', methods=['GET', 'POST'])
@login_required
@admin_required
def igdb_settings():
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
    
    return render_template('admin/admin_manage_igdb_settings.html', settings=settings)

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
