"""A test client for the app production actually serves (``asgi.LazyASGIApp``).

It keeps the small call surface the suite already uses (``get``/``post``/...,
``get_json()``, ``.data``, ``session_transaction()``) so existing tests can move
off the retired Flask routes without being rewritten. Requests run against the
real native runtime, which is given the test's own database connection: rows a
test writes are visible to the request, and everything still rolls back with
the test's transaction.
"""
from __future__ import annotations

import asyncio
import json as jsonlib
from contextlib import contextmanager
from typing import Any
from urllib.parse import urlencode

import httpx


def _seconds(value) -> int:
    if hasattr(value, 'total_seconds'):
        return int(value.total_seconds())
    return int(value or 31_536_000)


class _Headers:
    """httpx headers with the Werkzeug spellings tests already use."""

    def __init__(self, headers):
        self._headers = headers

    def getlist(self, name):
        return self._headers.get_list(name)

    def get_all(self, name):
        return self._headers.get_list(name)

    def __getattr__(self, name):
        return getattr(self._headers, name)

    def __getitem__(self, name):
        return self._headers[name]

    def __contains__(self, name):
        return name in self._headers

    def __iter__(self):
        return iter(self._headers)

    def items(self):
        return self._headers.items()


class NativeResponse:
    def __init__(self, response: httpx.Response):
        self._response = response
        self.status_code = response.status_code
        self.headers = _Headers(response.headers)
        self.data = response.content

    def close(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def location(self) -> str | None:
        return self.headers.get('location')

    @property
    def content_type(self) -> str:
        return self.headers.get('content-type', '')

    @property
    def mimetype(self) -> str:
        return self.content_type.split(';', 1)[0].strip()

    @property
    def text(self) -> str:
        return self._response.text

    @property
    def json(self) -> Any:
        return self.get_json()

    def get_data(self, as_text: bool = False):
        return self._response.text if as_text else self.data

    def get_json(self, silent: bool = False):
        try:
            return jsonlib.loads(self.data or b'null')
        except ValueError:
            if silent:
                return None
            raise


class NativeTestClient:
    """Drives the real ASGI app over an in-process transport."""

    def __init__(self, asgi_app, config, source_config=None, db_session=None, application=None):
        from oneirodex.runtime_native.session_compat import dump_session_cookie, load_session_cookie

        self._app = asgi_app
        self._config = config
        self._dump = dump_session_cookie
        self._load = load_session_cookie
        self.cookies: dict[str, str] = {}
        # Tests adjust settings on the fixture app's config; mirror them into
        # the runtime config before each request so both stay in step.
        self._source_config = source_config
        self._db_session = db_session
        # Tests read settings and push contexts through ``client.application``.
        self.application = application

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    # -- session ---------------------------------------------------------
    @property
    def _cookie_name(self) -> str:
        return self._config.get('SESSION_COOKIE_NAME') or 'session'

    @contextmanager
    def session_transaction(self):
        session = self._load(
            self.cookies.get(self._cookie_name), self._config['SECRET_KEY'],
            max_age=_seconds(self._config.get('PERMANENT_SESSION_LIFETIME')),
        )
        yield session
        self._upgrade_bare_identity(session)
        self.cookies[self._cookie_name] = self._dump(session, self._config['SECRET_KEY'])

    def _upgrade_bare_identity(self, session):
        """Turn ``_user_id = "<id>"`` into the identity a real sign-in issues.

        The served app accepts only server-side login identities; a bare user
        id is a retired cookie shape and is refused. Tests that log in by id
        get exactly what signing in would have produced.
        """
        identity = str(session.get('_user_id') or '')
        if not identity.isdigit() or self._db_session is None:
            return
        from oneirodex.models import User
        from oneirodex.utils.persistent_sessions import issue_login_identity

        user = self._db_session.get(User, int(identity))
        if user is None:
            return
        session['_user_id'] = issue_login_identity(user)
        session.setdefault('_fresh', True)

    def set_cookie(self, key, value='', *args, **kwargs):
        # Accept both Werkzeug 2 (server_name, key, value) and 3 (key, value) orders.
        if args and isinstance(value, str) and kwargs.get('domain') is None and len(args) == 1:
            key, value = value, args[0]
        self.cookies[key] = value

    def delete_cookie(self, key, *args, **kwargs):
        self.cookies.pop(key, None)

    # -- requests --------------------------------------------------------
    def open(self, path, method='GET', *, json=None, data=None, headers=None, query_string=None,
             content_type=None, follow_redirects=False, environ_base=None, **_ignored):
        headers = dict(headers or {})
        if self._source_config is not None:
            for key, value in self._source_config.items():
                if key != 'SQLALCHEMY_DATABASE_URI':
                    self._config[key] = value
        if environ_base and environ_base.get('REMOTE_ADDR'):
            headers.setdefault('X-Test-Remote-Addr', environ_base['REMOTE_ADDR'])
        if query_string:
            sep = '&' if '?' in path else '?'
            path += sep + (query_string if isinstance(query_string, str) else urlencode(query_string, doseq=True))
        kwargs: dict[str, Any] = {}
        if json is not None:
            kwargs['json'] = json
        elif isinstance(data, dict):
            files = {k: v for k, v in data.items() if isinstance(v, tuple)}
            fields = {k: v for k, v in data.items() if not isinstance(v, tuple)}
            if files:
                kwargs['files'] = {
                    k: ((v[1] if len(v) > 1 else k), v[0].read() if hasattr(v[0], 'read') else v[0])
                    for k, v in files.items()
                }
                kwargs['data'] = fields
            else:
                kwargs['data'] = fields
        elif data is not None:
            kwargs['content'] = data
            if content_type:
                headers.setdefault('Content-Type', content_type)
        if content_type and 'json' in content_type and json is None and isinstance(data, (str, bytes)):
            headers['Content-Type'] = content_type

        if self.cookies:
            headers['Cookie'] = '; '.join(f'{k}={v}' for k, v in self.cookies.items())

        async def perform():
            transport = httpx.ASGITransport(app=self._app, client=('127.0.0.1', 50000))
            async with httpx.AsyncClient(transport=transport, base_url='http://localhost') as client:
                return await client.request(method, path, headers=headers,
                                            follow_redirects=False, **kwargs)

        response = asyncio.run(perform())
        self._store_cookies(response)
        if self._db_session is not None:
            # What a finished request committed is committed for the test too,
            # and objects the test already loaded are re-read, as they would be
            # by any other caller of the database.
            self._db_session.commit()
        if follow_redirects and response.status_code in (301, 302, 303, 307, 308):
            target = response.headers.get('location', '')
            if target.startswith('http://localhost'):
                target = target[len('http://localhost'):]
            keep = response.status_code in (307, 308)
            return self.open(target, method if keep else 'GET', headers={k: v for k, v in (headers or {}).items() if k != 'Cookie'},
                             follow_redirects=True, **({'json': json} if keep and json is not None else {}))
        return NativeResponse(response)

    def _store_cookies(self, response):
        from http.cookies import SimpleCookie

        for header in response.headers.get_list('set-cookie'):
            jar = SimpleCookie()
            jar.load(header)
            for name, morsel in jar.items():
                expired = morsel['max-age'] == '0' or (morsel['expires'] and 'Thu, 01 Jan 1970' in morsel['expires'])
                if expired or morsel.value == '':
                    self.cookies.pop(name, None)
                else:
                    self.cookies[name] = morsel.value

    def get(self, path, **kwargs):
        return self.open(path, 'GET', **kwargs)

    def post(self, path, **kwargs):
        return self.open(path, 'POST', **kwargs)

    def put(self, path, **kwargs):
        return self.open(path, 'PUT', **kwargs)

    def patch(self, path, **kwargs):
        return self.open(path, 'PATCH', **kwargs)

    def delete(self, path, **kwargs):
        return self.open(path, 'DELETE', **kwargs)

    def head(self, path, **kwargs):
        return self.open(path, 'HEAD', **kwargs)

    def options(self, path, **kwargs):
        return self.open(path, 'OPTIONS', **kwargs)


_SHARED_APP = None


def build_native_client(app, db_session):
    """Return a client for the real app, bound to this test's connection.

    The app is built once per test run (its routers and configuration are the
    expensive part); each test hands it its own connection and gets a fresh
    copy of the runtime settings.
    """
    global _SHARED_APP
    from asgi import LazyASGIApp

    connection = db_session.connection()
    if _SHARED_APP is None:
        asgi_app = LazyASGIApp()
        asgi_app._native_sqlalchemy_engine = connection
        asyncio.run(asgi_app._ensure_flask())
        _SHARED_APP = (asgi_app, dict(asgi_app._flask_app.config))
    asgi_app, pristine = _SHARED_APP
    # Never let a request write test data into the repository's library folder.
    import tempfile
    from pathlib import Path

    scratch = Path(tempfile.mkdtemp(prefix='od-native-client-'))
    for key in ('EMULATOR_SAVES_PATH',):
        if not app.config.get(key) or 'static' in str(app.config.get(key)):
            app.config[key] = str(scratch / key.lower())
    asgi_app._native_sqlalchemy_engine = connection
    runtime = asgi_app._flask_app
    if hasattr(runtime, 'native_engine'):
        runtime.native_engine = connection
    runtime.config.clear()
    runtime.config.update(pristine)
    return NativeTestClient(asgi_app, runtime.config, source_config=app.config, db_session=db_session, application=app)
