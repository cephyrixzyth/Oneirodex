"""JSON setup state transitions preserve first-run admin/session gates."""


def test_first_run_setup_advances_with_existing_session_without_returning_secrets(client, db_session):
    state = client.get('/api/setup/state')
    assert state.status_code == 200
    assert state.headers['cache-control'] == 'no-store'
    assert state.get_json()['step'] == 1
    assert state.get_json()['required'] is True

    created = client.post('/api/setup/step', json={
        'step': 1,
        'username': 'setup_admin',
        'email': 'setup_admin@example.com',
        'password': 'correct horse battery',
        'confirm_password': 'correct horse battery',
    })
    assert created.status_code == 200
    assert created.get_json()['step'] == 2
    assert created.get_json()['next_url'] == '/setup/smtp'
    assert client.get('/api/account/summary').status_code == 200

    saved = client.post('/api/setup/step', json={
        'step': 2,
        'smtp_server': 'mail.example.com',
        'smtp_port': 587,
        'smtp_username': 'setup@example.com',
        'smtp_password': 'smtp-secret-never-return',
        'smtp_default_sender': 'setup@example.com',
        'smtp_use_tls': True,
        'smtp_enabled': True,
    })
    assert saved.status_code == 200
    assert saved.get_json()['step'] == 3
    next_state = client.get('/api/setup/state').get_json()
    assert next_state['settings']['smtp_password_configured'] is True
    assert 'smtp-secret-never-return' not in str(next_state)
    assert next_state['settings']['smtp_server'] == 'mail.example.com'


def test_setup_api_rejects_out_of_order_and_invalid_admin_transitions(client):
    out_of_order = client.post('/api/setup/step', json={'step': 2, 'skip': True})
    assert out_of_order.status_code == 409
    assert out_of_order.get_json()['error_code'] == 'conflict'

    invalid_admin = client.post('/api/setup/step', json={
        'step': 1,
        'username': 'bad name',
        'email': 'invalid',
        'password': 'short',
        'confirm_password': 'different',
    })
    assert invalid_admin.status_code == 422
    assert invalid_admin.get_json()['error_code'] == 'unprocessable'


def test_setup_skip_path_resumes_and_completes_each_ordered_step(client, db_session, monkeypatch):
    import oneirodex.init_data as init_data

    for name in (
        'initialize_library_folders', 'initialize_discovery_sections',
        'insert_default_scanning_filters', 'initialize_default_settings',
        'initialize_allowed_file_types',
    ):
        monkeypatch.setattr(init_data, name, lambda **_kwargs: None)

    created = client.post('/api/setup/step', json={
        'step': 1, 'username': 'skip_admin', 'email': 'skip@example.com',
        'password': 'correct horse battery', 'confirm_password': 'correct horse battery',
    })
    assert created.status_code == 200
    assert client.post('/api/setup/step', json={'step': 2, 'skip': True}).get_json()['step'] == 3
    assert client.post('/api/setup/step', json={'step': 3}).get_json()['step'] == 4
    assert client.post('/api/setup/step', json={'step': 4, 'skip': True}).get_json()['step'] == 5
    assert client.post('/api/setup/step', json={'step': 5, 'skip': True}).get_json()['step'] == 6
    finished = client.post('/api/setup/step', json={'step': 6, 'skip': True})
    assert finished.status_code == 200
    assert finished.get_json()['complete'] is True
    assert client.get('/api/setup/state').get_json()['complete'] is True


def test_setup_api_requires_admin_for_wizard_state(client, db_session):
    from oneirodex.models import User
    from oneirodex.utils.setup import set_setup_step

    user = User(
        name='existing_admin', email='existing@example.com', role='admin',
        password_hash='placeholder', user_id='existing-admin', is_email_verified=True,
    )
    user.set_password('correct horse battery')
    db_session.add(user)
    db_session.commit()
    set_setup_step(2)
    response = client.get('/api/setup/state')
    assert response.status_code == 401
    assert response.get_json()['error_code'] == 'unauthorized'


