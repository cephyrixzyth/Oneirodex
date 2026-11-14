from unittest.mock import MagicMock, patch

import pytest

from oneirodex.utils.smtp_transport import open_smtp_connection, upgrade_smtp_connection


def test_port_465_uses_ssl_smtp_and_default_verification_context():
    context = MagicMock()
    with (
        patch('oneirodex.utils.smtp_transport.ssl.create_default_context', return_value=context),
        patch('oneirodex.utils.smtp_transport.smtplib.SMTP_SSL') as smtp_ssl,
        patch('oneirodex.utils.smtp_transport.smtplib.SMTP') as smtp,
    ):
        connection = open_smtp_connection(
            'smtp.example.com', 465, use_tls=True, timeout=12
        )

    assert connection is smtp_ssl.return_value
    smtp_ssl.assert_called_once_with(
        'smtp.example.com', 465, timeout=12, context=context
    )
    smtp.assert_not_called()


def test_port_465_rejects_disabled_tls_without_opening_a_socket():
    with patch('oneirodex.utils.smtp_transport.smtplib.SMTP_SSL') as smtp_ssl:
        with pytest.raises(ValueError, match='TLS is required for SMTP port 465'):
            open_smtp_connection('smtp.example.com', 465, use_tls=False, timeout=12)

    smtp_ssl.assert_not_called()


def test_other_tls_ports_use_starttls_with_verified_context():
    connection = MagicMock()
    context = MagicMock()
    with patch('oneirodex.utils.smtp_transport.ssl.create_default_context', return_value=context):
        upgrade_smtp_connection(connection, 587, use_tls=True)

    connection.starttls.assert_called_once_with(context=context)


def test_port_465_does_not_send_starttls_after_implicit_tls():
    connection = MagicMock()
    with patch('oneirodex.utils.smtp_transport.ssl.create_default_context') as context:
        upgrade_smtp_connection(connection, 465, use_tls=True)

    connection.starttls.assert_not_called()
    context.assert_not_called()


def test_quiet_sender_uses_implicit_tls_for_port_465():
    from oneirodex.utils import smtp

    settings = {
        'SMTP_ENABLED': True,
        'MAIL_SERVER': 'smtp.example.com',
        'MAIL_PORT': 465,
        'MAIL_USERNAME': 'mailer',
        'MAIL_PASSWORD': 'secret',
        'MAIL_USE_TLS': True,
        'MAIL_DEFAULT_SENDER': 'sender@example.com',
    }
    connection = MagicMock()
    connection.__enter__.return_value = connection
    with (
        patch.object(smtp, 'get_smtp_settings', return_value=settings),
        patch.object(smtp, 'is_smtp_config_valid', return_value=(True, 'Configuration valid')),
        patch.object(smtp, 'log_system_event'),
        patch('oneirodex.utils.smtp_transport.smtplib.SMTP_SSL', return_value=connection) as ssl_smtp,
        patch('oneirodex.utils.smtp_transport.smtplib.SMTP') as plain_smtp,
    ):
        assert smtp.send_email_quiet('to@example.com', 'Subject', '<p>Body</p>') is True

    ssl_smtp.assert_called_once()
    plain_smtp.assert_not_called()
    connection.starttls.assert_not_called()
    connection.login.assert_called_once_with('mailer', 'secret')
    connection.send_message.assert_called_once()


def test_interactive_sender_uses_implicit_tls_for_port_465():
    from oneirodex.utils import smtp

    settings = {
        'SMTP_ENABLED': True,
        'MAIL_SERVER': 'smtp.example.com',
        'MAIL_PORT': 465,
        'MAIL_USERNAME': 'mailer',
        'MAIL_PASSWORD': 'secret',
        'MAIL_USE_TLS': True,
        'MAIL_DEFAULT_SENDER': 'sender@example.com',
    }
    connection = MagicMock()
    connection.__enter__.return_value = connection
    with (
        patch.object(smtp, 'get_smtp_settings', return_value=settings),
        patch.object(smtp, 'is_smtp_config_valid', return_value=(True, 'Configuration valid')),
        patch.object(smtp, 'is_server_reachable', return_value=True),
        patch.object(smtp, 'log_system_event'),
        patch('flask.flash'),
        patch('builtins.print'),
        patch('oneirodex.utils.smtp_transport.smtplib.SMTP_SSL', return_value=connection) as ssl_smtp,
        patch('oneirodex.utils.smtp_transport.smtplib.SMTP') as plain_smtp,
    ):
        assert smtp.send_email('to@example.com', 'Subject', '<p>Body</p>') is True

    ssl_smtp.assert_called_once()
    plain_smtp.assert_not_called()
    connection.starttls.assert_not_called()
    connection.login.assert_called_once_with('mailer', 'secret')
    connection.send_message.assert_called_once()


def test_smtp_config_requires_tls_for_port_465():
    from oneirodex.utils.smtp import is_smtp_config_valid

    settings = {
        'SMTP_ENABLED': True,
        'MAIL_SERVER': 'smtp.example.com',
        'MAIL_PORT': 465,
        'MAIL_USERNAME': 'mailer',
        'MAIL_PASSWORD': 'secret',
        'MAIL_USE_TLS': False,
        'MAIL_DEFAULT_SENDER': 'sender@example.com',
    }
    with patch('oneirodex.utils.smtp.get_smtp_settings', return_value=settings):
        assert is_smtp_config_valid() == (False, 'TLS is required for SMTP port 465')
