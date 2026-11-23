"""Invoke route functions with fake auth/storage; no ASGI app/server/DB is started."""
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from starlette.requests import Request
from oneirodex.runtime_native.room_games import create_room_games_router
from oneirodex.runtime_native.room_game_store import RoomProgressConflict
from oneirodex.runtime_native.session_compat import generate_csrf_token


class Data:
    def __init__(self): self.reads = []; self.writes = []; self.conflict = False
    def read(self, user, game):
        self.reads.append((user.id, game))
        return {'game_id': game, 'revision': 0, 'state': None, 'updated_at': None}
    def write(self, user, game, revision, state):
        self.writes.append((user.id, game, revision, state))
        if self.conflict: raise RoomProgressConflict()
        return {'game_id': game, 'revision': revision + 1, 'state': state, 'updated_at': None}


class RoomGameRouterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.data = Data()
        self.config = {'SECRET_KEY': 'synthetic-room-schema-secret', 'CSP_ENABLED': False}
        self.session = {}
        self.csrf = generate_csrf_token(self.session, self.config['SECRET_KEY'])
        self.auth = SimpleNamespace(user=SimpleNamespace(id=41), token=None, session_data=self.session,
                                    should_set_session_cookie=False, has_scope=lambda scope: True)
        router = create_room_games_router(SimpleNamespace(config=self.config), find_user=lambda _: None,
            find_token=lambda _: None, commit_token_touch=lambda _: None, data_access=self.data)
        self.endpoint = router.routes[0].endpoint

    async def call(self, method='GET', payload=None, *, csrf=True, game='moonfall-pinball', raw=None):
        content = raw if raw is not None else json.dumps(payload).encode() if payload is not None else b''
        headers = [(b'content-type', b'application/json')]
        if csrf: headers.append((b'x-csrftoken', self.csrf.encode()))
        sent = False
        async def receive():
            nonlocal sent
            body = content if not sent else b''
            sent = True
            return {'type': 'http.request', 'body': body, 'more_body': False}
        request = Request({'type': 'http', 'method': method, 'path': f'/api/room-games/{game}/progress',
                           'headers': headers, 'query_string': b'', 'scheme': 'http',
                           'server': ('testserver', 80), 'client': ('127.0.0.1', 123)}, receive)
        with patch('oneirodex.runtime_native.room_games.request_auth_context', return_value=self.auth):
            return await self.endpoint(request, game)

    def save(self):
        state = json.loads((Path(__file__).resolve().parents[1] / 'fixtures' / 'moonfall-save-v1.json').read_text())
        return {'revision': 0, 'state': state}

    async def test_unauthenticated_read_and_write_are_json_denials_without_storage(self):
        self.auth.user = None
        for method in ('GET', 'PUT', 'DELETE'):
            response = await self.call(method, self.save())
            self.assertEqual(response.status_code, 401)
            self.assertEqual(json.loads(response.body)['error_code'], 'unauthorized')
        self.assertEqual(self.data.reads, [])
        self.assertEqual(self.data.writes, [])

    async def test_read_is_member_scoped_and_not_cacheable(self):
        response = await self.call()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.data.reads, [(41, 'moonfall-pinball')])
        self.assertIn('no-store', response.headers['cache-control'])
        self.assertIn('Cookie', response.headers['vary'])

    async def test_session_mutation_requires_real_signed_csrf(self):
        denied = await self.call('PUT', self.save(), csrf=False)
        self.assertEqual(denied.status_code, 400)
        self.assertEqual(self.data.writes, [])
        allowed = await self.call('PUT', self.save())
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(self.data.writes[0][:3], (41, 'moonfall-pinball', 0))

    async def test_bearer_scopes_are_enforced_for_reads_and_mutations(self):
        self.auth.token = object()
        self.auth.has_scope = lambda scope: False
        for method in ('GET', 'PUT', 'DELETE'):
            self.assertEqual((await self.call(method, self.save())).status_code, 403)
        self.assertEqual(self.data.writes, [])
        self.assertEqual(self.data.reads, [])

    async def test_unsupported_game_invalid_save_and_overflow_do_not_reach_storage(self):
        self.assertEqual((await self.call(game='unknown')).status_code, 404)
        malformed = self.save()
        malformed['state']['score'] = float('nan')
        response = await self.call('PUT', malformed)
        self.assertEqual(response.status_code, 422)
        self.assertNotIn(b'NaN', response.body)
        self.assertEqual((await self.call('PUT', raw=b'{' + b' ' * 65536)).status_code, 413)
        self.assertEqual(self.data.writes, [])

    async def test_conflict_and_delete_have_explicit_revision_semantics(self):
        self.data.conflict = True
        response = await self.call('PUT', self.save())
        self.assertEqual(response.status_code, 409)
        self.data.conflict = False
        response = await self.call('DELETE', {'revision': 7})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.data.writes[-1], (41, 'moonfall-pinball', 7, None))


if __name__ == '__main__': unittest.main()