def test_integrations_json_transition_respects_provider_configure_checkboxes(client, db_session):
    from sqlalchemy import select

    from oneirodex.models import GlobalSettings

    created = client.post('/api/setup/step', json={
        'step': 1, 'username': 'provider_admin', 'email': 'provider@example.com',
        'password': 'correct horse battery', 'confirm_password': 'correct horse battery',
    })
    assert created.status_code == 200
    assert client.post('/api/setup/step', json={'step': 2, 'skip': True}).status_code == 200
    assert client.post('/api/setup/step', json={'step': 3}).status_code == 200
    assert client.post('/api/setup/step', json={'step': 4, 'skip': True}).status_code == 200

    settings = db_session.execute(select(GlobalSettings)).scalars().first()
    settings.steam_web_api_key = 'existing-steam-key'
    settings.steamgriddb_api_key = 'existing-grid-key'
    settings.giantbomb_api_key = 'existing-giantbomb-key'
    db_session.commit()

    response = client.post('/api/setup/step', json={
        'step': 5,
        'steam_web_api_key': 'unchecked-replacement',
        'configure_steam_web_api_key': False,
        'steamgriddb_api_key': 'selected-replacement',
        'configure_steamgriddb_api_key': True,
        'giantbomb_api_key': '',
        'configure_giantbomb_api_key': True,
    })

    assert response.status_code == 200
    assert response.get_json()['step'] == 6
    db_session.refresh(settings)
    assert settings.steam_web_api_key == 'existing-steam-key'
    assert settings.steamgriddb_api_key == 'selected-replacement'
    assert settings.giantbomb_api_key == 'existing-giantbomb-key'


def test_integrations_reject_provider_key_larger_than_storage_column(client, db_session):
    from sqlalchemy import select

    from oneirodex.models import GlobalSettings

    created = client.post('/api/setup/step', json={
        'step': 1, 'username': 'provider_limit_admin',
        'email': 'provider-limit@example.com',
        'password': 'correct horse battery',
        'confirm_password': 'correct horse battery',
    })
    assert created.status_code == 200
    assert client.post('/api/setup/step', json={'step': 2, 'skip': True}).status_code == 200
    assert client.post('/api/setup/step', json={'step': 3}).status_code == 200
    assert client.post('/api/setup/step', json={'step': 4, 'skip': True}).status_code == 200

    response = client.post('/api/setup/step', json={
        'step': 5,
        'configure_steam_web_api_key': True,
        'steam_web_api_key': 'k' * 256,
    })

    assert response.status_code == 422
    assert response.get_json()['error_code'] == 'unprocessable'
    assert '255 characters' in str(response.get_json()['detail'])
    settings = db_session.execute(select(GlobalSettings)).scalars().first()
    assert settings.steam_web_api_key is None
    assert settings.setup_current_step == 5


def test_integrations_accept_provider_key_at_storage_column_limit(client, db_session):
    from sqlalchemy import select

    from oneirodex.models import GlobalSettings

    created = client.post('/api/setup/step', json={
        'step': 1, 'username': 'provider_boundary_admin',
        'email': 'provider-boundary@example.com',
        'password': 'correct horse battery',
        'confirm_password': 'correct horse battery',
    })
    assert created.status_code == 200
    assert client.post('/api/setup/step', json={'step': 2, 'skip': True}).status_code == 200
    assert client.post('/api/setup/step', json={'step': 3}).status_code == 200
    assert client.post('/api/setup/step', json={'step': 4, 'skip': True}).status_code == 200

    key = 'k' * 255
    response = client.post('/api/setup/step', json={
        'step': 5,
        'configure_steam_web_api_key': True,
        'steam_web_api_key': key,
    })

    assert response.status_code == 200
    settings = db_session.execute(select(GlobalSettings)).scalars().first()
    assert settings.steam_web_api_key == key
    assert settings.setup_current_step == 6
