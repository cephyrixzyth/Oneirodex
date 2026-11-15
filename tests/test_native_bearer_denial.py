"""Call real native read handlers with fake persistence; no app/server/DB."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from types import SimpleNamespace
import unittest
from unittest import mock

from starlette.requests import Request
from oneirodex.runtime_native.client_reads import create_client_reads_router
from oneirodex.runtime_native.collection_reads import create_collection_reads_router
from oneirodex.runtime_native.acquire_status import _login_redirect
from oneirodex.runtime_native.request_auth import request_auth_context


class NativeBearerDenialContracts(unittest.TestCase):
    def reply(self,path,*,secret='actual-secret',bearer=True,revoked=False,expired=False,active=True,unknown=False,scopes=('read:library',),method='GET'):
        user=SimpleNamespace(id=27,user_id='synthetic-account',role='user',state=active)
        token=SimpleNamespace(user_id=27,token_hash=hashlib.sha256(b'actual-secret').hexdigest(),
            revoked_at=datetime.now(timezone.utc) if revoked else None,
            expires_at=datetime.now(timezone.utc)-timedelta(days=1) if expired else None,
            last_used_at=None,has_scope=lambda scope:scope in scopes)
        touched=mock.Mock();data=mock.Mock();data.list.return_value={'collections':[]}
        manager=SimpleNamespace(login_view='/login',blueprint_login_views={},login_message=None)
        settings=SimpleNamespace(config={'SECRET_KEY':'pure-test-secret','TESTING':True})
        factory=create_collection_reads_router if path=='/api/collections' else create_client_reads_router
        router=factory(settings,find_user=lambda _id:user,find_token=lambda _prefix:None if unknown else token,
                       commit_token_touch=touched,login_manager=manager,data_access=data)
        route=next(route for route in router.routes if route.path==path)
        headers=[(b'authorization',('Bearer gt_abcd1234_'+secret).encode())] if bearer else []
        request=Request({'type':'http','method':method,'scheme':'http','path':path,'query_string':b'',
                         'headers':headers,'server':('fixture.invalid',80),'client':('127.0.0.1',1)})
        return route.endpoint(request),touched,data

    def test_wrong_revoked_expired_and_inactive_bearers_get_json401_without_login_redirect(self):
        for path in ('/api/client/identity','/api/collections'):
            for case in ({'secret':'wrong-secret'},{'revoked':True},{'expired':True},{'active':False},{'unknown':True}):
                with self.subTest(path=path,case=case):
                    response,touched,data=self.reply(path,**case)
                    self.assertEqual(response.status_code,401)
                    self.assertEqual(json.loads(response.body)['error_code'],'unauthorized')
                    self.assertEqual(response.headers['www-authenticate'],'Bearer')
                    self.assertNotIn('location',response.headers);self.assertNotIn('set-cookie',response.headers)
                    self.assertNotIn('wrong-secret',response.body.decode());touched.assert_not_called();data.list.assert_not_called()

    def test_anonymous_browser_keeps_login_redirect(self):
        for path in ('/api/client/identity','/api/collections'):
            response,touched,data=self.reply(path,bearer=False)
            self.assertEqual(response.status_code,302);self.assertTrue(response.headers['location'].startswith('/login?'))
            touched.assert_not_called();data.list.assert_not_called()

    def test_valid_scope_limited_bearer_stays403(self):
        for path in ('/api/client/identity','/api/collections'):
            response,touched,data=self.reply(path,scopes=('write:presence',))
            self.assertEqual(response.status_code,403)
            self.assertEqual(json.loads(response.body)['error_code'],'forbidden');touched.assert_called_once();data.list.assert_not_called()

    def test_valid_bearer_still_reads_actual_handlers(self):
        for path in ('/api/client/identity','/api/collections'):
            response,touched,_=self.reply(path)
            self.assertEqual(response.status_code,200);touched.assert_called_once()

    def test_head_denial_has_no_body_and_keeps_security_headers(self):
        response,touched,_=self.reply('/api/collections',secret='wrong-secret',method='HEAD')
        self.assertEqual(response.status_code,401);self.assertEqual(response.body,b'')
        self.assertEqual(response.headers['x-content-type-options'],'nosniff');touched.assert_not_called()

    def test_session_only_route_does_not_advertise_unsupported_bearer_authentication(self):
        request=Request({'type':'http','method':'GET','scheme':'http','path':'/api/tokens','query_string':b'',
            'headers':[(b'authorization',b'Bearer gt_abcd1234_synthetic')],
            'server':('fixture.invalid',80),'client':('127.0.0.1',1)})
        settings=SimpleNamespace(config={'SECRET_KEY':'pure-test-secret','TESTING':True})
        manager=SimpleNamespace(login_view='/login',blueprint_login_views={},login_message=None)
        find_token=mock.Mock(side_effect=AssertionError('session-only route must not resolve tokens'))
        context=request_auth_context(request,settings.config,find_user=lambda _id:None,
            find_token=find_token,commit_token_touch=mock.Mock(),login_manager=manager,allow_bearer=False)
        response=_login_redirect(settings,request,manager,context)
        self.assertEqual(response.status_code,302);self.assertNotIn('www-authenticate',response.headers)
        find_token.assert_not_called()

    def test_authenticated_role_refusal_is_not_reported_as_bad_bearer_credentials(self):
        request=Request({'type':'http','method':'GET','scheme':'http','path':'/api/restricted','query_string':b'',
            'headers':[(b'authorization',b'Bearer gt_abcd1234_synthetic')],
            'server':('fixture.invalid',80),'client':('127.0.0.1',1)})
        settings=SimpleNamespace(config={'SECRET_KEY':'pure-test-secret','TESTING':True})
        manager=SimpleNamespace(login_view='/login',blueprint_login_views={},login_message=None)
        context=SimpleNamespace(user=SimpleNamespace(id=27),session_data={},should_set_session_cookie=False)
        response=_login_redirect(settings,request,manager,context)
        self.assertEqual(response.status_code,302);self.assertNotIn('www-authenticate',response.headers)


if __name__=='__main__':unittest.main()
