"""Framework-neutral Acquire readiness projections shared by API runtimes."""
from __future__ import annotations


def acquire_allowed(config=None) -> bool:
    from oneirodex.utils.debrid_connectors import debrid_enabled
    from oneirodex.utils.module_status import arr_module_on

    return arr_module_on(config=config) or debrid_enabled(config=config)


def indexer_readiness(config=None) -> dict:
    """Return native/indexer-hub readiness for the Acquire empty state."""
    from oneirodex.utils.arr_connectors import get_arr_config
    from oneirodex.utils.indexer_registry import indexer_status_summary
    from oneirodex.utils.module_status import arr_module_on

    if not arr_module_on(config=config):
        return {
            'native_ready': False,
            'hubs_ready': False,
            'indexers_ready': False,
            'indexer_warnings': [],
            'native_count': 0,
            'native_ready_count': 0,
        }
    native = indexer_status_summary()
    cfg = get_arr_config(config=config)
    hubs_ready = bool(
        (cfg.get('prowlarr_url') and cfg.get('prowlarr_api_key'))
        or (cfg.get('jackett_url') and cfg.get('jackett_api_key'))
    )
    native_ready = bool(native.get('configured'))
    return {
        'native_ready': native_ready,
        'hubs_ready': hubs_ready,
        'indexers_ready': native_ready or hubs_ready,
        'indexer_warnings': list(native.get('warnings') or []),
        'native_count': int(native.get('count') or 0),
        'native_ready_count': int(native.get('ready') or 0),
    }
