"""Pure ASGI CORS contracts: no server, configuration, database or keyring."""
import ast
import asyncio
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
MODULE=ROOT/'oneirodex/runtime_native/companion_cors.py'


class CompanionCORSContracts(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE.is_file(),'native webviews need a bounded CORS policy')
        spec=importlib.util.spec_from_file_location('companion_cors_contract',MODULE)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        self.decorate=module.native_companion_cors

    def exchange(self,origin='tauri://localhost',method='GET',extra=(),status=200,scope_type='http'):
        events=[];calls=[]
        async def handler(instance,scope,receive,send):
            calls.append(scope)
            if scope_type!='http':return
            await send({'type':'http.response.start','status':status,
                        'headers':[(b'vary',b'Cookie'),(b'cache-control',b'private, no-store')]})
            await send({'type':'http.response.body','body':b'first','more_body':True})
            await send({'type':'http.response.body','body':b'last','more_body':False})
        scope={'type':scope_type,'method':method,'path':'/api/collections',
               'headers':([] if origin is None else [(b'origin',origin.encode())])+list(extra)}
        async def receive():return {'type':'http.request','body':b''}
        async def send(event):events.append(event)
        asyncio.run(self.decorate(handler)(object(),scope,receive,send))
        headers=dict(events[0]['headers']) if events else {}
        return events,calls,headers

    def test_native_origins_allow_bearer_preflight_without_routing_or_cookie_credentials(self):
        for origin in ('tauri://localhost','http://tauri.localhost','https://tauri.localhost'):
            with self.subTest(origin=origin):
                events,calls,headers=self.exchange(origin,method='OPTIONS',extra=(
                    (b'access-control-request-method',b'POST'),
                    (b'access-control-request-headers',b'authorization,content-type')))
                self.assertEqual(events[0]['status'],200);self.assertEqual(calls,[])
                self.assertEqual(headers[b'access-control-allow-origin'],origin.encode())
                self.assertNotIn(b'access-control-allow-credentials',headers)

    def test_external_null_lookalike_and_port_origins_are_not_allowed(self):
        for origin in ('https://example.test','null','tauri://localhost.evil.test','http://tauri.localhost:3000'):
            with self.subTest(origin=origin):
                events,calls,headers=self.exchange(origin,method='OPTIONS',extra=((b'access-control-request-method',b'GET'),))
                self.assertEqual(events[0]['status'],400);self.assertEqual(calls,[])
                self.assertNotIn(b'access-control-allow-origin',headers)

    def test_unapproved_header_and_method_fail_preflight(self):
        for method,header in (('TRACE','authorization'),('POST','x-csrftoken'),('GET','x-operator-secret')):
            events,calls,_=self.exchange(method='OPTIONS',extra=(
                (b'access-control-request-method',method.encode()),(b'access-control-request-headers',header.encode())))
            self.assertEqual(events[0]['status'],400);self.assertEqual(calls,[])

    def test_actual_success_denials_and_errors_keep_auth_status_private_cache_and_stream(self):
        for status in (200,401,403,404,500):
            with self.subTest(status=status):
                events,calls,headers=self.exchange(status=status,extra=((b'authorization',b'Bearer synthetic'),))
                self.assertEqual(events[0]['status'],status);self.assertEqual(len(calls),1)
                self.assertEqual(headers[b'access-control-allow-origin'],b'tauri://localhost')
                self.assertNotIn(b'access-control-allow-credentials',headers)
                self.assertEqual(headers[b'cache-control'],b'private, no-store')
                self.assertEqual(set(headers[b'vary'].decode().split(', ')),{'Cookie','Origin'})
                self.assertEqual([event['body'] for event in events[1:]],[b'first',b'last'])

    def test_no_origin_and_unapproved_actual_origin_get_no_access_header(self):
        for origin in (None,'https://example.test'):
            events,calls,headers=self.exchange(origin)
            self.assertEqual(len(calls),1);self.assertEqual(events[0]['status'],200)
            self.assertNotIn(b'access-control-allow-origin',headers)

    def test_lifespan_and_websocket_pass_through(self):
        for kind in ('lifespan','websocket'):
            events,calls,_=self.exchange(scope_type=kind)
            self.assertEqual(events,[]);self.assertEqual(len(calls),1)

    def test_outer_runtime_entry_is_decorated_without_replacing_lazy_app_identity(self):
        tree=ast.parse((ROOT/'asgi.py').read_text(encoding='utf-8'))
        cls=next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=='LazyASGIApp')
        entry=next(node for node in cls.body if isinstance(node,ast.AsyncFunctionDef) and node.name=='__call__')
        self.assertTrue(any(isinstance(node,ast.Name) and node.id=='native_companion_cors' for node in entry.decorator_list))
        assignment=next(node for node in tree.body if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='asgi_app' for t in node.targets))
        self.assertEqual(ast.unparse(assignment.value),'LazyASGIApp()')


if __name__=='__main__':unittest.main()
