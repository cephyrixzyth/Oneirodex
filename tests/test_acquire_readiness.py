from oneirodex.utils import acquire_readiness


def test_disabled_arr_returns_empty_indexer_readiness(monkeypatch):
    monkeypatch.setattr('oneirodex.utils.module_status.arr_module_on', lambda **_kwargs: False)
    assert acquire_readiness.indexer_readiness({'ENABLE_ARR_MODULE': False}) == {
        'native_ready': False,
        'hubs_ready': False,
        'indexers_ready': False,
        'indexer_warnings': [],
        'native_count': 0,
        'native_ready_count': 0,
    }


def test_indexer_readiness_combines_native_and_hub_state(monkeypatch):
    monkeypatch.setattr('oneirodex.utils.module_status.arr_module_on', lambda **_kwargs: True)
    monkeypatch.setattr(
        'oneirodex.utils.indexer_registry.indexer_status_summary',
        lambda: {'configured': False, 'warnings': ['No native indexer'], 'count': 4, 'ready': 0},
    )
    monkeypatch.setattr(
        'oneirodex.utils.arr_connectors.get_arr_config',
        lambda **_kwargs: {'prowlarr_url': 'https://indexer.example', 'prowlarr_api_key': 'configured'},
    )
    assert acquire_readiness.indexer_readiness({}) == {
        'native_ready': False,
        'hubs_ready': True,
        'indexers_ready': True,
        'indexer_warnings': ['No native indexer'],
        'native_count': 4,
        'native_ready_count': 0,
    }


def test_acquire_allowed_combines_arr_and_debrid_flags(monkeypatch):
    states = {'arr': False, 'debrid': False}
    monkeypatch.setattr(
        'oneirodex.utils.module_status.arr_module_on', lambda **_kwargs: states['arr'],
    )
    monkeypatch.setattr(
        'oneirodex.utils.debrid_connectors.debrid_enabled', lambda **_kwargs: states['debrid'],
    )
    assert acquire_readiness.acquire_allowed({}) is False
    states['debrid'] = True
    assert acquire_readiness.acquire_allowed({}) is True
    states['arr'] = True
    states['debrid'] = False
    assert acquire_readiness.acquire_allowed({}) is True
