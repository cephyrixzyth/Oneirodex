"""Match Flask-WTF's early CSRF rejection for empty admin mutations."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from http.cookies import SimpleCookie
from urllib.parse import parse_qs


_UNSAFE_METHODS = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})
_URLENCODED_BODY_LIMIT = 64 * 1024
_MULTIPART_BODY_LIMIT = 64 * 1024


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
    """Read and replay a small multipart body to recover its CSRF field.

    Use Starlette's multipart parser and a strict body ceiling. Oversized or
    malformed bodies remain the selected route's responsibility.
    """
    headers = {key.lower(): value for key, value in scope.get('headers', ())}
    content_type = headers.get(b'content-type', b'').split(b';', 1)[0].strip().lower()
    if content_type != b'multipart/form-data':
        return None, receive, False
    raw_length = headers.get(b'content-length')
    if raw_length:
        try:
            if int(raw_length) > _MULTIPART_BODY_LIMIT:
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
        if len(body) > _MULTIPART_BODY_LIMIT:
            return None, _replay_receive(messages, receive), False
        if not message.get('more_body', False):
            break

    replay = _replay_receive(messages, receive)
    from starlette.datastructures import Headers
    from starlette.formparsers import MultiPartException, MultiPartParser

    async def stream():
        yield bytes(body)

    try:
        form = await MultiPartParser(
            Headers(scope=scope),
            stream(),
            max_files=16,
            max_fields=128,
            max_part_size=_MULTIPART_BODY_LIMIT,
        ).parse()
    except (MultiPartException, ValueError):
        return None, replay, False
    field_name = str(config.get('WTF_CSRF_FIELD_NAME') or 'csrf_token')
    value = form.get(field_name)
    token = value if isinstance(value, str) else None
    for _, item in form.multi_items():
        close = getattr(item, 'close', None)
        if close is not None:
            await close()
    return token or None, replay, True


def _replay_receive(messages, receive):
    queue = list(messages)

    async def replay():
        if queue:
            return queue.pop(0)
        return await receive()

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
