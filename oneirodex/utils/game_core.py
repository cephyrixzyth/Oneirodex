"""Game identify / enrichment / image-pipeline core.

Historically one ~2668-line module; split by responsibility in wave A2.3 into
``oneirodex/utils/services/`` (igdb_maps, entities, game_lookup, game_delete,
image_pipeline, game_enrich, scan_identify) and ``oneirodex/utils/clients/``
(igdb, images). Every ``from oneirodex.utils.game_core import X`` still resolves
through the star re-exports below, and every attribute a test patches as
``oneirodex.utils.game_core.<name>`` is still reachable here.
"""
import threading  # noqa: F401  -- re-export: `patch('oneirodex.utils.game_core.threading.Thread')`

from oneirodex.runtime_native.db_session import native_db as db

from oneirodex.utils.services.igdb_maps import *  # noqa: F401,F403
from oneirodex.utils.services.entities import *  # noqa: F401,F403
from oneirodex.utils.clients.igdb import *  # noqa: F401,F403
from oneirodex.utils.clients.images import *  # noqa: F401,F403
from oneirodex.utils.services.game_lookup import *  # noqa: F401,F403
from oneirodex.utils.services.game_delete import *  # noqa: F401,F403
from oneirodex.utils.services.image_pipeline import *  # noqa: F401,F403
from oneirodex.utils.services.game_enrich import *  # noqa: F401,F403
from oneirodex.utils.services.scan_identify import *  # noqa: F401,F403

# Incidental module-level imports the old god-module exposed; kept so existing
# ``patch('oneirodex.utils.game_core.<name>')`` call sites keep resolving even
# though the code that reads them now lives in a submodule above.
from oneirodex.utils.igdb_api import make_igdb_api_request  # noqa: F401
from oneirodex.utils.notifications import notify_admins_new_game  # noqa: F401
from oneirodex.utils.event_logging import log_system_event  # noqa: F401
from oneirodex.utils.metadata_enrichment import apply_enriched_metadata  # noqa: F401
from oneirodex.utils.secondary_scrapers import fetch_steam_data  # noqa: F401
from oneirodex.utils.steam_lookup import fetch_steam_title_by_app_id  # noqa: F401
from oneirodex.utils.match_scoring import select_best_match  # noqa: F401
from oneirodex.utils.software_identify import corroborate_igdb_with_catalogs  # noqa: F401
from oneirodex.utils.match_proposal import write_match_proposal  # noqa: F401
from oneirodex.utils.helpers.fs import (  # noqa: F401
    read_first_nfo_content,
    get_folder_size_in_bytes_updates,
)

from oneirodex.utils.services.igdb_maps import __all__ as _igdb_maps_all
from oneirodex.utils.services.entities import __all__ as _entities_all
from oneirodex.utils.clients.igdb import __all__ as _cli_igdb_all
from oneirodex.utils.clients.images import __all__ as _cli_images_all
from oneirodex.utils.services.game_lookup import __all__ as _game_lookup_all
from oneirodex.utils.services.game_delete import __all__ as _game_delete_all
from oneirodex.utils.services.image_pipeline import __all__ as _image_pipeline_all
from oneirodex.utils.services.game_enrich import __all__ as _game_enrich_all
from oneirodex.utils.services.scan_identify import __all__ as _scan_identify_all

__all__ = (
    ["db", "threading", "make_igdb_api_request", "notify_admins_new_game",
     "log_system_event", "apply_enriched_metadata", "fetch_steam_data",
     "fetch_steam_title_by_app_id", "select_best_match",
     "corroborate_igdb_with_catalogs", "write_match_proposal",
     "read_first_nfo_content", "get_folder_size_in_bytes_updates"]
    + list(_igdb_maps_all) + list(_entities_all) + list(_cli_igdb_all)
    + list(_cli_images_all) + list(_game_lookup_all) + list(_game_delete_all)
    + list(_image_pipeline_all) + list(_game_enrich_all) + list(_scan_identify_all)
)
