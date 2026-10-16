"""Reference upload/delete contracts; parser, persistence, and audit mocked."""
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from flask import Flask
from flask_login import LoginManager, UserMixin
from flask_wtf.csrf import CSRFProtect, generate_csrf
import oneirodex.routes_admin_ext.reference_sets as routes


class ReviewUser(UserMixin):
    def __init__(self, role): self.id = role; self.role = role


@pytest.fixture
def harness(monkeypatch):
    app = Flask(__name__); app.config.update(TESTING=True, SECRET_KEY='reference-api-test-only')
    manager = LoginManager(app); manager.login_view = 'login.login'; manager.user_loader(lambda identity: ReviewUser(identity))
    app.add_url_rule('/login', 'login.login', lambda: 'login'); app.add_url_rule('/csrf', 'csrf', generate_csrf)
    CSRFProtect(app); app.register_blueprint(routes.admin2_bp)
    row = {'id': 1, 'library_platform': 'NES', 'region': 'USA', 'source': 'nointro', 'name': 'Synthetic Review', 'entry_count': 1}
    upload = Mock(return_value=SimpleNamespace(**row, to_dict=lambda: row)); delete = Mock(return_value=True); listing = Mock(return_value=[]); session = Mock(); audit = Mock()
    monkeypatch.setattr(routes, 'upsert_reference_set', upload); monkeypatch.setattr(routes, 'delete_reference_set', delete)
    monkeypatch.setattr(routes, 'list_reference_sets', listing); monkeypatch.setattr(routes, 'db', SimpleNamespace(session=session)); monkeypatch.setattr(routes, 'log_system_event', audit)
    client = app.test_client()
    with client.session_transaction() as value: value['_user_id'] = 'admin'; value['_fresh'] = True
    return client, upload, delete, listing, session, audit, {'X-CSRFToken': client.get('/csrf').text}, row


def fields(raw=b'<datafile/>', **extra):
    return {'library_platform': 'NES', 'region': 'USA', 'source': 'nointro', 'file': (BytesIO(raw), 'synthetic.xml'), **extra}


def test_state_has_all_options_and_catalog_exclusions(harness):
    client, *_ = harness
    response = client.get('/api/admin/reference-sets')
    assert response.status_code == 200 and response.headers['Cache-Control'] == 'no-store'
    assert response.json['max_dat_bytes'] == 32 * 1024 * 1024
    assert {p['id'] for p in response.json['platforms']} == {p.name for p in routes.LibraryPlatform}
    assert not ({p['id'] for p in response.json['catalog_platforms']} & set(routes.NATIVE_PC_PLATFORMS))
    assert response.json['sources'] == sorted(routes.VALID_SOURCES)


def test_admin_page_uses_shared_shell_and_loads_state_through_api(harness, monkeypatch):
    client, _, _, listing, _, _, _, _ = harness
    rendered = []
    monkeypatch.setattr(routes, 'render_admin_spa', lambda *, title: rendered.append(title) or '<main>shell</main>')
    response = client.get('/admin/reference_sets')
    assert response.status_code == 200
    assert response.text == '<main>shell</main>'
    assert rendered == ['Reference sets · Oneirodex Admin']
    listing.assert_not_called()


def test_upload_preserves_bytes_parser_and_normalization_helper(harness):
    client, upload, _, _, _, audit, headers, row = harness
    response = client.post('/api/admin/reference-sets', data=fields(), headers=headers)
    assert response.status_code == 201 and response.json['reference_set'] == row
    upload.assert_called_once_with(library_platform='NES', region='USA', source='nointro', dat_bytes=b'<datafile/>', uploader_id='admin', allow_replace=False)
    audit.assert_called_once()


def test_replacement_requires_explicit_confirmation(harness):
    client, upload, _, listing, _, _, headers, row = harness
    listing.return_value = [row]
    assert client.post('/api/admin/reference-sets', data=fields(), headers=headers).status_code == 409
    upload.assert_not_called()
    assert client.post('/api/admin/reference-sets', data=fields(replace='true'), headers=headers).status_code == 201
    assert upload.call_count == 1
    assert upload.call_args.kwargs['allow_replace'] is True


