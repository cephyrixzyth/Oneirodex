from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.session_compat import dump_session_cookie, generate_csrf_token
from oneirodex.runtime_native.smtp_settings_read import create_smtp_settings_router
from oneirodex.utils.smtp_settings import validate_smtp_data
from oneirodex.utils.smtp_settings import smtp_public_state


def _client(*, role='admin', test_result=True, legacy_save=None):
    flask_app = Flask(__name__)
    flask_app.config.update(SECRET_KEY='native-smtp-read-secret', CSP_ENABLED=False)
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    user = SimpleNamespace(
        id=71, user_id='smtp-user', role=role,
        is_active=True, state=True, is_authenticated=True,
        session_fingerprint=lambda: 'fingerprint',
    )
    login_manager = SimpleNamespace(
        login_view='login.login', blueprint_login_views={},
        login_message='Please log in to access this page.',
        login_message_category='message', localize_callback=None,
        session_protection='basic',
    )
    saved = []

    def save(payload):
        validated = validate_smtp_data(payload, None)
        saved.append(validated)
        return {'settings': {
            'smtp_server': validated['smtp_server'],
            'password_saved': bool(validated['smtp_password']),
        }}

    def legacy_test():
        if isinstance(test_result, BaseException):
            raise test_result
        if test_result is None:
            return None
        if isinstance(test_result, tuple):
            return test_result
        return bool(test_result), (
            'Connection successful' if test_result
            else 'Connection failed: Authentication error'
        )

    data_access = SimpleNamespace(
        read=lambda: {'settings': {
            'smtp_server': 'mail.example', 'password_saved': True,
        }},
        save=save,
        test_connection=lambda: test_result,
        test_connection_legacy=legacy_test,
    )
    if legacy_save is not None:
        data_access.save_legacy = legacy_save

    router = create_smtp_settings_router(
        flask_app,
        find_user=lambda user_id: user if user_id == 71 else None,
        find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: user if value.split(':', 1)[0] == '71' else None,
        login_manager=login_manager,
        data_access=data_access,
        database_scope=lambda _app: nullcontext(),
    )
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    session_data = {'_user_id': '71:fingerprint', '_fresh': True}
    client.csrf_token = generate_csrf_token(session_data, flask_app.config['SECRET_KEY'])
    client.cookies.set(
        'session', dump_session_cookie(session_data, flask_app.config['SECRET_KEY'])
    )
    client.saved = saved
    return client


def test_smtp_settings_read_keeps_secret_free_envelope_and_head():
    client = _client()
    response = client.get('/api/admin/smtp/settings')
    head = client.head('/api/admin/smtp/settings')
    assert response.status_code == 200
    assert response.json()['settings'] == {
        'smtp_server': 'mail.example', 'password_saved': True,
    }
    assert response.headers['cache-control'] == 'no-store'
    assert 'smtp_password' not in response.text
    assert head.status_code == 200
    assert head.content == b''
    assert head.headers['content-length'] == str(len(response.content))


def test_smtp_settings_requires_admin():
    response = _client(role='user').get('/api/admin/smtp/settings', follow_redirects=False)
    assert response.status_code == 302
    assert response.headers['location'].startswith('/login')


def test_smtp_public_state_reports_password_presence_only():
    state = smtp_public_state(SimpleNamespace(
        smtp_enabled=True, smtp_server='mail.example', smtp_port=587,
        smtp_username='mailer', smtp_password='secret', smtp_use_tls=True,
        smtp_default_sender='noreply@example.com', smtp_last_tested=None,
    ))
    assert state['password_saved'] is True
    assert 'smtp_password' not in state
    assert 'secret' not in repr(state)


def test_smtp_settings_write_validates_csrf_and_preserves_hidden_password():
    client = _client()
    payload = {
        'smtp_enabled': False, 'smtp_use_tls': True,
        'smtp_server': 'mail.example', 'smtp_username': 'mailer',
        'smtp_password': 'private-password', 'smtp_default_sender': 'noreply@example.com',
        'smtp_port': 587,
    }
    missing_csrf = client.put('/api/admin/smtp/settings', json=payload)
    saved = client.put(
        '/api/admin/smtp/settings', json=payload,
        headers={'X-CSRFToken': client.csrf_token},
    )
    invalid = client.put(
        '/api/admin/smtp/settings', json={'smtp_enabled': True},
        headers={'X-CSRFToken': client.csrf_token},
    )
    assert missing_csrf.status_code == 400
    assert saved.status_code == 200
    assert saved.json()['settings']['password_saved'] is True
    assert 'private-password' not in saved.text
    assert invalid.status_code == 400
    assert client.saved[0]['smtp_password'] == 'private-password'


def test_smtp_connection_test_checks_csrf_and_reports_safe_result():
    client = _client()
    invalid_csrf = client.post('/api/admin/smtp/test')
    success = client.post(
        '/api/admin/smtp/test', headers={'X-CSRFToken': client.csrf_token}
    )
    fail_client = _client(test_result=False)
    failure = fail_client.post(
        '/api/admin/smtp/test', headers={'X-CSRFToken': fail_client.csrf_token}
    )
    assert invalid_csrf.status_code == 400
    assert success.status_code == 200
    assert success.json()['message'] == 'SMTP connection successful. No email was sent.'
    assert failure.status_code == 502
    assert 'password' not in failure.text.lower()


