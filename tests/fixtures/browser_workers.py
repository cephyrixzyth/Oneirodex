"""Real-browser worker fixture using synthetic data and an owned loopback server."""
from contextlib import contextmanager
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent
LEGACY_HASH = '21f298241242f4239ac7f23c70944b067d410a642c2b011667ba73bdb6666abd'


def wait_js(page, expression, *, timeout=10):
    """Await the value of asynchronous probes, rather than a truthy Promise."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if page.evaluate(expression):
            return
        page.wait_for_timeout(50)
    raise AssertionError(f'Browser fixture condition did not settle: {expression}')


@contextmanager
def worker_site():
    legacy = (FIXTURES / 'vr-sw-legacy-fd2683e5.js').read_bytes()
    assert sha256(legacy).hexdigest() == LEGACY_HASH
    state = {'phase': 'legacy', 'account': 'adult-fixture', 'delayed_started': threading.Event(), 'delayed_release': threading.Event(), 'root_release': threading.Event()}
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            path = urlsplit(self.path).path
            phase, account = state['phase'], state['account']
            requests.append({'path': path, 'phase': phase})
            content_type = 'text/html; charset=utf-8'
            scope = None
            if path == '/vr/sw.js':
                if phase == 'current' and state.get('reject_update'):
                    self.send_error(503)
                    return
                payload = legacy if phase == 'legacy' else (ROOT / 'oneirodex/static/vr-sw.js').read_bytes()
                # The original endpoint permits /vr and its /vr/ descendant.
                content_type, scope = 'application/javascript', '/vr'
            elif path == '/sw.js':
                if phase == 'current' and state.get('root_failure') == 'reject':
                    self.send_error(503)
                    return
                if phase == 'current' and state.get('root_failure') == 'hang':
                    state['root_release'].wait(15)
                source = FIXTURES / 'app-sw-legacy-e26eb687.js' if phase == 'legacy' else ROOT / 'oneirodex/static/app-sw.js'
                payload = source.read_bytes()
                content_type, scope = 'application/javascript', '/'
            elif path == '/unrelated-worker.js':
                payload = b"self.addEventListener('install',e=>e.waitUntil(self.skipWaiting()));self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));"
                content_type, scope = 'application/javascript', '/unrelated/'
            elif path == '/static/js/od_pwa_install.js':
                payload = (ROOT / 'oneirodex/static/js/od_pwa_install.js').read_bytes()
                content_type = 'application/javascript'
            elif path == '/static/js/fixture.js':
                payload, content_type = b'/* public fixture asset */', 'application/javascript'
            elif path == '/static/library/images/fixture.png':
                payload, content_type = b'synthetic-private-cover', 'image/png'
            elif path == '/static/vr-manifest.webmanifest':
                payload = b'{"name":"Fixture","start_url":"/vr"}'
                content_type = 'application/manifest+json'
            elif path.startswith('/api/vr/'):
                if path == '/api/vr/delayed':
                    state['delayed_started'].set()
                    if not state['delayed_release'].wait(10):
                        self.send_error(504)
                        return
                payload = json.dumps({
                    'identity': account,
                    'titles': ['restricted-fixture-title'] if account == 'adult-fixture' else [],
                }).encode()
                content_type = 'application/json'
            elif path in {'/vr', '/vr/'}:
                installer = '<script src="/static/js/od_pwa_install.js"></script>' if phase == 'current' else ''
                payload = (
                    '<!doctype html><title>Privacy fixture</title><h1>' + account + '</h1>'
                    '<button type="button" data-action="logout">Sign out</button>'
                    '<a href="/logout">Sign out link</a>' + installer
                ).encode()
            elif path == '/offline':
                payload = b'<!doctype html><title>Offline</title><h1>Offline fixture</h1>'
            elif path == '/favicon.ico':
                payload = b''
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-cache' if scope else 'no-store')
            if scope:
                self.send_header('Service-Worker-Allowed', scope)
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', state, requests
    finally:
        state['delayed_release'].set()
        state['root_release'].set()
        server.shutdown()
        server.server_close()
        thread.join(5)
        assert not thread.is_alive(), 'Owned fixture server did not stop'


def exercise_worker_upgrade(*, root_preinstalled=False, legacy_scope='/vr', query='', logout='button', legacy_only=False, delayed=False, update_failure=False, root_failure=None):
    from playwright.sync_api import sync_playwright

    with worker_site() as (base, state, requests), sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base + '/') else route.abort())
            page = context.new_page()
            page.set_default_timeout(10000)
            page.goto(base + legacy_scope)
            page.evaluate("async()=>{await caches.open('unrelated-fixture').then(c=>c.put('/unrelated',new Response('unrelated-data')));await navigator.serviceWorker.register('/unrelated-worker.js',{scope:'/unrelated/'})}")
            if root_preinstalled:
                page.evaluate("navigator.serviceWorker.register('/sw.js',{scope:'/'})")
                wait_js(page, "()=>navigator.serviceWorker.controller?.scriptURL.endsWith('/sw.js')")
            page.evaluate("([scope,query])=>navigator.serviceWorker.register('/vr/sw.js'+query,{scope})", [legacy_scope, query])
            wait_js(page, "()=>!!navigator.serviceWorker.controller && new URL(navigator.serviceWorker.controller.scriptURL).pathname==='/vr/sw.js'")
            page.reload(wait_until='domcontentloaded')
            adult = page.evaluate("fetch('/api/vr/catalog').then(r=>r.json())")
            page.evaluate("fetch('/api/vr/games/fixture').then(r=>r.json())")
            wait_js(page, "async()=>!!(await (await caches.open('oneirodex-vr-v1')).match('/api/vr/catalog'))")
            result = {'legacy_controlled': True, 'adult_catalog': adult, 'chromium': browser.version}
            if legacy_only:
                page.evaluate("navigator.serviceWorker.controller.postMessage({type:'od-clear-caches'})")
                state['account'] = 'child-fixture'
                context.set_offline(True)
                page.reload(wait_until='domcontentloaded')
                result['offline_dom'] = page.locator('body').inner_text()
                result['offline_catalog'] = page.evaluate("fetch('/api/vr/catalog').then(r=>r.json())")
                return result

            if delayed:
                page.evaluate("()=>{window.delayedVr=fetch('/api/vr/delayed').then(r=>r.json());}")
                deadline = time.monotonic() + 5
                while not state['delayed_started'].is_set():
                    assert time.monotonic() < deadline, 'Old-worker request did not reach fixture'
                    page.wait_for_timeout(20)
            state['root_failure'] = root_failure
            state['reject_update'] = update_failure
            state['phase'] = 'current'
            page.add_script_tag(url=base + '/static/js/od_pwa_install.js')
            if delayed:
                wait_js(page, "()=>!!window.odPwaPrivacyReady")
                page.evaluate("()=>{window.privacySettled=false;window.odPwaPrivacyReady.then(()=>window.privacySettled=true)}")
                # Wait for the actual update request, rather than an arbitrary delay.
                deadline = time.monotonic() + 5
                while not any(r['path'] == '/vr/sw.js' and r['phase'] == 'current' for r in requests):
                    assert time.monotonic() < deadline, 'No legacy-worker update request'
                    page.wait_for_timeout(20)
                result['ready_while_old_fetch_pending'] = page.evaluate('window.privacySettled')
                state['delayed_release'].set()
                result['delayed_response'] = page.evaluate('window.delayedVr')
            # A fixed coordinator can delay private work until control is safe.
            ready = page.evaluate("async()=>window.odPwaPrivacyReady?await window.odPwaPrivacyReady:null")
            if ready is None:
                wait_js(page, "async()=>!!(await navigator.serviceWorker.getRegistrations()).find(r=>new URL(r.scope).pathname==='/' && r.active?.state==='activated')")
            result['ready'] = ready
            if update_failure or root_failure:
                return {'ready': ready, 'controller':page.evaluate('navigator.serviceWorker.controller.scriptURL'), 'requests':requests}
            result['safe_control_policy'] = page.evaluate("async()=>{const worker=navigator.serviceWorker.controller;const type=new URL(worker.scriptURL).pathname==='/sw.js'?'od-privacy-claim':'od-vr-retired';return new Promise(resolve=>{const ch=new MessageChannel();const timer=setTimeout(()=>resolve(null),1000);ch.port1.onmessage=e=>{clearTimeout(timer);ch.port1.close();resolve(e.data)};worker.postMessage({type},[ch.port2])})}")
            result['controller'] = page.evaluate("()=>new URL(navigator.serviceWorker.controller.scriptURL).pathname")
            assert ready is True, {'ready': ready, 'policy': result['safe_control_policy'], 'controller_state':page.evaluate('navigator.serviceWorker.controller.state'), 'controller': result['controller'], 'workers': page.evaluate("async()=>(await navigator.serviceWorker.getRegistrations()).map(r=>({scope:r.scope,active:r.active?.state,waiting:r.waiting?.state,installing:r.installing?.state}))"), 'requests': requests}
            result['registration_scopes'] = page.evaluate("async()=>(await navigator.serviceWorker.getRegistrations()).map(r=>new URL(r.scope).pathname)")
            # The safe retirement controller may remain attached until navigation.
            # A root claim cannot replace that unregistered controlling registration.
            page.reload(wait_until='domcontentloaded')
            wait_js(page, "()=>new URL(navigator.serviceWorker.controller.scriptURL).pathname==='/sw.js'")
            result['controller_after_navigation'] = page.evaluate("()=>new URL(navigator.serviceWorker.controller.scriptURL).pathname")
            page.evaluate("fetch('/api/vr/catalog').then(r=>r.json())")
            page.evaluate("fetch('/static/js/fixture.js?v=1').then(r=>r.text())")
            page.evaluate("fetch('/static/js/fixture.js').then(r=>r.text())")
            page.evaluate("fetch('/static/library/images/fixture.png?v=1').then(r=>r.text())")
            if result['controller_after_navigation'] == '/sw.js':
                wait_js(page, "async()=>!!(await caches.match('/static/js/fixture.js?v=1'))")
            result['cache_entries'] = page.evaluate("async()=>{const out=[];for(const name of await caches.keys()){for(const req of await(await caches.open(name)).keys()){const u=new URL(req.url);out.push({cache:name,path:u.pathname+u.search})}}return out}")
            context.set_offline(True)
            offline_page = context.new_page()
            offline_page.goto(base + '/vr', wait_until='domcontentloaded')
            result['offline_shell_before_logout'] = offline_page.locator('body').inner_text()
            offline_page.close()
            context.set_offline(False)
            # Keep the synthetic document in place; the real installer capture
            # listener still observes the link/button. No real logout endpoint.
            page.evaluate("document.querySelector('a[href=\"/logout\"]').addEventListener('click',e=>e.preventDefault())")
            page.locator('button[data-action=logout]' if logout == 'button' else 'a[href="/logout"]').click()
            state['account'] = 'child-fixture'
            context.set_offline(True)
            result['offline_catalog_after_logout'] = page.evaluate("fetch('/api/vr/catalog').then(r=>r.json()).catch(()=>({network_failed:true}))")
            if result['controller_after_navigation'] == '/sw.js':
                wait_js(page, "async()=>(await caches.keys()).every(n=>!n.startsWith('oneirodex-'))")
            result['caches_after_logout'] = page.evaluate('caches.keys()')
            result['unrelated_cache_body'] = page.evaluate("async()=>await(await(await caches.open('unrelated-fixture')).match('/unrelated')).text()")
            from playwright.sync_api import Error as BrowserError
            try:
                page.reload(wait_until='domcontentloaded')
                result['offline_navigation_failed_after_logout'] = False
            except BrowserError as error:
                if 'net::ERR_FAILED' not in str(error):
                    raise
                result['offline_navigation_failed_after_logout'] = True
            result['offline_dom_after_logout'] = page.locator('body').inner_text()
            result['requests'] = requests
            return result
        finally:
            browser.close()


def exercise_first_load_logout(*, unsupported=False, root_failure=None):
    from playwright.sync_api import sync_playwright

    with worker_site() as (base, state, _requests), sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base + '/') else route.abort())
            page = context.new_page()
            page.goto(base + '/vr')
            if unsupported:
                page.evaluate('delete Navigator.prototype.serviceWorker')
            state['root_failure'] = root_failure
            state['phase'] = 'current'
            page.add_script_tag(url=base + '/static/js/od_pwa_install.js')
            ready = page.evaluate('window.odPwaPrivacyReady')
            if not unsupported and not root_failure:
                wait_js(page, "()=>navigator.serviceWorker.controller?.scriptURL.endsWith('/sw.js')")
            page.evaluate("async()=>{for(const name of ['oneirodex-vr-v1','oneirodex-assets-fixture','unrelated-fixture']){await(await caches.open(name)).put('/fixture',new Response('fixture'))}}")
            page.locator('button[data-action=logout]').click()
            wait_js(page, "async()=>(await caches.keys()).every(n=>!n.startsWith('oneirodex-'))")
            return {'ready':ready,'caches':page.evaluate('caches.keys()')}
        finally:
            browser.close()
