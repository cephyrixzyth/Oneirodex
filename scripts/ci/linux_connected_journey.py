"""Drive the installed bundled form and genuine credential/native/server APIs."""
from contextlib import contextmanager
from pathlib import Path
import stat

from probe_linux_packaged import ProbeFailure
from linux_packaged_native import wait_for
from linux_packaged_runtime import execute_probe
from linux_connected_server import ConnectedServer


STATE_SCRIPT = '''return (() => {
  const summary = document.querySelector('#auth-summary')?.textContent || '';
  const status = document.querySelector('#status')?.textContent || '';
  const titles = document.querySelector('#library')?.textContent || '';
  const requested = path => (performance.getEntriesByType?.('resource') || []).some(entry => {
    try { return new URL(entry.name).pathname === path; } catch { return false; }
  });
  return {ready: status === 'Enter credentials and click Connect.',
    online: /\\bOnline\\b/.test(summary), denied: summary.includes('Server access denied'),
    network_error: /network|cors|tls/i.test(status), keyring_error: /keyring|credential store|secure.store/i.test(status),
    protocol_error: status.includes('Server API returned an unexpected response'),
    redirect_error: status.includes('Server API redirect refused'),
    permission_error: status.includes('Companion permission error'),
    connecting: status === 'Connecting…',
    identity_requested: requested('/api/client/identity'), search_requested: requested('/api/search'),
    shared_visible: titles.includes('Synthetic CI Shared Game'),
    private_visible: titles.includes('Synthetic CI Adult Private Game')};
})();'''
STATE_FIELDS = ('ready','online','denied','network_error','keyring_error','protocol_error',
                'redirect_error','permission_error','connecting','identity_requested','search_requested',
                'shared_visible','private_visible')


def mark(progress,label):
    progress.setdefault('connected_account_checks',{})[label]=True


@contextmanager
def ui_session(native,number):
    error=None
    try:
        native.open_round(number)
        yield
    except BaseException as failed:
        error=failed
        raise
    finally:
        try:native.stop_round()
        except Exception:
            if error is None:raise
            error.add_note('linux_connected_ui_cleanup_failed')


def connect(native,base_url,token,expected,progress,label,private_visible=None):
    native.execute_js('''document.querySelector('#base-url').value = arguments[0];
      document.querySelector('#token').value = arguments[1];
      document.querySelector('#connect-form').requestSubmit();''',[base_url,token])
    def settled():
        value=native.execute_js(STATE_SCRIPT)
        snapshot={key:value.get(key) is True for key in STATE_FIELDS}
        progress['failed_ui_snapshot']=snapshot
        return snapshot[expected] and (private_visible is None or
            (snapshot['shared_visible'] and snapshot['private_visible'] is private_visible))
    wait_for(settled,30,'linux_connected_ui_'+label+'_not_verified')
    progress.pop('failed_ui_snapshot',None)
    mark(progress,label)


def require_credentials(native,token,base_url,progress,label):
    value=native.execute_async('''const done=arguments[arguments.length-1], token=arguments[0], base=arguments[1];
      Promise.all([window.__TAURI_INTERNALS__.invoke('load_config'),
        window.__TAURI_INTERNALS__.invoke('secure_store_get',{account:'api_token'})])
      .then(([config,secret])=>done({secret_matches:secret===token,config_base_matches:config.base_url===base,
        config_token_empty:!config.token}),()=>done({secret_matches:false,config_base_matches:false,config_token_empty:false}));''',[token,base_url])
    if not all(value.get(key) is True for key in ('secret_matches','config_base_matches','config_token_empty')):
        raise ProbeFailure('linux_native_credential_check_failed')
    mark(progress,label)


def require_private_config(native,tokens,progress,label):
    config=native.app_directory/'config.json'
    if (not config.resolve(strict=True).is_relative_to(native.data_root.resolve(strict=True))
            or not stat.S_ISREG(config.lstat().st_mode) or config.stat().st_size>1024*1024):
        raise ProbeFailure('linux_persisted_config_not_owned_regular_file')
    value=config.read_bytes()
    if any(token.encode() in value for token in tokens.values()):
        raise ProbeFailure('linux_plaintext_token_in_owned_app_config')
    mark(progress,label)