def test_legacy_smtp_save_path_preserves_status_and_hides_password():
    client = _client()
    response = client.post(
        '/admin/smtp_settings',
        json={
            'smtp_enabled': False, 'smtp_use_tls': True,
            'smtp_server': 'mail.example', 'smtp_username': 'mailer',
            'smtp_password': 'private-password', 'smtp_default_sender': 'noreply@example.com',
            'smtp_port': 587,
        },
        headers={'X-CSRFToken': client.csrf_token},
    )

    assert response.status_code == 200
    assert response.json()['status'] == 'success'
    assert response.json()['message'] == 'SMTP settings updated successfully'
    assert 'private-password' not in response.text


def test_legacy_smtp_post_uses_compatibility_save_and_exact_response():
    calls = []
    client = _client(legacy_save=lambda payload: calls.append(payload))
    payload = {
        'smtp_enabled': False,
        'smtp_server': ' invalid hostname ',
        'smtp_port': 'not-a-number',
        'smtp_username': ' user ',
        'smtp_use_tls': 'unchecked',
        'smtp_default_sender': 'not-an-email',
    }

    response = client.post(
        '/admin/smtp_settings', json=payload,
        headers={'X-CSRFToken': client.csrf_token},
    )

    assert response.status_code == 200
    assert calls == [payload]
    assert client.saved == []  # strict modern PUT validator was bypassed
    assert response.json() == {
        'ok': True,
        'error': None,
        'error_code': None,
        'success': True,
        'status': 'success',
        'message': 'SMTP settings updated successfully',
    }


def test_legacy_smtp_disabled_save_preserves_v118_field_semantics(monkeypatch):
    from oneirodex.runtime_native import db_session
    from oneirodex.utils import global_settings
    from oneirodex.runtime_native.smtp_settings_read import SmtpSettingsData

    settings = SimpleNamespace(
        smtp_enabled=True, smtp_server='old.example', smtp_port=2525,
        smtp_username='old-user', smtp_password='saved-secret',
        smtp_use_tls=True, smtp_default_sender='old@example.com',
    )
    session = SimpleNamespace(commits=0)
    session.commit = lambda: setattr(session, 'commits', session.commits + 1)
    monkeypatch.setattr(db_session, 'native_db', SimpleNamespace(session=session))
    monkeypatch.setattr(global_settings, 'global_settings_row_or_create', lambda: settings)

    SmtpSettingsData().save_legacy({
        'smtp_enabled': False,
        'smtp_server': ' invalid hostname ',
        'smtp_port': 'not-a-number',
        'smtp_username': ' user ',
        'smtp_password': '',
        'smtp_use_tls': 'unchecked',
        'smtp_default_sender': 'not-an-email',
    })

    assert settings.smtp_enabled is False
    assert settings.smtp_port == 2525
    assert settings.smtp_server == ' invalid hostname '
    assert settings.smtp_username == ' user '
    assert settings.smtp_password == 'saved-secret'
    assert settings.smtp_use_tls == 'unchecked'
    assert settings.smtp_default_sender == 'not-an-email'
    assert session.commits == 1


def test_legacy_smtp_enabled_validation_keeps_v118_error_order(monkeypatch):
    import pytest

    from oneirodex.runtime_native import db_session
    from oneirodex.utils import global_settings
    from oneirodex.runtime_native.smtp_settings_read import SmtpSettingsData

    settings = SimpleNamespace(smtp_password='')
    monkeypatch.setattr(db_session, 'native_db', SimpleNamespace(session=SimpleNamespace()))
    monkeypatch.setattr(global_settings, 'global_settings_row_or_create', lambda: settings)

    with pytest.raises(ValueError, match='SMTP password is required when SMTP is enabled'):
        SmtpSettingsData().save_legacy({
            'smtp_enabled': True,
            'smtp_server': 'smtp.example.com',
            'smtp_port': 587,
            'smtp_username': 'mailer',
            'smtp_default_sender': '',
        })


def test_legacy_smtp_test_path_keeps_failure_at_http_200():
    client = _client(test_result=False)
    response = client.post('/admin/smtp_test', headers={'X-CSRFToken': client.csrf_token})

    assert response.status_code == 200
    assert response.json()['success'] is False
    assert response.json()['message'] == 'Connection failed: Authentication error'


def test_legacy_smtp_test_path_preserves_success_result_and_missing_settings():
    client = _client(test_result=(True, {'status': 'Connection successful'}))
    response = client.post('/admin/smtp_test', headers={'X-CSRFToken': client.csrf_token})
    assert response.status_code == 200
    assert response.json()['result'] == {'status': 'Connection successful'}

    client = _client(test_result=None)
    response = client.post('/admin/smtp_test', headers={'X-CSRFToken': client.csrf_token})
    assert response.status_code == 400
    assert response.json()['message'] == 'SMTP settings not configured'


def test_legacy_smtp_test_result_redacts_saved_secret():
    from oneirodex.runtime_native.smtp_settings_read import _redact_smtp_result

    assert _redact_smtp_result(
        {'message': 'server echoed private-token'}, 'private-token'
    ) == {'message': 'server echoed [redacted]'}


def test_legacy_smtp_unexpected_test_exception_uses_legacy_500_envelope():
    client = _client(test_result=RuntimeError('private error details'))
    response = client.post('/admin/smtp_test', headers={'X-CSRFToken': client.csrf_token})

    assert response.status_code == 500
    assert response.json()['error_code'] == 'internal'
    assert response.json()['message'] == 'Something went wrong on our end. The error has been logged.'
    assert 'private error details' not in response.text
