from types import SimpleNamespace
from unittest.mock import Mock
from datetime import datetime
import pytest
from flask import Flask
from flask_login import LoginManager, UserMixin
from flask_wtf.csrf import CSRFProtect, generate_csrf
from oneirodex.routes_admin_ext import admin2_bp
from oneirodex.routes_admin_ext import newsletter as routes

class Actor(UserMixin):
    def __init__(self, identity):
        self.id = 1 if identity == 'admin' else 2
        self.role = 'admin' if identity == 'admin' else 'user'

@pytest.fixture
def harness(monkeypatch):
    app = Flask(__name__); app.secret_key = 'review'; app.config['TESTING'] = True
    manager = LoginManager(app); manager.user_loader(lambda identity: Actor(identity))
    CSRFProtect(app); app.register_blueprint(admin2_bp)
    app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    app.add_url_rule('/csrf', view_func=lambda: generate_csrf())
    users = [SimpleNamespace(id=1, email='one@example.test'), SimpleNamespace(id=2, email='two@example.test')]
    row = SimpleNamespace(id=7, subject='<b>review</b>', content='<script>unsafe</script>', status='pending', sent_date=datetime(2026,1,1), recipient_count=2, sender=SimpleNamespace(name='Reviewer'), error_message='secret /private/path')
    session = Mock(); session.execute.return_value.scalars.return_value.all.side_effect = lambda: users
    session.get.return_value = row
    session.add.side_effect = lambda value: (setattr(value, 'id', 8), setattr(value, 'sent_date', datetime(2026,1,2)))
    monkeypatch.setattr(routes, 'db', SimpleNamespace(session=session))
    settings = SimpleNamespace(settings={'enableNewsletterFeature': True}, smtp_enabled=True, smtp_server='local', smtp_default_sender='review@example.test')
    monkeypatch.setattr(routes, 'global_settings_row', lambda: settings)
    send = Mock(return_value=True); monkeypatch.setattr(routes, 'send_email_quiet', send)
    client = app.test_client()
    with client.session_transaction() as value: value['_user_id'] = 'admin'; value['_fresh'] = True
    return client, session, settings, send, row, {'X-CSRFToken': client.get('/csrf').text}


def payload():
    return {'subject': 'Review', 'content': 'Plain message', 'recipients': ['one@example.test']}


def test_state_and_detail_are_safe_readonly(harness):
    client, session, settings, send, row, headers = harness
    session.execute.return_value.scalars.return_value.all.side_effect = iter([[SimpleNamespace(id=1,email='one@example.test')], [row]])
    response = client.get('/api/admin/newsletters')
    assert response.status_code == 200 and response.json['can_send'] is True
    assert response.json['newsletters'][0]['status'] == 'pending'
    assert response.headers['Cache-Control'] == 'no-store'
    row.status = 'failed'
    detail = client.get('/api/admin/newsletters/7')
    assert detail.json['newsletter']['content'] == '<script>unsafe</script>'
    assert detail.json['newsletter']['sender'] == 'Reviewer'
    assert 'secret' not in detail.text and '/private' not in detail.text
    session.commit.assert_not_called(); send.assert_not_called()


def test_newsletter_routes_use_shared_shell_and_defer_state_to_api(harness, monkeypatch):
    client, session, *_ = harness
    rendered = []
    monkeypatch.setattr(routes, 'render_admin_spa', lambda *, title: rendered.append(title) or '<main>shell</main>')
    response = client.get('/admin/newsletter')
    assert response.status_code == 200 and response.text == '<main>shell</main>'
    detail = client.get('/admin/newsletter/7')
    assert detail.status_code == 200 and detail.text == '<main>shell</main>'
    assert rendered == ['Newsletter · Oneirodex Admin', 'Newsletter detail · Oneirodex Admin']
    session.execute.assert_not_called(); session.get.assert_not_called()

@pytest.mark.parametrize('identity', ['0', '2147483648', '99999999999999999999999999999999999'])
def test_detail_out_of_range_is_safe(harness, identity):
    client, session, *_ = harness
    assert client.get('/api/admin/newsletters/' + identity).status_code == 404
    session.get.assert_not_called()


def test_numeric_leading_zero_and_missing(harness):
    client, session, *_ = harness
    assert client.get('/api/admin/newsletters/0007').status_code == 200
    session.get.assert_called_with(routes.Newsletter, 7)
    session.get.return_value = None
    assert client.get('/api/admin/newsletters/7').status_code == 404

@pytest.mark.parametrize('patch', [{'subject': ''}, {'subject': 'x'*256}, {'subject': 'bad\nheader'}, {'content': True}, {'content': ''}, {'recipients': []}, {'recipients': 'one@example.test'}, {'recipients': [True]}, {'recipients': ['outside@example.test']}, {'extra': 1}])
def test_strict_send_validation_never_transports(harness, patch):
    client, session, settings, send, row, headers = harness
    data = payload(); data.update(patch)
    assert client.post('/api/admin/newsletters', json=data, headers=headers).status_code == 400
    send.assert_not_called(); session.add.assert_not_called()


def test_server_prerequisites_csrf_acl(harness):
    client, session, settings, send, row, headers = harness
    settings.settings['enableNewsletterFeature'] = False
    assert client.post('/api/admin/newsletters', json=payload(), headers=headers).status_code == 409
    settings.settings['enableNewsletterFeature'] = True; settings.smtp_enabled = False
    assert client.post('/api/admin/newsletters', json=payload(), headers=headers).status_code == 409
    assert client.post('/api/admin/newsletters', json=payload()).status_code == 400
    with client.session_transaction() as value: value['_user_id'] = 'member'
    assert client.get('/api/admin/newsletters').status_code == 302
    send.assert_not_called()

@pytest.mark.parametrize('transport,expected', [([True, True], 'sent'), ([True, False], 'failed'), ([RuntimeError('secret /path'), True], 'failed')])
def test_delivery_durable_pending_dedup_and_truthful_final(harness, transport, expected):
    client, session, settings, send, row, headers = harness
    observed = []
    def deliver(*args):
        saved = session.add.call_args.args[0]
        observed.append(saved.status)
        assert session.commit.call_count == 1
        value = transport.pop(0)
        if isinstance(value, Exception): raise value
        return value
    send.side_effect = deliver
    data = payload(); data['recipients'] = ['one@example.test','two@example.test','one@example.test']
    response = client.post('/api/admin/newsletters', json=data, headers=headers)
    assert response.status_code == 200 and response.json['newsletter']['status'] == expected
    assert response.json['newsletter']['recipient_count'] == 2
    assert observed == ['pending','pending'] and send.call_count == 2
    assert session.commit.call_count == 2 and 'secret' not in response.text


def test_load_and_commit_failure_are_generic(harness):
    client, session, settings, send, row, headers = harness
    session.execute.side_effect = RuntimeError('secret /private/path')
    assert 'secret' not in client.get('/api/admin/newsletters').text
    session.execute.side_effect = None
    session.commit.side_effect = RuntimeError('secret')
    response = client.post('/api/admin/newsletters', json=payload(), headers=headers)
    assert response.status_code == 500 and 'secret' not in response.text
    session.rollback.assert_called_once(); send.assert_not_called()
