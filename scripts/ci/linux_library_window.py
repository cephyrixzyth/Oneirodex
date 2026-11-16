"""Real Open full library handoff from the installed companion (DT-007).

The companion must open the server's own /library route in a separate
site-only window, without the API token in the address and without handing
that window the companion's native commands.
"""
import urllib.parse

from probe_linux_packaged import ProbeFailure
from linux_packaged_native import wait_for

LABEL = 'full-library'
LABELS_SCRIPT = '''const done = arguments[arguments.length - 1];
window.__TAURI_INTERNALS__.invoke('plugin:window|get_all_windows')
  .then(value => done(Array.isArray(value) ? value.map(String) : null), () => done(null));'''
CLICK_SCRIPT = '''const button = document.querySelector('#open-library-btn');
if (!(button instanceof HTMLButtonElement) || button.disabled) return false;
button.click(); return true;'''
STATUS_SCRIPT = '''const status = document.querySelector('#status');
return {opened: (status?.textContent || '').startsWith('Full library opened'),
        error: status?.dataset.tone === 'error'};'''
SITE_SCRIPT = '''const done = arguments[arguments.length - 1];
const ipc = window.__TAURI_INTERNALS__;
const finish = native => done({origin: location.origin, path: location.pathname,
  query_or_fragment: location.search + location.hash, ready: document.readyState === 'complete',
  native_secret_readable: native});
if (!ipc || typeof ipc.invoke !== 'function') finish(false);
else ipc.invoke('secure_store_get', {account: 'api_token'}).then(() => finish(true), () => finish(false));'''


def expected_origin(base_url):
    parts = urllib.parse.urlsplit(base_url)
    if parts.scheme not in ('http', 'https') or not parts.netloc:
        raise ProbeFailure('linux_library_base_url_invalid')
    return parts.scheme + '://' + parts.netloc


def require_site_page(value, base_url, token):
    """The opened page is the server's own route and carries no credential."""
    if not isinstance(value, dict) or value.get('ready') is not True:
        raise ProbeFailure('linux_library_window_not_loaded')
    if value.get('origin') != expected_origin(base_url):
        raise ProbeFailure('linux_library_window_wrong_origin')
    # An unauthenticated site view is sent to the server's sign-in page.
    if value.get('path') not in ('/library', '/login'):
        raise ProbeFailure('linux_library_window_unexpected_route')
    if token and token in str(value.get('query_or_fragment', '')) + str(value.get('path', '')):
        raise ProbeFailure('linux_library_window_address_contains_token')
    if value.get('native_secret_readable') is not False:
        raise ProbeFailure('linux_library_window_can_read_native_secret')


def _labels(native):
    value = native.execute_async(LABELS_SCRIPT)
    if not isinstance(value, list):
        raise ProbeFailure('linux_library_window_inventory_unavailable')
    return value


def open_full_library(native, base_url, token, progress):
    checks = progress.setdefault('full_library_checks', {})
    progress['phase'] = 'linux_full_library_handoff'
    if LABEL in _labels(native):
        raise ProbeFailure('linux_library_window_already_present')
    main = native.request('GET', native.session + '/window')
    before = list(native.request('GET', native.session + '/window/handles'))
    if native.execute_js(CLICK_SCRIPT) is not True:
        raise ProbeFailure('linux_library_button_unavailable')

    def opened():
        state = native.execute_js(STATUS_SCRIPT)
        if state.get('error') is True:
            raise ProbeFailure('linux_library_open_reported_error')
        return state.get('opened') is True and LABEL in _labels(native)
    wait_for(opened, 30, 'linux_library_window_not_created')
    checks['native_window_created_with_site_label'] = True

    handles = [item for item in native.request('GET', native.session + '/window/handles') if item not in before]
    checks['site_window_inspected'] = False
    if len(handles) == 1:
        try:
            native.request('POST', native.session + '/window', {'handle': handles[0]})
            holder = {}

            def loaded():
                holder['value'] = native.execute_async(SITE_SCRIPT)
                return isinstance(holder['value'], dict) and holder['value'].get('ready') is True \
                    and holder['value'].get('origin') != 'null'
            wait_for(loaded, 30, 'linux_library_window_not_loaded')
            require_site_page(holder['value'], base_url, token)
            checks.update(site_window_inspected=True, site_window_is_server_origin=True,
                          site_window_address_has_no_token=True, site_window_cannot_read_native_secret=True,
                          site_window_route=holder['value']['path'])
            native.request('DELETE', native.session + '/window')
        finally:
            native.request('POST', native.session + '/window', {'handle': main})
        wait_for(lambda: LABEL not in _labels(native), 15, 'linux_library_window_not_closed')
        checks['site_window_closed'] = True
    elif handles:
        raise ProbeFailure('linux_library_window_handles_ambiguous')
    progress['full_library_handoff_verified'] = checks['site_window_inspected']
