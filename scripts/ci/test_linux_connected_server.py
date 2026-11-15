"""Pure/fake backend fixture safety; never connect to a database locally."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace

from probe_linux_packaged import ProbeFailure
spec=importlib.util.find_spec('linux_connected_server')
server=__import__('linux_connected_server') if spec else None


class FakeAPI:
    def __init__(self,fail=None,collision=False,cleanup_fail=False):
        self.fail,self.collision,self.cleanup_fail=fail,collision,cleanup_fail
        self.events=[];self.created=False
    def event(self,name):
        self.events.append(name)
        if name==self.fail:raise ProbeFailure('synthetic_'+name)
    def exists(self,name):self.event('exists');return self.collision or self.created
    def create(self,name,marker):self.event('create');self.created=True
    def start(self,name):self.event('start')
    def ready(self):self.event('ready')
    def seed(self,name):self.event('seed');return {'tokens':{'PRIVATE':'PRIVATE'}}
    def stop(self):
        self.event('stop')
        if self.cleanup_fail:raise ProbeFailure('synthetic_stop_failure')
    def owned(self,name,marker):self.event('owned');return self.created
    def drop(self,name,marker):self.event('drop');self.created=False


class ConnectedServerContracts(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(server,'real connected backend needs ownership guards before execution')

    def test_control_url_must_be_loopback_test_database_not_a_test_marker_elsewhere(self):
        self.assertEqual(server.validate_control_url('postgresql://fixture:synthetic@127.0.0.1:5432/control_test').hostname,'127.0.0.1')
        for value in ['postgresql://test:test@127.0.0.1/oneirodex','postgresql://x:x@remote.example/control_test',
                      'postgresql://x:x@127.0.0.1/control_test?host=remote.example','sqlite:///test',
                      'postgresql://x:x@127.0.0.1/control_test#private']:
            with self.assertRaises(ProbeFailure):server.validate_control_url(value)

    def test_real_ci_fence_precedes_dotenv_metadata_and_all_native_calls(self):
        with mock.patch.object(server.Path,'exists',side_effect=AssertionError('no local dotenv check')):
            with self.assertRaises(ProbeFailure):server.require_backend_ci(Path('PRIVATE'),{},'win32',1001)
        env={'GITHUB_ACTIONS':'true','RUNNER_OS':'Linux','GITHUB_REPOSITORY':'cephyrixzyth/Oneirodex','GITHUB_RUN_ID':'123'}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'.env').write_text('PRIVATE')
            with self.assertRaisesRegex(ProbeFailure,'dotenv'):server.require_backend_ci(root,env,'linux',1001)

    def test_owned_success_closes_server_before_dropping_and_does_not_publish_tokens(self):
        api=FakeAPI();progress={}
        fixture=server.ConnectedServer.open(Path('PRIVATE'),Path('PRIVATE'),progress,api=api,run_id='123')
        self.assertEqual(fixture.private_data['tokens'],{'PRIVATE':'PRIVATE'})
        fixture.close()
        self.assertEqual(api.events,['exists','create','start','ready','seed','stop','owned','drop','exists'])
        self.assertTrue(progress['backend_cleanup_verified']);self.assertNotIn('PRIVATE',repr(progress))

    def test_foreign_collision_is_not_removed_or_started(self):
        api=FakeAPI(collision=True)
        with self.assertRaisesRegex(ProbeFailure,'collision'):
            server.ConnectedServer.open(Path('PRIVATE'),Path('PRIVATE'),{},api=api,run_id='123')
        self.assertEqual(api.events,['exists'])

    def test_start_failure_cleans_owned_database_without_hiding_original(self):
        api=FakeAPI(fail='start');progress={}
        with self.assertRaisesRegex(ProbeFailure,'synthetic_start'):
            server.ConnectedServer.open(Path('PRIVATE'),Path('PRIVATE'),progress,api=api,run_id='123')
        self.assertTrue(progress['backend_cleanup_verified']);self.assertIn('drop',api.events)

    def test_primary_start_failure_survives_cleanup_and_prevents_live_database_drop(self):
        api=FakeAPI(fail='start',cleanup_fail=True);progress={}
        with self.assertRaisesRegex(ProbeFailure,'synthetic_start') as failed:
            server.ConnectedServer.open(Path('PRIVATE'),Path('PRIVATE'),progress,api=api,run_id='123')
        self.assertIn('linux_backend_cleanup_failed',failed.exception.__notes__)
        self.assertFalse(progress['backend_cleanup_verified']);self.assertNotIn('drop',api.events)

    def test_server_environment_is_explicit_and_excludes_operator_or_ci_values(self):
        env=server.backend_environment(Path('/owned/root'),Path('/owned/work'),'postgresql://fixture:synthetic@127.0.0.1/test','synthetic-secret',6121)
        self.assertEqual(env['PYTHON_DOTENV_DISABLED'],'1');self.assertEqual(env['UVICORN_WORKERS'],'1')
        self.assertEqual(env['PORT'],'6121');self.assertEqual(env['ONEIRODEX_ENABLE_BACKGROUND_WORKERS'],'false')
        self.assertNotIn('GH_TOKEN',env);self.assertNotIn('ONEIRODEX_INITIALIZATION_COMPLETE',env)

    def test_private_seed_failure_selects_only_fixed_class_without_raw_stderr(self):
        api=server.NativeServerAPI.__new__(server.NativeServerAPI)
        api.root=Path('PRIVATE');api.env={};api.marker='fixture';api.progress={}
        env={'GITHUB_ACTIONS':'true','RUNNER_OS':'Linux','GITHUB_REPOSITORY':'cephyrixzyth/Oneirodex','GITHUB_RUN_ID':'123'}
        result=SimpleNamespace(returncode=1,stdout=b'',stderr=b'{"error_class":"OperationalError","message":"PRIVATE"}\n')
        with mock.patch.dict(server.os.environ,env,clear=True),mock.patch.object(server.subprocess,'run',return_value=result):
            with self.assertRaises(ProbeFailure):api.internal('seed')
        self.assertEqual(api.progress['backend_internal_failure'],{'action':'seed','error_class':'OperationalError'})
        self.assertNotIn('PRIVATE',repr(api.progress))

    def test_seed_controls_require_bearer_denial_without_following_redirects(self):
        api=server.NativeServerAPI.__new__(server.NativeServerAPI)
        api.progress={};api.base_url='http://127.0.0.1:6121'
        tokens={label:'PRIVATE-'+label for label in ('adult','child','wrong','limited')}
        data={'tokens':tokens,'ids':{},'alembic_head':'fixture-head','postgres_version_num':'160016'}
        def response(path,token=None,**kwargs):
            if kwargs.get('method')=='OPTIONS':return 200,b'',{}
            status=401 if token==tokens['wrong'] else 403 if token==tokens['limited'] else 200
            return status,b'',{}
        with mock.patch.object(api,'internal',return_value=data),mock.patch.object(api,'http',side_effect=response):
            api.seed('fixture')
        self.assertEqual(api.progress['backend_bearer_http_controls'],{'adult':200,'child':200,'wrong':401,'limited':403})
        self.assertEqual(api.progress['native_origin_preflight'],{'http_status':200,'origin_allowed':False})
        self.assertNotIn('PRIVATE',repr(api.progress))

    def test_seed_control_failure_keeps_numeric_observation_and_never_accepts_wrong_token(self):
        api=server.NativeServerAPI.__new__(server.NativeServerAPI)
        api.progress={};api.base_url='http://127.0.0.1:6121'
        data={'tokens':dict.fromkeys(('adult','child','wrong','limited'),'PRIVATE'),
              'ids':{},'alembic_head':'fixture-head','postgres_version_num':'160016'}
        with mock.patch.object(api,'internal',return_value=data),mock.patch.object(api,'http',return_value=(200,b'',{})):
            with self.assertRaisesRegex(ProbeFailure,'control_failed_wrong'):api.seed('fixture')
        self.assertEqual(api.progress['backend_bearer_http_controls']['wrong'],200)
        self.assertNotIn('PRIVATE',repr(api.progress))

    def test_collection_list_projection_keeps_only_numeric_status_and_shape(self):
        projected=server.collection_list_projection(200,b'{"collections":[],"PRIVATE":"PRIVATE"}')
        self.assertEqual(projected,{'http_status':200,'root_array':False,'collections_array':True})
        self.assertNotIn('PRIVATE',repr(projected))
        self.assertEqual(server.collection_list_projection(200,b'[]')['root_array'],True)
        self.assertFalse(server.collection_list_projection(500,b'not-json PRIVATE')['collections_array'])


if __name__=='__main__':unittest.main()
