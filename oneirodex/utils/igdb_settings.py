"""Framework-independent, secret-safe IGDB settings projection."""


def igdb_public_state(settings):
    return {
        'igdb_client_id': settings.igdb_client_id or '' if settings else '',
        'secret_present': bool(settings and settings.igdb_client_secret),
        'last_tested': settings.igdb_last_tested.isoformat()
        if settings and settings.igdb_last_tested else None,
    }


def validate_igdb_data(data):
    if (
        not isinstance(data, dict)
        or 'igdb_client_id' not in data
        or set(data) - {'igdb_client_id', 'igdb_client_secret'}
    ):
        raise ValueError('A JSON object containing only the client ID and secret is required')
    result = {}
    for key in ('igdb_client_id', 'igdb_client_secret'):
        value = data.get(key, '')
        if not isinstance(value, str) or len(value) > 255 or any(ord(char) < 32 for char in value):
            raise ValueError('Client ID and secret must be text of at most 255 characters without control characters')
        result[key] = value.strip() if key == 'igdb_client_id' else value
    return result
