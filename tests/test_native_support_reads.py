from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from flask import Flask

from oneirodex.runtime_native.session_compat import dump_session_cookie
from oneirodex.runtime_native.support_reads import create_support_reads_router


class FakeSupportData:
    def __init__(self):
        self.rows = [
            SimpleNamespace(
                id=5, user_id=7, title='Mine',
                to_dict=lambda compact=False: {'id': 5, 'title': 'Mine', 'compact': compact},
            ),
            SimpleNamespace(
                id=6, user_id=9, title='Other',
                to_dict=lambda compact=False: {'id': 6, 'title': 'Other', 'compact': compact},
            ),
        ]
        self.admin_flags = []

    def list_tickets(self, user, *, admin):
        self.admin_flags.append(admin)
        return self.rows if admin else [row for row in self.rows if row.user_id == user.id]

    def ticket(self, ticket_id):
        return next((row for row in self.rows if row.id == ticket_id), None)


@pytest.fixture
def harness():
    app = Flask('native-support-reads')
    app.config.update(SECRET_KEY='support-reads-secret', SESSION_PROTECTION='none')
    users = {
        7: SimpleNamespace(id=7, role='user', state=True, is_active=True),
        8: SimpleNamespace(id=8, role='admin', state=True, is_active=True),
    }
    data = FakeSupportData()
    runtime = FastAPI()
    runtime.include_router(create_support_reads_router(
        app, find_user=users.get, find_token=lambda _prefix: None,
        commit_token_touch=lambda _token: None,
        load_user_id=lambda value: users.get(int(value)) if value.isdigit() else None,
        data_access=data,
    ))
    return runtime, data


def _cookie(user_id):
    return dump_session_cookie({'_user_id': str(user_id), '_fresh': True}, 'support-reads-secret')


def _request(runtime, method, path, *, user_id=7):
    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver',
        ) as client:
            return await client.request(method, path, headers={'Cookie': f'session={_cookie(user_id)}'})
    return asyncio.run(send())


def test_member_list_is_owner_scoped_and_retains_bare_payload(harness):
    runtime, data = harness

    response = _request(runtime, 'GET', '/api/support/tickets')

    assert response.status_code == 200
    assert response.json() == {'tickets': [{'id': 5, 'title': 'Mine', 'compact': True}], 'empty': False}
    assert data.admin_flags == [False]


def test_detail_allows_owner_and_admin_but_denies_other_members(harness):
    runtime, _data = harness

    owner = _request(runtime, 'GET', '/api/support/tickets/5', user_id=7)
    denied = _request(runtime, 'GET', '/api/support/tickets/6', user_id=7)
    admin = _request(runtime, 'GET', '/api/support/tickets/6', user_id=8)

    assert owner.status_code == 200 and owner.json()['ticket']['id'] == 5
    assert denied.status_code == 403 and denied.json()['error_code'] == 'forbidden'
    assert admin.status_code == 200 and admin.json()['ticket']['id'] == 6


def test_missing_ticket_uses_not_found_contract(harness):
    runtime, _data = harness

    response = _request(runtime, 'GET', '/api/support/tickets/99')

    assert response.status_code == 404
    assert response.json()['error_code'] == 'not_found'
