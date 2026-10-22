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
