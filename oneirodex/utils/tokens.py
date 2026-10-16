"""Signed-token helpers.

``get_serializer`` was defined (identically) in both ``oneirodex/routes.py`` and
``oneirodex/routes_login.py``. Wave A2.1f retired the ``'main'`` blueprint, so the
canonical copy now lives here and ``routes_login`` imports it.
"""

from itsdangerous import URLSafeTimedSerializer
from oneirodex.utils.runtime_config import get_runtime_config


def get_serializer() -> URLSafeTimedSerializer:
    """Return a ``URLSafeTimedSerializer`` keyed by the active app's SECRET_KEY."""
    return URLSafeTimedSerializer(get_runtime_config()['SECRET_KEY'])
