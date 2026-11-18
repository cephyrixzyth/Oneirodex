"""The setup wizard's real path: the screens submit each step to /api/setup/step.

These replace form-POST tests of the retired /setup/<step> pages. The rules
they hold are the same: the first library must sit inside a declared library
location and exist, an OIDC issuer must use HTTPS, and invalid account or IGDB
details never advance the wizard.
"""
from sqlalchemy import select

from oneirodex.models import GlobalSettings, Library
from oneirodex.utils.setup import get_current_setup_step
from tests.test_routes_setup import _park_wizard_at, admin_user  # noqa: F401  (fixture)


def _admin_session(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _step(client, step, **fields):
    return client.post('/api/setup/step', json={'step': step, **fields})


def _message(response):
    body = response.get_json() or {}
    detail = body.get('detail')
    return ' '.join(str(part) for part in (body.get('error'), body.get('message'), detail) if part)


def test_first_library_outside_the_declared_locations_is_refused(client, db_session, admin_user, tmp_path):
    _park_wizard_at(db_session, 6)
    _admin_session(client, admin_user)
    folder = tmp_path / 'outside'
    folder.mkdir()

    response = _step(client, 6, library_name='Unsafe library', platform='NES',
                     folder_path=str(folder), scan_mode='folders', scan_depth=1)

    assert response.status_code == 422, response.get_json()
    assert 'outside the configured library locations' in _message(response)
    assert db_session.execute(select(Library).filter_by(name='Unsafe library')).scalars().first() is None
    assert get_current_setup_step() == 6


def test_first_library_that_does_not_exist_is_refused(client, db_session, admin_user, tmp_path, monkeypatch):
    monkeypatch.setattr('oneirodex.utils.security.get_allowed_base_directories', lambda *_a, **_k: [str(tmp_path)])
    _park_wizard_at(db_session, 6)
    _admin_session(client, admin_user)

    response = _step(client, 6, library_name='Missing path library', platform='NES',
                     folder_path=str(tmp_path / 'not-created'), scan_mode='folders', scan_depth=1)

    assert response.status_code == 422, response.get_json()
    assert 'not available as a directory' in _message(response)
    assert db_session.execute(select(Library).filter_by(name='Missing path library')).scalars().first() is None


def test_oidc_issuer_with_a_non_http_scheme_is_refused(client, db_session, admin_user):
    _park_wizard_at(db_session, 5)
    _admin_session(client, admin_user)

    response = _step(client, 5, configure_oidc=True, oidc_issuer_url='file:///etc/passwd',
                     oidc_client_id='invalid-scheme')

    assert response.status_code == 422, response.get_json()
    assert 'must be an HTTP or HTTPS URL' in _message(response)
    assert get_current_setup_step() == 5


def test_oidc_issuer_over_plain_http_is_refused_and_nothing_is_saved(client, db_session, admin_user):
    _park_wizard_at(db_session, 5)
    _admin_session(client, admin_user)

    response = _step(client, 5, configure_oidc=True, oidc_issuer_url='http://idp.example.test',
                     oidc_client_id='cleartext-risk', oidc_client_secret='must-not-be-saved')

    assert response.status_code == 422, response.get_json()
    assert 'must use HTTPS' in _message(response)
    assert get_current_setup_step() == 5
    db_session.expire_all()
    settings = db_session.execute(select(GlobalSettings).order_by(GlobalSettings.id).limit(1)).scalars().first()
    assert settings.oidc_issuer_url in (None, '')
    assert 'must-not-be-saved' not in str(settings.oidc_client_secret or '')


def test_invalid_administrator_details_are_refused(client, db_session):
    from tests.test_routes_setup import safe_cleanup_users_and_related

    safe_cleanup_users_and_related(db_session)
    response = _step(client, 1, username='a', email='invalid-email',
                     password='short', confirm_password='different')

    assert response.status_code == 422, response.get_json()
    assert response.get_json()['ok'] is False


def test_too_short_igdb_credentials_do_not_advance_the_wizard(client, db_session, admin_user):
    _park_wizard_at(db_session, 4)
    _admin_session(client, admin_user)

    response = _step(client, 4, igdb_client_id='short', igdb_client_secret='short')

    assert response.status_code == 422, response.get_json()
    assert set(response.get_json()['detail']) == {'igdb_client_id', 'igdb_client_secret'}
    assert get_current_setup_step() == 4
