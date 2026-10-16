"""Shared Attract Mode defaults used by legacy and native handlers."""

DEFAULT_ATTRACT_MODE_SETTINGS = {
    'filters': {
        'library_uuid': None,
        'genres': [],
        'themes': [],
        'date_from': None,
        'date_to': None,
    },
    'autoplay': {
        'enabled': True,
        'skipFirst': 0,
        'skipAfter': 0,
    },
}
