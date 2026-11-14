"""Bound native admin discovery shelf JSON before model/helper traversal."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import Mock

from starlette.requests import Request
from starlette.responses import Response

from oneirodex.runtime_native.admin_discovery_sections import (
    _SHELF_GAME_UUIDS_MAX_ITEMS,
    _SHELF_JSON_BODY_MAX_BYTES,
    _dispatch_action,
    _shelf_model_body,
)
from oneirodex.schemas.admin_system import DiscoveryShelfBody
from oneirodex.utils.discovery_shelves import normalize_manual_uuids


def _request(body: bytes, *, headers=None, chunks=None, method='POST', path='/'):
    chunks = list(chunks) if chunks is not None else [body]
    index = 0

    async def receive():
        nonlocal index
        if index >= len(chunks):
            return {'type': 'http.request', 'body': b'', 'more_body': False}
        chunk = chunks[index]
        index += 1
        return {'type': 'http.request', 'body': chunk, 'more_body': index < len(chunks)}

    raw_headers = [(b'content-type', b'application/json')]
    raw_headers.extend((key.lower().encode(), value.encode()) for key, value in (headers or {}).items())
    return Request({
        'type': 'http', 'http_version': '1.1', 'method': method,
        'scheme': 'http', 'path': path, 'raw_path': path.encode(), 'query_string': b'',
        'headers': raw_headers, 'client': ('test', 1), 'server': ('test', 80),
    }, receive)


def test_shelf_body_rejects_declared_oversize_before_reading():
    request = _request(b'', headers={'content-length': str(_SHELF_JSON_BODY_MAX_BYTES + 1)})

    result = asyncio.run(_shelf_model_body(request, DiscoveryShelfBody))

    assert isinstance(result, Response)
    assert result.status_code == 413
    assert json.loads(result.body)['error_code'] == 'payload_too_large'


def test_shelf_body_rejects_chunked_oversize():
    body = b' ' * (_SHELF_JSON_BODY_MAX_BYTES + 1)
    request = _request(body, chunks=[body[:1024], body[1024:]])

    result = asyncio.run(_shelf_model_body(request, DiscoveryShelfBody))

    assert isinstance(result, Response)
    assert result.status_code == 413


def test_shelf_body_caps_uuid_array_before_model_validation():
    payload = {'name': 'Duplicates', 'mode': 'manual', 'game_uuids': ['same'] * (_SHELF_GAME_UUIDS_MAX_ITEMS + 1)}
    request = _request(json.dumps(payload).encode())

    result = asyncio.run(_shelf_model_body(request, DiscoveryShelfBody))

    assert isinstance(result, Response)
    assert result.status_code == 413
    assert json.loads(result.body)['error_code'] == 'payload_too_large'


def test_shelf_post_and_put_reject_duplicate_heavy_arrays_before_data_access():
    payload = {'name': 'Duplicates', 'mode': 'manual', 'game_uuids': ['same'] * (_SHELF_GAME_UUIDS_MAX_ITEMS + 1)}
    data = Mock()
    user = SimpleNamespace(id=9)
    cases = (
        ('POST', '/admin/api/discovery_sections', None, 'create'),
        ('PUT', '/admin/api/discovery_sections/2', 2, 'update'),
    )

    for method, path, section_id, action in cases:
        request = _request(
            json.dumps(payload).encode(), method=method, path=path,
        )
        result = asyncio.run(_dispatch_action(request, data, user, section_id))
        assert result.status_code == 413
        getattr(data, action).assert_not_called()


def test_all_other_discovery_mutations_reject_oversized_bodies_before_data_access():
    data = Mock()
    user = SimpleNamespace(id=9)
    body = b' ' * (_SHELF_JSON_BODY_MAX_BYTES + 1)
    cases = (
        ('PUT', '/admin/api/discovery_sections/2/schedule', 2),
        ('PUT', '/admin/api/discovery_sections/2/pin', 2),
        ('POST', '/admin/api/discovery_sections/order', None),
        ('POST', '/admin/api/discovery_sections/visibility', None),
    )

    for method, path, section_id in cases:
        request = _request(body, method=method, path=path)
        result = asyncio.run(_dispatch_action(request, data, user, section_id))
        assert result.status_code == 413

    data.schedule.assert_not_called()
    data.pin.assert_not_called()
    data.reorder.assert_not_called()
    data.visibility.assert_not_called()


def test_shelf_body_keeps_valid_unique_ids_and_duplicate_cleanup():
    uuids = [f'game-{index}' for index in range(60)]
    payload = {
        'name': 'Curated games', 'mode': 'manual',
        'game_uuids': uuids + [uuids[0]] * 100,
    }
    request = _request(json.dumps(payload).encode())

    result = asyncio.run(_shelf_model_body(request, DiscoveryShelfBody))

    assert isinstance(result, DiscoveryShelfBody)
    assert normalize_manual_uuids(result.game_uuids) == uuids
