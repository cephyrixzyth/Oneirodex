"""Framework-independent public view of persisted SMTP configuration."""


def smtp_public_state(settings):
    """Safe form state: the saved credential never leaves the server."""
    return {
        'smtp_enabled': bool(settings and settings.smtp_enabled),
        'smtp_server': settings.smtp_server or '' if settings else '',
        'smtp_port': settings.smtp_port or 587 if settings else 587,
        'smtp_username': settings.smtp_username or '' if settings else '',
        'smtp_use_tls': bool(settings.smtp_use_tls) if settings else True,
        'smtp_default_sender': settings.smtp_default_sender or '' if settings else '',
        'password_saved': bool(settings and settings.smtp_password),
        'last_tested': settings.smtp_last_tested.isoformat() if settings and settings.smtp_last_tested else None,
    }


def validate_smtp_data(data, settings):
    if not isinstance(data, dict):
        raise ValueError('A JSON settings object is required')
    for key in ('smtp_enabled', 'smtp_use_tls'):
        if not isinstance(data.get(key), bool):
            raise ValueError('SMTP enabled and TLS must be boolean values')
    result = {key: data[key] for key in ('smtp_enabled', 'smtp_use_tls')}
    for key in ('smtp_server', 'smtp_username', 'smtp_password', 'smtp_default_sender'):
        value = data.get(key, '')
        if not isinstance(value, str) or len(value) > 255 or any(ord(char) < 32 for char in value):
            raise ValueError('SMTP fields must be text of at most 255 characters without control characters')
        result[key] = value if key == 'smtp_password' else value.strip()
    value = data.get('smtp_port')
    if isinstance(value, bool) or not isinstance(value, (int, str)) or not str(value).isdigit():
        raise ValueError('SMTP port must be a whole number between 1 and 65535')
    port = int(value)
    if not 1 <= port <= 65535:
        raise ValueError('SMTP port must be between 1 and 65535')
    result['smtp_port'] = port
    if result['smtp_default_sender']:
        from email_validator import validate_email, EmailNotValidError
        try:
            validate_email(result['smtp_default_sender'], check_deliverability=False)
        except EmailNotValidError:
            raise ValueError('Default sender must be a valid email address') from None
    if result['smtp_server']:
        from oneirodex.utils.smtp_test import SMTPTester
        valid, _ = SMTPTester(debug=False)._validate_inputs(result['smtp_server'], port)
        if not valid:
            raise ValueError('SMTP server must be a valid hostname or IPv4 address')
    if result['smtp_enabled']:
        for key, label in (('smtp_server', 'SMTP server'), ('smtp_username', 'SMTP username'),
                           ('smtp_default_sender', 'Default sender email')):
            if not result[key]:
                raise ValueError(f'{label} is required when SMTP is enabled')
        if not result['smtp_password'] and not (settings and settings.smtp_password):
            raise ValueError('SMTP password is required when SMTP is enabled')
    return result
