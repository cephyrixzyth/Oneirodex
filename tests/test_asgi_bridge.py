"""The process entry point stays native ASGI and serves liveness without Flask."""

import asyncio

import asgi as asgi_module

BASE_SCOPE = {
    "type": "http",
    "http_version": "1.1",
    "method": "GET",
    "scheme": "http",
    "path": "/",
    "raw_path": b"/",
    "query_string": b"",
    "root_path": "",
    "headers": [(b"host", b"testserver")],
    "client": ("127.0.0.1", 54321),
    "server": ("testserver", 80),
}


def _drive(app, receive_messages, *, path='/pulse', method='GET'):
    """Run one ASGI request to completion, returning what it sent."""
    sent = []
    queued = list(receive_messages)

    async def receive():
        if queued:
            return queued.pop(0)
        # A real server holds the connection open rather than ending the
        # stream, so an app that keeps polling must not spin on a sentinel.
        await asyncio.sleep(0.05)
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    scope = dict(BASE_SCOPE, path=path, raw_path=path.encode('ascii'), method=method)
    asyncio.run(asyncio.wait_for(app(scope, receive, send), timeout=10))
    return sent


def test_process_entrypoint_is_lazy_native_asgi():
    assert isinstance(asgi_module.asgi_app, asgi_module.LazyASGIApp)


def test_liveness_does_not_initialize_the_legacy_app():
    app = asgi_module.LazyASGIApp()

    async def legacy_app_is_retired():
        raise AssertionError('liveness must not initialize Flask')

    app._ensure_flask = legacy_app_is_retired
    sent = _drive(app, [{"type": "http.request", "body": b""}])
    start = [m for m in sent if m["type"] == "http.response.start"]
    assert start and start[0]["status"] == 200
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    assert b'"status":"ok"' in body
