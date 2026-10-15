"""Grab-bag utility helpers.

Historically one ~928-line module; split by responsibility in wave A2.3
into ``oneirodex/utils/helpers/`` (pure/leaf) and ``oneirodex/utils/clients/``
(outbound image download). Every ``from oneirodex.utils.functions import X``
still resolves through the star re-exports below, and every attribute a test
patches as ``oneirodex.utils.functions.<name>`` is still reachable here.
"""
from oneirodex.runtime_native.db_session import native_db as db  # noqa: F401 -- legacy-compatible re-export; native workers use their active session

from oneirodex.utils.helpers.fs import *  # noqa: F401,F403
from oneirodex.utils.helpers.images import *  # noqa: F401,F403
from oneirodex.utils.helpers.strings import *  # noqa: F401,F403
from oneirodex.utils.helpers.urls import *  # noqa: F401,F403
from oneirodex.utils.helpers.platforms import *  # noqa: F401,F403
from oneirodex.utils.helpers.scan_filters import *  # noqa: F401,F403
from oneirodex.utils.helpers.counts import *  # noqa: F401,F403
from oneirodex.utils.clients.images import *  # noqa: F401,F403

# Incidental module-level imports the old grab-bag exposed; kept so existing
# ``patch('oneirodex.utils.functions.<name>')`` call sites keep resolving even
# though the code that reads them now lives in the submodule above.
from oneirodex.utils.helpers.images import PILImage  # noqa: F401
from oneirodex.utils.security import (  # noqa: F401
    get_allowed_base_directories,
    is_safe_path,
    validate_user_outbound_http_url,
)
from oneirodex.utils.http_safe import safe_get  # noqa: F401

from oneirodex.utils.helpers.fs import __all__ as _fs_all
from oneirodex.utils.helpers.images import __all__ as _images_all
from oneirodex.utils.helpers.strings import __all__ as _strings_all
from oneirodex.utils.helpers.urls import __all__ as _urls_all
from oneirodex.utils.helpers.platforms import __all__ as _platforms_all
from oneirodex.utils.helpers.scan_filters import __all__ as _scan_filters_all
from oneirodex.utils.helpers.counts import __all__ as _counts_all
from oneirodex.utils.clients.images import __all__ as _client_images_all

__all__ = (
    ["db", "PILImage", "get_allowed_base_directories", "is_safe_path",
     "validate_user_outbound_http_url", "safe_get"]
    + list(_fs_all) + list(_images_all) + list(_strings_all) + list(_urls_all)
    + list(_platforms_all) + list(_scan_filters_all) + list(_counts_all)
    + list(_client_images_all)
)
