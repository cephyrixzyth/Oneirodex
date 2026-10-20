"""Match Flask-WTF's early CSRF rejection for empty admin mutations."""
from __future__ import annotations

from .form_compat import first_form_value
from collections.abc import Mapping
from datetime import timedelta
from http.cookies import SimpleCookie
from tempfile import SpooledTemporaryFile
from urllib.parse import parse_qs


_UNSAFE_METHODS = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})
_URLENCODED_BODY_LIMIT = 1024 * 1024
_MULTIPART_BODY_DEFAULT_LIMIT = 128 * 1024 * 1024


def native_route_matches(native_app, scope: Mapping) -> bool:
    """Return whether FastAPI recognizes this exact path and method.

    Flask's CSRF middleware does not preempt requests that fail URL matching.
    The ASGI preflight must preserve that ordering for 404/405 responses.
    """
    from starlette.routing import Match

    router = getattr(native_app, 'router', None)
    if router is None:
        # Compatibility fixtures can replace ASGI initialization without a
        # native route table; preserve the established preflight behavior.
        return True
    for route in getattr(router, 'routes', ()):
        match, _child_scope = route.matches(scope)
        if match is Match.FULL:
            return True
    return False


async def inspect_urlencoded_csrf_body(scope: Mapping, receive, config: Mapping):
    """Read and replay a small URL-encoded body so CSRF precedes route auth.

    Large/unbounded bodies stay on their existing route parser. The returned
    receive callable replays every consumed ASGI message to the selected app.
    """
    headers = {key.lower(): value for key, value in scope.get('headers', ())}
    content_type = headers.get(b'content-type', b'').split(b';', 1)[0].strip().lower()
    if content_type != b'application/x-www-form-urlencoded':
        return None, receive, False
    raw_length = headers.get(b'content-length')
    if raw_length:
        try:
            if int(raw_length) > _URLENCODED_BODY_LIMIT:
                return None, receive, False
        except ValueError:
            return None, receive, False

    messages = []
    body = bytearray()
    while True:
        message = await receive()
        messages.append(message)
        if message.get('type') != 'http.request':
            return None, _replay_receive(messages, receive), False
        body.extend(message.get('body', b''))
        if len(body) > _URLENCODED_BODY_LIMIT:
            return None, _replay_receive(messages, receive), False
        if not message.get('more_body', False):
            break

    replay = _replay_receive(messages, receive)
    if len(body) > _URLENCODED_BODY_LIMIT:
        return None, replay, False
    field_name = str(config.get('WTF_CSRF_FIELD_NAME') or 'csrf_token')
    values = parse_qs(bytes(body).decode('utf-8', 'replace'), keep_blank_values=True)
    token = values.get(field_name, [''])
    return (token[0] or None), replay, True


async def inspect_multipart_csrf_body(scope: Mapping, receive, config: Mapping):
    """Read and replay a multipart body to recover its CSRF field.

    Starlette's parser spools uploaded files. The captured request is also
    spooled to disk beyond 1 MiB and bounded by the runtime body-size limit.
    """
    headers = {key.lower(): value for key, value in scope.get('headers', ())}
    content_type = headers.get(b'content-type', b'').split(b';', 1)[0].strip().lower()
    if content_type != b'multipart/form-data':
        return None, receive, False
    try:
        body_limit = int(config.get('MAX_CONTENT_LENGTH') or _MULTIPART_BODY_DEFAULT_LIMIT)
    except (TypeError, ValueError):
        body_limit = _MULTIPART_BODY_DEFAULT_LIMIT
    body_limit = max(0, body_limit)
    raw_length = headers.get(b'content-length')
    if raw_length:
        try:
            if int(raw_length) > body_limit:
                return None, receive, False
        except ValueError:
            return None, receive, False

    body_file = SpooledTemporaryFile(max_size=1024 * 1024, mode='w+b')
    messages = []
    received = 0
    from starlette.datastructures import Headers
    from starlette.formparsers import MultiPartException, MultiPartParser

    async def stream():
        nonlocal received
        while True:
            message = await receive()
            if message.get('type') != 'http.request':
                messages.append((dict(message), None, 0))
                return
            chunk = message.get('body', b'')
            received += len(chunk)
            offset = body_file.tell()
            body_file.write(chunk)
            replay_meta = {key: value for key, value in message.items() if key != 'body'}
            messages.append((replay_meta, offset, len(chunk)))
            if received > body_limit:
                raise MultiPartException('Request body exceeded the configured limit.')
            yield chunk
            if not message.get('more_body', False):
                return

    try:
        form = await MultiPartParser(
            Headers(scope=scope),
            stream(),
            max_files=int(config.get('MAX_FORM_PARTS') or 1000),
            max_fields=int(config.get('MAX_FORM_PARTS') or 1000),
            max_part_size=body_limit,
        ).parse()
    except (MultiPartException, ValueError):
        return None, _replay_spooled_receive(messages, body_file, receive), False
    field_name = str(config.get('WTF_CSRF_FIELD_NAME') or 'csrf_token')
    value = first_form_value(form, field_name)
    token = value if isinstance(value, str) else None
    for _, item in form.multi_items():
        close = getattr(item, 'close', None)
        if close is not None:
            await close()
    replay = _replay_spooled_receive(messages, body_file, receive)
    replay.close = body_file.close
    return token or None, replay, True


