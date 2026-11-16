import asyncio

from starlette.requests import Request

from oneirodex.runtime_native.admin_art_studio_actions import _json_object
from oneirodex.runtime_native.bounded_request_body import BODY_TOO_LARGE


def _request(chunks):
    chunks = list(chunks)
    index = 0

    async def receive():
        nonlocal index
        if index >= len(chunks):
            return {'type': 'http.request', 'body': b'', 'more_body': False}
        body = chunks[index]
        index += 1
        return {'type': 'http.request', 'body': body, 'more_body': index < len(chunks)}

    return Request({
        'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
        'method': 'POST', 'scheme': 'http', 'path': '/admin/api/art-studio/generate',
        'raw_path': b'/admin/api/art-studio/generate', 'query_string': b'',
        'headers': [(b'content-type', b'application/json')],
        'client': ('127.0.0.1', 1234), 'server': ('testserver', 80),
    }, receive=receive)


def test_admin_art_studio_json_reader_caps_chunked_body():
    request = _request([b' ' * (64 * 1024), b' '])

    result = asyncio.run(_json_object(request))

    assert result is BODY_TOO_LARGE
