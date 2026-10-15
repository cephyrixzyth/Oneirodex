"""Member-blueprint SPA shells must carry global nav flags.

``/systems``, ``/chat``, ``/collections`` and the rest of ``member_bp`` used
to render ``member_spa.html`` without a settings context processor. The
Python-built shell now resolves the shared settings contract for every route, so
``show_trailers`` / ``show_help_button`` cannot silently default false and the
React rail hid Help and Trailers on a full load of those routes — while
``/discover`` and ``/favorites`` (other blueprints) stayed correct.
"""

from uuid import uuid4
from unittest.mock import patch

import pytest

from oneirodex.models import User


@pytest.fixture
def test_user(db_session):
    user_uuid = str(uuid4())
    user = User(
        name=f'testuser_{user_uuid[:8]}',
        email=f'test_{user_uuid[:8]}@example.com',
        password_hash='hashed_password',
        role='user',
        user_id=user_uuid,
    )
    db_session.add(user)
    db_session.commit()
    return user


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


class TestMemberBlueprintSettings:
    def test_inject_settings_context_processor(self, app):
        with app.app_context():
            from oneirodex.routes_member import inject_settings

            with patch(
                'oneirodex.routes_member.get_global_settings',
                return_value={'show_trailers': True},
            ) as mocked:
                assert inject_settings() == {'show_trailers': True}
            mocked.assert_called_once()

    def test_systems_shell_defaults_help_and_trailers_on(
        self, client, test_user, configured_install,
    ):
        _login(client, test_user)
        html = client.get('/systems').get_data(as_text=True)
        assert 'id="member-app-root"' in html
        assert 'data-show-trailers="true"' in html
        assert 'data-show-help="true"' in html

    def test_systems_catalog_and_completion_shells(
        self, client, test_user, configured_install,
    ):
        _login(client, test_user)
        catalog = client.get('/systems/catalog?library_platform=NES')
        assert catalog.status_code == 200
        assert 'id="member-app-root"' in catalog.get_data(as_text=True)
        completion = client.get('/systems/completion?library_platform=NES')
        assert completion.status_code == 200
        assert 'id="member-app-root"' in completion.get_data(as_text=True)

    def test_ways_to_play_shell_defaults_help_and_trailers_on(
        self, client, test_user, configured_install,
    ):
        _login(client, test_user)
        html = client.get('/ways-to-play').get_data(as_text=True)
        assert 'id="member-app-root"' in html
        assert 'data-show-trailers="true"' in html
        assert 'data-show-help="true"' in html

    def test_chat_shell_defaults_help_and_trailers_on(
        self, client, test_user, configured_install,
    ):
        _login(client, test_user)
        html = client.get('/chat').get_data(as_text=True)
        assert 'data-show-trailers="true"' in html
        assert 'data-show-help="true"' in html

    def test_systems_shell_respects_disabled_trailers(
        self, client, test_user, configured_install, db_session,
    ):
        settings = dict(configured_install.settings or {})
        settings['showTrailers'] = False
        configured_install.settings = settings
        db_session.commit()

        _login(client, test_user)
        html = client.get('/systems').get_data(as_text=True)
        assert 'data-show-trailers="false"' in html
        assert 'data-show-help="true"' in html
