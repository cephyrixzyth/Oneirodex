"""Oneirodex ORM models.

Historically one ~2200-line ``oneirodex/models.py``; split by domain in
wave A2.2. Every ``from oneirodex.models import X`` still resolves through
the star re-exports below. Import order is for readability only -- all
cross-domain relationships are string-form and resolve lazily at mapper
configuration. Model metadata is framework-independent so native routes can
load mapped classes without importing Flask.
"""
from oneirodex.platform import LibraryPlatform  # noqa: F401  -- re-export (forms.py)

from oneirodex.models._base import *  # noqa: F401,F403
from oneirodex.models.catalog import *  # noqa: F401,F403
from oneirodex.models.users import *  # noqa: F401,F403
from oneirodex.models.library import *  # noqa: F401,F403
from oneirodex.models.social import *  # noqa: F401,F403
from oneirodex.models.discover import *  # noqa: F401,F403
from oneirodex.models.ownership import *  # noqa: F401,F403
from oneirodex.models.misc import *  # noqa: F401,F403

from oneirodex.models._base import __all__ as _base_all
from oneirodex.models.catalog import __all__ as _catalog_all
from oneirodex.models.users import __all__ as _users_all
from oneirodex.models.library import __all__ as _library_all
from oneirodex.models.social import __all__ as _social_all
from oneirodex.models.discover import __all__ as _discover_all
from oneirodex.models.ownership import __all__ as _ownership_all
from oneirodex.models.misc import __all__ as _misc_all

__all__ = ["LibraryPlatform"] + list(_base_all) + list(_catalog_all) + list(_users_all) + list(_library_all) + list(_social_all) + list(_discover_all) + list(_ownership_all) + list(_misc_all)


def __getattr__(name):
    """Load the Flask extension only for legacy callers that request ``db``."""
    if name == 'db':
        from oneirodex import db

        return db
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
