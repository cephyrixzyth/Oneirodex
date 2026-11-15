"""Real disposable CI backend. Local imports/tests create no resources."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

from probe_linux_packaged import ProbeFailure, require_ci_execution


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def collection_list_projection(status,body):
    try:value=json.loads(body)
    except (ValueError,UnicodeError):value=None
    return {'http_status':status,'root_array':isinstance(value,list),
            'collections_array':isinstance(value,dict) and isinstance(value.get('collections'),list)}


def search_list_projection(status,body):
    try:value=json.loads(body)
    except (ValueError,UnicodeError):value=None
    results=value.get('results') if isinstance(value,dict) else None
    games=value.get('games') if isinstance(value,dict) else None
    items=next((v for v in (value,results,games) if isinstance(v,list)),[])
    return {'http_status':status,'root_array':isinstance(value,list),
            'results_array':isinstance(results,list),'games_array':isinstance(games,list),
            'item_count':len(items),
            'shared_visible':any(isinstance(v,dict) and v.get('name')=='Synthetic CI Shared Game' for v in items),
            'private_visible':any(isinstance(v,dict) and v.get('name')=='Synthetic CI Adult Private Game' for v in items)}


def require_backend_ci(root, env, platform, uid):
    require_ci_execution(platform, env, uid)
    if (root/'.env').exists():
        raise ProbeFailure('linux_backend_checkout_has_operator_dotenv')


def validate_control_url(raw):
    try:
        parsed = urllib.parse.urlsplit(raw)
        if (parsed.scheme not in ('postgresql','postgresql+psycopg2')
                or parsed.hostname not in ('127.0.0.1','localhost','::1')
                or not re.fullmatch(r'[A-Za-z0-9_]*test[A-Za-z0-9_]*',parsed.path.lstrip('/'))
                or parsed.query or parsed.fragment or parsed.port not in (None,5432)):
            raise ValueError()
        return parsed
    except (ValueError, TypeError, AttributeError):
        raise ProbeFailure('linux_backend_control_database_not_safe') from None


def backend_environment(root, work, database_url, secret, port):
    return {'PATH':str(root/'venv/bin')+':/usr/local/bin:/usr/bin:/bin','LANG':'C.UTF-8',
            'HOME':str(work/'home'),'TMPDIR':str(work/'tmp'),'PYTHON_DOTENV_DISABLED':'1',
            'DATABASE_URL':database_url,'TEST_DATABASE_URL':database_url,'SECRET_KEY':secret,
            'PORT':str(port),'UVICORN_WORKERS':'1','SESSION_COOKIE_SECURE':'false',
            'ONEIRODEX_ENABLE_BACKGROUND_WORKERS':'false','ENABLE_EMAIL_DIGEST':'false',
            'DATA_FOLDER_GAMES':str(work/'games'),'BASE_FOLDER_POSIX':str(work/'games'),
            'ONEIRODEX_LIBRARY_DIR':str(work/'library'),
            'ONEIRODEX_ENV':'production'}


class ConnectedServer:
    @classmethod
    def open(cls, root, work, progress, api=None, run_id=None):
        run_id = run_id or os.environ.get('GITHUB_RUN_ID','')
        if not re.fullmatch(r'[1-9][0-9]*',run_id):
            raise ProbeFailure('linux_backend_run_not_safe')
        marker = 'oneirodex-ci-connected-'+uuid.uuid4().hex
        name = 'oneirodex_companion_test_'+run_id+'_'+marker[-12:]
        api = api or NativeServerAPI(root,work,progress)
        if api.exists(name):
            raise ProbeFailure('linux_backend_database_collision')
        context = cls(api,name,marker,progress)
        try:
            progress['phase'] = 'linux_backend_database_create'
            api.create(name,marker)
            progress['phase'] = 'linux_backend_startweb_start'
            api.start(name)
            api.ready()
            progress['phase'] = 'linux_backend_seed'
            context.private_data = api.seed(name)
            progress.update(backend_ready=True,backend_synthetic_seeded=True)
            return context
        except BaseException as error:
            try:
                context.close()
            except Exception:
                error.add_note('linux_backend_cleanup_failed')
            raise

    def __init__(self,api,name,marker,progress):
        self.api,self.name,self.marker,self.progress = api,name,marker,progress
        self.private_data = {}
        self.closed = False

    def close(self):
        if self.closed:
            return
        self.progress['backend_cleanup_verified'] = False
        self.api.stop()
        if self.api.owned(self.name,self.marker):
            self.api.drop(self.name,self.marker)
        if self.api.exists(self.name):
            raise ProbeFailure('linux_backend_database_cleanup_not_verified')
        self.progress['backend_cleanup_verified'] = True
        self.closed = True
        self.private_data.clear()


class NativeServerAPI:
    def __init__(self,root,work,progress):
        require_backend_ci(root,os.environ,sys.platform,getattr(os,'geteuid',lambda:-1)())
        source=subprocess.run(['git','rev-parse','HEAD'],cwd=root,capture_output=True,timeout=10)
        head=source.stdout.decode().strip()
        if source.returncode or not re.fullmatch(r'[a-f0-9]{40}',head):
            raise ProbeFailure('linux_backend_source_identity_not_verified')
        progress['backend_source_commit']=head
        self.control = validate_control_url(os.environ.get('ONEIRODEX_CI_CONTROL_DATABASE_URL',''))
        self.root,self.work,self.progress = root,work/'server',progress
        self.work.mkdir(mode=0o700)
        self.process,self.log,self.engine = None,None,None
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())

    @contextmanager
    def admin(self):
        import psycopg2
        raw=urllib.parse.urlunsplit(self.control).replace('postgresql+psycopg2://','postgresql://',1)
        connection=psycopg2.connect(raw)
        connection.autocommit=True
        try:
            with connection.cursor() as cursor:
                yield cursor
        finally:
            connection.close()

    def exists(self,name):
        with self.admin() as cursor:
            cursor.execute('SELECT 1 FROM pg_database WHERE datname=%s',(name,))
            return cursor.fetchone() is not None

    def create(self,name,marker):
        from psycopg2 import sql
        with self.admin() as cursor:
            cursor.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
            try:
                cursor.execute(sql.SQL('COMMENT ON DATABASE {} IS %s').format(sql.Identifier(name)),(marker,))
                self.marker=marker
            except BaseException:
                cursor.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
                raise

    def owned(self,name,marker):
        with self.admin() as cursor:
            cursor.execute("SELECT shobj_description(oid,'pg_database') FROM pg_database WHERE datname=%s",(name,))
            row=cursor.fetchone()
            return row is not None and row[0]==marker

    def drop(self,name,marker):
        from psycopg2 import sql
        if not self.owned(name,marker):
            raise ProbeFailure('linux_backend_database_owner_mismatch')
        with self.admin() as cursor:
            cursor.execute('SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=%s AND pid<>pg_backend_pid()',(name,))
            cursor.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))

    def start(self,name):
        from linux_packaged_native import GUARDIAN_CODE,free_port
        self.port=free_port();self.base_url='http://127.0.0.1:'+str(self.port)
        self.child_url=urllib.parse.urlunsplit(self.control._replace(path='/'+name))
        self.env=backend_environment(self.root,self.work,self.child_url,secrets.token_urlsafe(48),self.port)
        for key in ('HOME','TMPDIR','DATA_FOLDER_GAMES'):
            Path(self.env[key]).mkdir(mode=0o700)
        self.log_path=self.work/'startweb.log';self.log=self.log_path.open('xb')
        self.process=subprocess.Popen([sys.executable,'-c',GUARDIAN_CODE,'bash',str(self.root/'startweb.sh')],
                                      cwd=self.root,env=self.env,stdin=subprocess.DEVNULL,
                                      stdout=self.log,stderr=self.log,start_new_session=True)
        self.progress['backend_launcher']='startweb.sh'

    def http(self,path,token=None,method='GET',headers=None):
        from linux_packaged_native import listener_owned
        if not listener_owned(self.port,self.process.pid,allow_wildcard=True):
            raise ProbeFailure('linux_backend_listener_not_owned')
        selected={'Accept':'application/json',**(headers or {})}
        if token:
            selected['Authorization']='Bearer '+token
        request=urllib.request.Request(self.base_url+path,method=method,headers=selected)
        try:
            with self.opener.open(request,timeout=3) as response:
                return response.status,response.read(1024*1024),dict(response.headers)
        except urllib.error.HTTPError as error:
            return error.code,error.read(16384),dict(error.headers)

    def ready(self):
        from linux_packaged_native import listener_owned,wait_for
        def ready():
            # The real launcher binds all IPv4 interfaces; requests still target only loopback.
            if not listener_owned(self.port,self.process.pid,allow_wildcard=True):
                return False
            try:return self.http('/awake')[0]==200
            except OSError:return False
        wait_for(ready,120,'linux_real_backend_not_ready')
        self.progress['backend_listener_owned']=True

    def seed(self,name):
        data=self.internal('seed')
        self.progress['backend_alembic_head']=data.pop('alembic_head')
        self.progress['postgres_version_num']=data.pop('postgres_version_num')
        controls={}
        self.progress['backend_bearer_http_controls']=controls
        # Bearer rejection must be a readable JSON401, so the companion can
        # distinguish denial from browser login redirects and network errors.
        # Ordinary browser redirects are verified separately by handler tests.
        for label,expected in (('adult',200),('child',200),('wrong',401),('limited',403)):
            code,_,_=self.http('/api/client/identity',data['tokens'][label])
            controls[label]=code
            if code!=expected:
                raise ProbeFailure('linux_backend_bearer_control_failed_'+label)
        code,_,headers=self.http('/api/collections',method='OPTIONS',headers={
            'Origin':'tauri://localhost','Access-Control-Request-Method':'GET',
            'Access-Control-Request-Headers':'authorization'})
        self.progress['native_origin_preflight']={'http_status':code,
            'origin_allowed':headers.get('access-control-allow-origin',headers.get('Access-Control-Allow-Origin'))=='tauri://localhost'}
        code,body,_=self.http('/api/collections',data['tokens']['adult'])
        self.progress['backend_collection_list_shape']=collection_list_projection(code,body)
        search_controls={}
        for role in ('adult','child'):
            for label,query in (('empty',''),('star','*'),('letter','a')):
                code,body,_=self.http('/api/search?'+urllib.parse.urlencode({'query':query}),data['tokens'][role])
                search_controls[role+'_'+label]=search_list_projection(code,body)
        self.progress['backend_search_wire_controls']=search_controls
        data['base_url']=self.base_url
        return data

    def internal(self,action,payload=None):
        if action not in ('seed','revoke'):raise ProbeFailure('linux_fixture_action_not_allowed')
        safe_ci={key:os.environ[key] for key in ('GITHUB_ACTIONS','RUNNER_OS','GITHUB_REPOSITORY','GITHUB_RUN_ID')}
        result=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--'+action+'-owned'],
                              cwd=self.root,env={**self.env,**safe_ci,'ONEIRODEX_CI_DATABASE_MARKER':self.marker},
                              input=json.dumps(payload).encode() if payload is not None else None,
                              capture_output=True,timeout=120)
        if result.returncode or len(result.stdout)>65536:
            failure={'action':action,'error_class':'unclassified'}
            try:
                diagnostic=json.loads(result.stderr[-16384:].splitlines()[-1])
                known={'ProbeFailure','RuntimeError','ImportError','ModuleNotFoundError','OperationalError',
                       'ProgrammingError','IntegrityError','ValueError','TypeError','AttributeError','KeyError'}
                if diagnostic.get('error_class') in known:failure['error_class']=diagnostic['error_class']
            except (ValueError,IndexError,AttributeError):pass
            self.progress['backend_internal_failure']=failure
            raise ProbeFailure('linux_backend_'+action+'_failed_exit_'+str(result.returncode & 0xFFFFFFFF))
        return json.loads(result.stdout)

    def revoke(self,ids):
        if self.internal('revoke',ids).get('revoked') is not True:
            raise ProbeFailure('linux_fixture_revocation_not_persisted')

    def stop(self):
        if self.process is not None:
            from linux_packaged_native import NativeLinuxAPI
            NativeLinuxAPI.__new__(NativeLinuxAPI).stop(self.process)
        if self.log is not None:
            self.log.close();self.log=None
        if self.engine is not None:self.engine.dispose()
        if hasattr(self,'log_path'):
            try:
                with self.log_path.open('rb') as source:data=source.read(65537)
                prefix=data[:65536];text=prefix.decode(errors='replace').lower()
                categories=('modulenotfounderror','operationalerror','runtimeerror','permission denied','migration','failed')
                self.progress['selected_backend_log']={'prefix_bytes':len(prefix),'truncated':len(data)>65536,
                    'prefix_sha256':hashlib.sha256(prefix).hexdigest(),
                    'matched_categories':[v.replace(' ','_') for v in categories if v in text]}
            except OSError:self.progress['selected_backend_log']={'observation':'unavailable'}


def seed_native_fixture():
    root=Path(__file__).resolve().parents[2]
    require_backend_ci(root,os.environ,sys.platform,getattr(os,'geteuid',lambda:-1)())
    sys.path.insert(0,str(root))
    parsed=validate_control_url(os.environ.get('DATABASE_URL',''))
    if not re.fullmatch(r'oneirodex_companion_test_[1-9][0-9]*_[a-f0-9]{12}',parsed.path.lstrip('/')):
        raise ProbeFailure('linux_seed_database_not_owned_shape')
    from sqlalchemy import create_engine,select,text
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from oneirodex.models import User,GlobalSettings,Library,Game,UserLibraryAccess
    from oneirodex.platform import LibraryPlatform
    from oneirodex.runtime_native.db_session import native_db,native_engine_session_scope
    from oneirodex.utils.api_tokens import generate_api_token
    engine=create_engine(urllib.parse.urlunsplit(parsed).replace('postgresql://','postgresql+psycopg2://',1))
    try:
        with native_engine_session_scope(engine):
            db=native_db.session
            marker=os.environ.get('ONEIRODEX_CI_DATABASE_MARKER','')
            if not re.fullmatch(r'oneirodex-ci-connected-[a-f0-9]{32}',marker):
                raise ProbeFailure('linux_seed_database_marker_missing')
            actual=db.scalar(text("SELECT shobj_description(oid,'pg_database') FROM pg_database WHERE datname=current_database()"))
            if actual!=marker:
                raise ProbeFailure('linux_seed_database_marker_mismatch')
            if db.execute(select(User.id).limit(1)).first() is not None:
                raise ProbeFailure('linux_seed_database_not_empty')
            config=Config(str(root/'alembic.ini'));config.set_main_option('script_location',str(root/'alembic'))
            head=db.scalar(text('SELECT version_num FROM alembic_version'))
            if head!=ScriptDirectory.from_config(config).get_current_head():
                raise ProbeFailure('linux_seed_schema_head_not_verified')
            version=db.scalar(text("SELECT current_setting('server_version_num')"))
            settings=db.execute(select(GlobalSettings)).scalars().one()
            settings.setup_completed=True;settings.setup_in_progress=False;settings.enable_store_ownership_sync=False
            adult=User(name='SyntheticCIAdult',email='ci-adult@example.test',role='user',state=True,is_email_verified=True)
            child=User(name='SyntheticCIChild',email='ci-child@example.test',role='child',state=True,is_email_verified=True)
            for user in (adult,child):user.set_password(secrets.token_urlsafe(32));db.add(user)
            allowed=Library(name='Synthetic CI Allowed',platform=LibraryPlatform.OTHER)
            private=Library(name='Synthetic CI Adult Private',platform=LibraryPlatform.PCWIN)
            db.add_all([allowed,private]);db.flush()
            from linux_installed_journey import write_fixture_archive
            archive,manifest=write_fixture_archive(Path(os.environ['DATA_FOLDER_GAMES']))
            shared=Game(uuid=str(uuid.uuid4()),name='Synthetic CI Shared Game',library_uuid=allowed.uuid,
                        full_disk_path=str(archive),size=manifest['archive_bytes'])
            db.add(shared)
            db.add(Game(uuid=str(uuid.uuid4()),name='Synthetic CI Adult Private Game',library_uuid=private.uuid))
            db.add(UserLibraryAccess(user_id=child.id,library_uuid=allowed.uuid));db.commit()
            tokens,ids={},{}
            for label,user,scopes in (('adult',adult,['read:library','write:download','write:presence']),
                                      ('child',child,['read:library','write:presence']),('limited',adult,['write:presence'])):
                row,raw=generate_api_token(user,'Synthetic CI '+label,scopes)
                tokens[label]=raw;ids[label]={'token_id':row.id,'user_id':user.id,'account_id':user.user_id}
            tokens['wrong']='_'.join(tokens['adult'].split('_',2)[:2])+'_'+secrets.token_urlsafe(32)
            return {'tokens':tokens,'ids':ids,'alembic_head':head,'postgres_version_num':version,
                    'installed_fixture':{'game_uuid':shared.uuid,'manifest':manifest}}
    finally:
        engine.dispose()


def revoke_native_fixture(payload):
    root=Path(__file__).resolve().parents[2]
    require_backend_ci(root,os.environ,sys.platform,getattr(os,'geteuid',lambda:-1)())
    sys.path.insert(0,str(root))
    parsed=validate_control_url(os.environ.get('DATABASE_URL',''))
    marker=os.environ.get('ONEIRODEX_CI_DATABASE_MARKER','')
    if (not re.fullmatch(r'oneirodex_companion_test_[1-9][0-9]*_[a-f0-9]{12}',parsed.path.lstrip('/'))
            or not re.fullmatch(r'oneirodex-ci-connected-[a-f0-9]{32}',marker)):
        raise ProbeFailure('linux_fixture_revoke_database_not_owned')
    from sqlalchemy import create_engine,text
    from oneirodex.runtime_native.db_session import native_db,native_engine_session_scope
    from oneirodex.utils.api_tokens import revoke_api_token
    from oneirodex.models import ApiToken
    engine=create_engine(urllib.parse.urlunsplit(parsed).replace('postgresql://','postgresql+psycopg2://',1))
    try:
        with native_engine_session_scope(engine):
            db=native_db.session
            if db.scalar(text("SELECT shobj_description(oid,'pg_database') FROM pg_database WHERE datname=current_database()"))!=marker:
                raise ProbeFailure('linux_fixture_revoke_database_marker_mismatch')
            if not revoke_api_token(payload['token_id'],user_id=payload['user_id']):
                raise ProbeFailure('linux_fixture_revoke_failed')
            row=db.get(ApiToken,payload['token_id'])
            return {'revoked':row is not None and row.revoked_at is not None}
    finally:engine.dispose()


if __name__=='__main__':
    if sys.argv[1:] not in (['--seed-owned'],['--revoke-owned']):sys.exit(2)
    try:
        value=seed_native_fixture() if sys.argv[1]=='--seed-owned' else revoke_native_fixture(json.loads(sys.stdin.buffer.read(4096)))
    except Exception as error:
        print(json.dumps({'code':'linux_seed_failed','error_class':type(error).__name__}),file=sys.stderr)
        sys.exit(1)
    print(json.dumps(value))  # Private pipe to the controller, never inherited CI stdout.
