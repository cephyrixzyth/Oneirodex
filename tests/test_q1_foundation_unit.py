"""Pure unit tests that do not require PostgreSQL."""

import threading

from oneirodex.utils.event_bus import EventBus, encode_sse
from oneirodex.utils.api_tokens import VALID_SCOPES, TOKEN_PREFIX, _hash_secret


def test_event_bus_fanout():
    bus = EventBus(history_size=5)
    q1 = bus.subscribe()
    q2 = bus.subscribe()
    bus.publish('scan', job_id=1, status='Running')
    e1 = q1.get_nowait()
    e2 = q2.get_nowait()
    assert e1.type == 'scan'
    assert e2.payload['job_id'] == 1
    bus.unsubscribe(q1)
    bus.unsubscribe(q2)


def test_event_bus_cross_thread_publish():
    bus = EventBus()
    q = bus.subscribe()
    errors = []

    def publisher():
        try:
            bus.publish('activity', kind='play')
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    thread = threading.Thread(target=publisher)
    thread.start()
    thread.join(timeout=2)
    assert not errors
    event = q.get(timeout=1)
    assert event.type == 'activity'
    assert event.payload['kind'] == 'play'
    bus.unsubscribe(q)


def test_encode_sse_bytes():
    bus = EventBus()
    event = bus.publish('download', request_id=9)
    raw = encode_sse(event)
    assert raw.startswith(b'event: download\n')
    assert b'request_id' in raw


def test_token_hash_stable():
    assert _hash_secret('abc') == _hash_secret('abc')
    assert _hash_secret('abc') != _hash_secret('xyz')
    assert TOKEN_PREFIX == 'gt_'
    assert 'read:library' in VALID_SCOPES