def test_helper_conflict_after_api_listing_is_409(harness):
    client, upload, _, _, session, _, headers, _ = harness
    upload.side_effect = routes.ReferenceSetReplacementConflict('Confirmation required')
    response = client.post('/api/admin/reference-sets', data=fields(), headers=headers)
    assert response.status_code == 409
    assert upload.call_args.kwargs['allow_replace'] is False
    session.rollback.assert_called_once()


def test_helper_blocks_replacement_before_deletion_or_commit(monkeypatch):
    import oneirodex.utils.set_completion as helpers
    existing = SimpleNamespace(id=1)
    session = Mock()
    session.execute.return_value.scalars.return_value.first.return_value = existing
    monkeypatch.setattr(helpers, 'db', SimpleNamespace(session=session))
    monkeypatch.setattr(helpers, 'parse_dat_bytes', Mock(return_value=('Synthetic Review', [{'name': 'Review', 'normalized_name': 'review'}])))
    with pytest.raises(helpers.ReferenceSetReplacementConflict):
        helpers.upsert_reference_set(library_platform='NES', region='USA', source='nointro', dat_bytes=b'synthetic', allow_replace=False)
    session.delete.assert_not_called(); session.flush.assert_not_called(); session.add.assert_not_called(); session.commit.assert_not_called()
    # Existing callers omit the new option and retain their replacement behavior.
    helpers.upsert_reference_set(library_platform='NES', region='USA', source='nointro', dat_bytes=b'synthetic')
    session.delete.assert_called_once_with(existing); session.commit.assert_called_once()


@pytest.mark.parametrize('payload,error', [({}, 'DAT file required'), (fields(b''), 'Empty DAT file'),
    (fields(library_platform='UNKNOWN'), 'Could not parse'), (fields(region='x' * 65), 'Invalid platform')])
def test_invalid_uploads_do_not_persist(harness, payload, error):
    client, upload, _, _, _, _, headers, _ = harness
    response = client.post('/api/admin/reference-sets', data=payload, headers=headers)
    assert response.status_code == 400 and error in response.json['error']
    upload.assert_not_called()


def test_size_limit_and_parser_errors_are_safe(harness, monkeypatch):
    client, upload, _, _, session, _, headers, _ = harness
    monkeypatch.setattr(routes, 'MAX_DAT_BYTES', 8)
    assert client.post('/api/admin/reference-sets', data=fields(b'123456789'), headers=headers).status_code == 400
    upload.assert_not_called()
    upload.side_effect = ValueError('/private/path token parser failure')
    response = client.post('/api/admin/reference-sets', data=fields(b'bad'), headers=headers)
    assert response.status_code == 400 and '/private/path' not in response.text
    session.rollback.assert_called_once()
    upload.side_effect = RuntimeError('private failure')
    response = client.post('/api/admin/reference-sets', data=fields(b'bad'), headers=headers)
    assert response.status_code == 500 and 'private failure' not in response.text


def test_delete_notfound_and_safe_failure(harness):
    client, _, delete, _, session, audit, headers, _ = harness
    assert client.delete('/api/admin/reference-sets/1', headers=headers).status_code == 200
    delete.assert_called_once_with(1); audit.assert_called_once()
    delete.return_value = False
    assert client.delete('/api/admin/reference-sets/1', headers=headers).status_code == 404
    delete.side_effect = RuntimeError('/private/path')
    response = client.delete('/api/admin/reference-sets/1', headers=headers)
    assert response.status_code == 500 and '/private/path' not in response.text
    session.rollback.assert_called_once()


def test_acl_csrf_and_load_failure(harness):
    client, upload, delete, listing, _, _, headers, _ = harness
    listing.side_effect = RuntimeError('private error')
    response = client.get('/api/admin/reference-sets')
    assert response.status_code == 500 and 'private error' not in response.text
    assert client.post('/api/admin/reference-sets', data={}).status_code == 400
    assert client.delete('/api/admin/reference-sets/1').status_code == 400
    with client.session_transaction() as value: value['_user_id'] = 'member'
    assert client.get('/api/admin/reference-sets').status_code == 302
    assert client.post('/api/admin/reference-sets', data={}, headers=headers).status_code == 302
    assert client.delete('/api/admin/reference-sets/1', headers=headers).status_code == 302
    upload.assert_not_called(); delete.assert_not_called()
