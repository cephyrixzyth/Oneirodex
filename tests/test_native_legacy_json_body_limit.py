from __future__ import annotations

import pytest
from starlette.requests import Request

from oneirodex.runtime_native.legacy_json_compat import (
    MAX_LEGACY_JSON_BODY_BYTES,
    LegacyJSONError,
    parse_legacy_json,
)


@pytest.mark.anyio
async def test_legacy_json_parser_rejects_oversized_chunked_body():
    parts = iter((
        {
            'type': 'http.request',
            'body': b' ' * (MAX_LEGACY_JSON_BODY_BYTES // 2 + 1),
            'more_body': True,
        },
        {
            'type': 'http.request',
            'body': b' ' * (MAX_LEGACY_JSON_BODY_BYTES // 2),
            'more_body': False,
        },
    ))

    async def receive():
        return next(parts)

    request = Request({
        'type': 'http',
        'method': 'POST',
        'path': '/admin/igdb_settings',
        'headers': [(b'content-type', b'application/json')],
        'query_string': b'',
    }, receive=receive)

    with pytest.raises(LegacyJSONError) as error:
        await parse_legacy_json(request)

    assert error.value.status_code == 413
