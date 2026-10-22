from oneirodex.runtime_native.setup_transition import _setup_form_payload


def test_setup_password_mismatch_returns_to_setup_wizard():
    payload, return_to, error = _setup_form_payload(
        '/setup/submit',
        {
            'username': 'ParityAdmin',
            'email': 'parity@example.test',
            'password': 'ParityPassword1!',
            'confirm_password': 'DifferentPassword1!',
        },
    )

    assert payload is None
    assert return_to == '/setup'
    assert error == 'Passwords must match.'


def test_setup_step_validation_returns_to_its_wizard_route():
    payload, return_to, error = _setup_form_payload(
        '/setup/library',
        {'name': 'Retro', 'platform': 'NES', 'scan_depth': '99'},
    )

    assert payload is None
    assert return_to == '/setup/library'
    assert error == 'Please check the setup form and try again.'


def test_setup_integrations_form_carries_provider_configure_checkboxes():
    payload, return_to, error = _setup_form_payload(
        '/setup/integrations',
        {
            'steam_web_api_key': 'typed-but-unchecked',
            'steamgriddb_api_key': 'typed-and-selected',
            'configure_steamgriddb_api_key': 'on',
            'configure_oidc': 'on',
            'oidc_issuer_url': 'https://identity.example.test',
        },
    )

    assert error is None
    assert return_to == '/setup/integrations'
    assert payload['steam_web_api_key'] == 'typed-but-unchecked'
    assert payload['configure_steam_web_api_key'] is False
    assert payload['steamgriddb_api_key'] == 'typed-and-selected'
    assert payload['configure_steamgriddb_api_key'] is True
    assert payload['configure_oidc'] is True