def identity(native,base_url,account_id,progress,label):
    value=native.execute_async('''const done=arguments[arguments.length-1], base=arguments[0], account=arguments[1];
      (async()=>{const token=await window.__TAURI_INTERNALS__.invoke('secure_store_get',{account:'api_token'});
        const response=await fetch(base+'/api/client/identity',{headers:{Authorization:'Bearer '+token},redirect:'manual'});
        const body=await response.json();return response.status===200 && (body.data?.account_id??body.account_id)===account;
      })().then(done,()=>done(false));''',[base_url,account_id])
    if value is not True:raise ProbeFailure('linux_live_account_identity_not_verified')
    mark(progress,label)


def run_connected_journey(native,fixture,progress):
    data=fixture.private_data;tokens=data['tokens'];ids=data['ids'];base=data['base_url']
    with ui_session(native,3):
        wait_for(lambda:native.execute_js(STATE_SCRIPT).get('ready') is True,30,'linux_fresh_ui_hydration_not_ready')
        connect(native,base,tokens['adult'],'online',progress,'adult_connect',private_visible=True)
        require_private_config(native,tokens,progress,'adult_persisted_json_has_no_plaintext_token')
        require_credentials(native,tokens['adult'],base,progress,'adult_os_credential_persisted')
        identity(native,base,ids['adult']['account_id'],progress,'adult_live_identity')
    with ui_session(native,4):
        wait_for(lambda:native.execute_js(STATE_SCRIPT).get('ready') is True,30,'linux_saved_ui_hydration_not_ready')
        hydrated=native.execute_js("return document.querySelector('#base-url').value===arguments[0] && document.querySelector('#token').value===arguments[1];",[base,tokens['adult']])
        if hydrated is not True:raise ProbeFailure('linux_os_credential_cold_hydration_failed')
        mark(progress,'os_credential_hydrated_after_app_cold_reopen')
        connect(native,base,tokens['adult'],'online',progress,'adult_reconnect',private_visible=True)
        for label in ('wrong','limited'):
            connect(native,base,tokens[label],'denied',progress,label+'_token_denied')
            require_credentials(native,tokens['adult'],base,progress,label+'_failed_connect_preserves_credential')
        connect(native,base,tokens['child'],'online',progress,'child_account_switch',private_visible=False)
        require_private_config(native,tokens,progress,'child_persisted_json_has_no_plaintext_token')
        require_credentials(native,tokens['child'],base,progress,'child_os_credential_persisted')
        identity(native,base,ids['child']['account_id'],progress,'child_live_identity')
        fixture.api.revoke(ids['child'])
        mark(progress,'child_revocation_persisted')
        connect(native,base,tokens['child'],'denied',progress,'revoked_token_denied')
        require_credentials(native,tokens['child'],base,progress,'revoked_denial_preserves_saved_credential')
        native.execute_js("document.querySelector('#forget-account-btn').click();")
        wait_for(lambda:native.execute_js("return document.querySelector('#token').value==='' && document.querySelector('#base-url').value==='';") is True,
                 30,'linux_forget_fields_not_cleared')
        require_credentials(native,None,'',progress,'forget_clears_os_credential_and_config')
    require_private_config(native,tokens,progress,'forgotten_json_has_no_plaintext_token')
    progress['connected_account_journey_verified']=True


def run_connected_package(deb,work,progress):
    fixture=ConnectedServer.open(Path(__file__).resolve().parents[2],work,progress)
    error=None
    try:
        execute_probe(deb,work,progress,journey=lambda native,report:run_connected_journey(native,fixture,report))
    except BaseException as failed:
        error=failed
        progress['installed_runtime_acceptance']=False
        raise
    finally:
        try:fixture.close()
        except Exception:
            progress['installed_runtime_acceptance']=False
            if error is None:raise
            error.add_note('linux_backend_cleanup_failed')