def _replay_receive(messages, receive):
    queue = list(messages)

    async def replay():
        if queue:
            return queue.pop(0)
        return await receive()

    return replay


def _replay_spooled_receive(messages, body_file, receive):
    queue = list(messages)

    async def replay():
        if queue:
            message, offset, size = queue.pop(0)
            if offset is not None:
                body_file.seek(offset)
                message['body'] = body_file.read(size)
            if not queue:
                body_file.close()
            return message
        body_file.close()
        return await receive()

    replay.close = body_file.close
    return replay


def empty_admin_mutation_csrf_error(
    scope: Mapping,
    config: Mapping,
    *,
    form_token: str | None = None,
    form_inspected: bool = False,
) -> str | None:
    """Return Flask-WTF's error for bodyless admin writes before route auth.

    Native route handlers keep validating populated forms and requests with a
    CSRF header. This preflight handles the bodyless case that otherwise
    reaches an auth redirect before CSRF validation.
    """
    if not config.get('WTF_CSRF_ENABLED', True):
        return None
    if str(scope.get('method') or '').upper() not in _UNSAFE_METHODS:
        return None
    path = str(scope.get('path') or '')
    if path != '/admin' and not path.startswith('/admin/'):
        return None
    # Werkzeug's <path:filename> converter rejects an empty filename before
    # CSRF runs. Let the native equivalent reach its route-miss response too.
    if (
        str(scope.get('method') or '').upper() == 'DELETE'
        and path == '/admin/api/theme/fonts/'
    ):
        return None

    headers = {key.lower(): value for key, value in scope.get('headers', ())}
    content_type = headers.get(b'content-type', b'').split(b';', 1)[0].strip().lower()
    content_length = headers.get(b'content-length')
    form_encoded = content_type in {
        b'application/x-www-form-urlencoded', b'multipart/form-data',
    }
    # Populated forms can carry csrf_token in their body, so route-level
    # validators retain ownership. JSON and other body types cannot satisfy
    # Flask-WTF's form-field lookup and require a valid CSRF header.
    if form_encoded and not form_inspected and (
        content_length not in (b'', b'0') or headers.get(b'transfer-encoding')
    ):
        return None

    header_token = (
        headers.get(b'x-csrftoken')
        or headers.get(b'x-csrf-token')
        or b''
    ).decode('utf-8', 'replace') or None
    token = form_token or header_token
    session_data = _session_from_cookie(headers, config)
    from oneirodex.runtime_native.session_compat import (
        CsrfTokenError,
        validate_csrf_token,
    )

    field_name = str(config.get('WTF_CSRF_FIELD_NAME') or 'csrf_token')
    lifetime = config.get('PERMANENT_SESSION_LIFETIME', 31 * 24 * 3600)
    if isinstance(lifetime, timedelta):
        lifetime = int(lifetime.total_seconds())
    time_limit = config.get('WTF_CSRF_TIME_LIMIT', 3600)
    try:
        validate_csrf_token(
            token,
            session_data,
            config.get('WTF_CSRF_SECRET_KEY') or config.get('SECRET_KEY'),
            field_name=field_name,
            time_limit=time_limit,
        )
    except CsrfTokenError as exc:
        return str(exc)
    return None


def _session_from_cookie(headers: Mapping[bytes, bytes], config: Mapping) -> dict:
    cookie_header = headers.get(b'cookie', b'').decode('latin-1', 'replace')
    cookies = SimpleCookie()
    try:
        cookies.load(cookie_header)
    except Exception:
        return {}
    name = str(config.get('SESSION_COOKIE_NAME') or 'session')
    morsel = cookies.get(name)
    if morsel is None:
        return {}

    from oneirodex.runtime_native.session_compat import load_session_cookie

    secret = config.get('SECRET_KEY')
    if not secret:
        return {}
    lifetime = config.get('PERMANENT_SESSION_LIFETIME', 31 * 24 * 3600)
    max_age = int(lifetime.total_seconds()) if isinstance(lifetime, timedelta) else int(lifetime)
    fallback = config.get('SECRET_KEY_FALLBACKS') or ()
    return load_session_cookie(
        morsel.value,
        secret,
        max_age=max_age,
        fallback_secret_keys=fallback,
    )


def admin_request_wants_json(scope: Mapping) -> bool:
    """Mirror the legacy HTTP-error format choice for admin requests."""
    if str(scope.get('path') or '').startswith('/api/'):
        return True
    headers = {key.lower(): value for key, value in scope.get('headers', ())}
    if headers.get(b'x-requested-with', b'').lower() == b'xmlhttprequest':
        return True
    accept = headers.get(b'accept', b'').decode('latin-1', 'replace')
    if not accept:
        return False
    from werkzeug.datastructures import MIMEAccept
    from werkzeug.http import parse_accept_header

    return parse_accept_header(accept, MIMEAccept).best == 'application/json'
