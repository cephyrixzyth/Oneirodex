"""Focused tests for current setup-page redirect feedback."""
import asyncio
from types import SimpleNamespace

import httpx
from fastapi import FastAPI
from flask import Flask

from oneirodex.runtime_native.setup_pages import create_setup_pages_router


def test_stale_setup_smtp_and_igdb_pages_keep_legacy_warning():
    flask_app = Flask(__name__)
    flask_app.secret_key = 'setup-pages-parity-test-secret'
    data = SimpleNamespace(
        required=lambda: False,
        in_progress=lambda: True,
        current_step=lambda: 5,
        redirect_url=lambda: '/setup/integrations',
        start=lambda: None,
    )
    router = create_setup_pages_router(
        flask_app,
        find_user=lambda *_args: None,
        find_token=lambda *_args: None,
        commit_token_touch=lambda *_args: None,
        data_access=data,
    )
    app = FastAPI()
    app.include_router(router)

    cases = (
        ('/setup/smtp', 'Please complete the admin account setup first.'),
        ('/setup/igdb', 'Please complete the previous setup steps first.'),
    )

    async def run_case(path):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url='http://testserver',
            follow_redirects=False,
        ) as client:
            return await client.get(path)

    for path, warning in cases:
        response = asyncio.run(run_case(path))
        assert response.status_code == 302
        assert response.headers['location'] == '/setup/integrations'
        session_cookie = response.cookies.get('session')
        assert session_cookie
        session = flask_app.session_interface.get_signing_serializer(flask_app).loads(
            session_cookie,
        )
        assert session['_flashes'] == [('warning', warning)]
