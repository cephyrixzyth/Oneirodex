"""Contract checks for the framework-independent SimpleCache replacement."""
from oneirodex.utils.cache import ProcessCache


def test_cache_timeout_defaults_to_five_minutes(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr('oneirodex.utils.cache.time.time', lambda: now[0])
    cache = ProcessCache()
    assert cache.set('item', {'value': 1})
    now[0] = 1299.0
    assert cache.get('item') == {'value': 1}
    now[0] = 1300.0
    assert cache.get('item') is None


def test_cache_zero_timeout_is_non_expiring_and_values_are_serialized(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr('oneirodex.utils.cache.time.time', lambda: now[0])
    cache = ProcessCache()
    value = {'nested': [1]}
    assert cache.set('item', value, timeout=0)
    value['nested'].append(2)
    now[0] = 10_000_000.0
    assert cache.get('item') == {'nested': [1]}


def test_cache_delete_clear_and_threshold_pruning(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr('oneirodex.utils.cache.time.time', lambda: now[0])
    cache = ProcessCache(default_timeout=30, threshold=2)
    cache.set('first', 1, timeout=20)
    cache.set('second', 2, timeout=40)
    cache.set('third', 3, timeout=60)
    assert len(cache._entries) == 2
    assert cache.get('first') is None
    assert cache.delete('second')
    assert not cache.delete('missing')
    assert cache.clear()
    assert cache.get('third') is None
