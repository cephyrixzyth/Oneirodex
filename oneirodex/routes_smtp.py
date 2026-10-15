from oneirodex.utils.api_response import api_error, api_ok
from oneirodex.utils.admin_spa import render_admin_spa
from flask import Blueprint, current_app, request
from flask_login import login_required
from oneirodex.utils.auth import admin_required
from oneirodex.utils.global_settings import (
    global_settings_row,
    global_settings_row_or_create,
)
from oneirodex.models import GlobalSettings
from oneirodex import db
from oneirodex.utils.smtp_test import SMTPTester
from oneirodex import cache
from oneirodex.utils.smtp_settings import smtp_public_state, validate_smtp_data

smtp_bp = Blueprint('smtp', __name__)


@smtp_bp.route('/api/admin/smtp/settings', methods=['GET', 'PUT'])
@login_required
@admin_required
def smtp_settings_api():
    settings = global_settings_row()
    if request.method == 'GET':
        response = current_app.make_response(api_ok({'settings': smtp_public_state(settings)}))
        response.headers['Cache-Control'] = 'no-store'
        return response
    try:
        data = validate_smtp_data(request.get_json(silent=True), settings)
    except ValueError as exc:
        return api_error(str(exc), code='bad_request')
    try:
        settings = settings or global_settings_row_or_create()
        for key, value in data.items():
            if key != 'smtp_password' or value:
                setattr(settings, key, value)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.warning('SMTP settings API save failed')
        return api_error('Could not save SMTP settings', code='internal')
    cache.delete('global_settings')
    response = current_app.make_response(api_ok({'settings': smtp_public_state(settings)}))
    response.headers['Cache-Control'] = 'no-store'
    return response


@smtp_bp.route('/api/admin/smtp/test', methods=['POST'])
@login_required
@admin_required
def smtp_test_api():
    """Connect/authenticate using saved settings; never send a message."""
    settings = global_settings_row()
    if not settings or not settings.smtp_enabled:
        return api_error('Save and enable SMTP before testing the connection', code='bad_request')
    try:
        success, _ = SMTPTester(debug=False).test_connection(
            host=settings.smtp_server, port=settings.smtp_port,
            username=settings.smtp_username, password=settings.smtp_password,
            use_tls=settings.smtp_use_tls, timeout=10,
        )
    except Exception:
        current_app.logger.warning('SMTP connection test failed')
        return api_error('SMTP connection failed. Check the saved settings and provider access.', code='bad_gateway')
    if not success:
        return api_error('SMTP connection failed. Check the saved settings and provider access.', code='bad_gateway')
    return api_ok({'message': 'SMTP connection successful. No email was sent.'})

@smtp_bp.route('/admin/smtp_settings', methods=['GET', 'POST'])
@login_required
@admin_required
def smtp_settings():
    if request.method == 'POST':
        data = request.json or {}
        settings = global_settings_row_or_create()
        
        # Validate required fields when SMTP is enabled
        if data.get('smtp_enabled'):
            if not data.get('smtp_server'):
                return api_error(
                    'SMTP server is required when SMTP is enabled',
                    code='bad_request',
                )
            if not data.get('smtp_port'):
                return api_error(
                    'SMTP port is required when SMTP is enabled',
                    code='bad_request',
                )
            if not data.get('smtp_username'):
                return api_error(
                    'SMTP username is required when SMTP is enabled',
                    code='bad_request',
                )
            # The page never shows the saved password; blank keeps it.
            if not data.get('smtp_password') and not settings.smtp_password:
                return api_error(
                    'SMTP password is required when SMTP is enabled',
                    code='bad_request',
                )
            if not data.get('smtp_default_sender'):
                return api_error(
                    'Default sender email is required when SMTP is enabled',
                    code='bad_request',
                )
            
            # Validate port number
            try:
                port = int(data.get('smtp_port', 587))
                if port <= 0 or port > 65535:
                    return api_error(
                        'Invalid port number. Must be between 1 and 65535',
                        code='bad_request',
                    )
                settings.smtp_port = port
            except ValueError:
                return api_error('SMTP port must be a valid number', code='bad_request')
        
        settings.smtp_enabled = data.get('smtp_enabled', False)
        settings.smtp_server = data.get('smtp_server')
        settings.smtp_username = data.get('smtp_username')
        if data.get('smtp_password'):
            settings.smtp_password = data.get('smtp_password')
        settings.smtp_use_tls = data.get('smtp_use_tls', True)
        settings.smtp_default_sender = data.get('smtp_default_sender')
        settings.smtp_enabled = data.get('smtp_enabled', False)
        
        try:
            db.session.commit()
            # `status: 'success'` stays in the payload: the admin page branches
            # on `data.status === 'success'`. Failures that need a body status
            # use api_error(..., body_status=...).
            return api_ok({
                'status': 'success',
                'message': 'SMTP settings updated successfully',
            })
        except Exception as e:
            db.session.rollback()
            current_app.logger.warning('SMTP settings save failed: %s', e)
        return api_error('Could not save SMTP settings', code='internal')
    
    return render_admin_spa(title='SMTP - Oneirodex Admin')

@smtp_bp.route('/admin/smtp_test', methods=['POST'])
@login_required
@admin_required
def smtp_test():
    settings = global_settings_row()
    if not settings:
        return api_error('SMTP settings not configured', code='bad_request')

    # Create SMTPTester instance
    tester = SMTPTester(debug=False)
    print(f"Testing SMTP connection using settings: {settings.smtp_server}:{settings.smtp_port}")
    # Test the connection using settings from database
    success, result = tester.test_connection(
        host=settings.smtp_server,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        use_tls=settings.smtp_use_tls,
        timeout=10
    )

    if success:
        # 200 + `success`: the request worked, the connection test is what
        # failed or passed. admin_manage_smtp_settings.js reads `data.success`.
        return api_ok({'result': result})
    # HTTP 200 on purpose: the save-adjacent test endpoint reports a failed
    # connection as `success: false`, not as a 4xx. api_error still sets those
    # mirrors when status=200.
    return api_error(str(result or 'SMTP connection failed'), code='bad_request', status=200)
