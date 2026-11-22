"""Real room qualification inside the existing guarded disposable visual job.

Never invoke on an operator machine. No fabricated responses or product debug hooks.
"""
import os
import json
import sys

from probe_linux_packaged import ProbeFailure
from release_visual_review import ROOT, require_capture_ci, capture_checkpoint


def review_library_room(page, output, report, fixture=None):
    require_capture_ci(ROOT, os.environ, sys.platform, getattr(os, 'geteuid', lambda: -1)())
    from PIL import Image, ImageStat

    output = output / 'room'
    output.mkdir()
    result = {'status': 'failed', 'renderer': 'CI Chromium; no hardware performance claim'}
    report['library_room'] = result
    def checkpoint(phase):
        result['phase'] = phase
        capture_checkpoint(output.parent,report,'room_'+phase)
    endpoint = '/api/room-games/moonfall-pinball/progress'
    errors = []
    page.on('pageerror', lambda error: errors.append(type(error).__name__))

    def fetch(method='GET', body=None, csrf=True):
        return page.evaluate('''async ({path,method,body,csrf}) => {
          const headers = {'Content-Type':'application/json'};
          if(csrf) Object.assign(headers, window.CSRFUtils?.getHeaders?.() || {});
          if(csrf && !headers['X-CSRFToken']) {
            const token = document.querySelector('meta[name="csrf-token"]')?.content;
            if(token) headers['X-CSRFToken'] = token;
          }
          const response = await window.fetch(path,{method,credentials:'same-origin',cache:'no-store',headers,
            ...(body===null ? {} : {body:JSON.stringify(body)})});
          return {status:response.status,body:await response.json()};
        }''', {'path': endpoint, 'method': method, 'body': body, 'csrf': csrf})

    def require(value, code):
        if not value:
            raise ProbeFailure('room_' + code)

    def open_room():
        checkpoint('opening_room')
        page.goto(page.url.split('/library', 1)[0].split('/vr', 1)[0] + '/vr?room=open&vr_compat=collection', wait_until='domcontentloaded')
        page.get_by_role('group', name='Room stations', exact=True).wait_for()
        checkpoint('visiting_observatory')
        page.get_by_label('Visit room', exact=True).select_option('oneirodex')
        page.get_by_role('button', name='Moonfall Pinball', exact=True).wait_for()
        checkpoint('waiting_for_populated_shelf')
        page.wait_for_function("() => document.querySelector('.od-library-room__controls[aria-label=\"Room shelf\"]')?.textContent.includes('Titles ')")

    open_room()
    checkpoint('reading_progress')
    result['webgl'] = page.evaluate('''() => {
      const gl=document.querySelector('.od-library-room__canvas')?.getContext('webgl2');
      if(!gl) return {supported:false};
      const debug=gl.getExtension('WEBGL_debug_renderer_info');
      return {supported:true,software:debug ? /swiftshader/i.test(gl.getParameter(debug.UNMASKED_RENDERER_WEBGL)) : null,
        width:gl.drawingBufferWidth,height:gl.drawingBufferHeight};
    }''')
    require(result['webgl']['supported'], 'webgl_context_unavailable')
    # This fixture belongs to the disposable job; clear any previous synthetic run.
    current = fetch()
    require(current['status'] == 200, 'read_failed')
    require(fetch('PUT', {'revision': current['body']['revision'], 'state': {}} , csrf=False)['status'] in (400, 403), 'csrf_not_enforced')
    if current['body']['state'] is not None:
        require(fetch('DELETE', {'revision': current['body']['revision']})['status'] == 200, 'reset_failed')
        open_room()
    checkpoint('catalog_selection')
    case = page.locator('.od-vr__card').first
    case.wait_for()
    case_name = case.locator('span').inner_text()
    case.click()
    page.locator('.od-vr__detail h2').filter(has_text=case_name).wait_for()
    page.get_by_role('button', name='Reading desk', exact=True).click()
    page.screenshot(path=str(output / 'observatory-reading.png'))
    page.get_by_role('button', name='Library wall', exact=True).click()
    result['populated_catalog_selection'] = True
    page.screenshot(path=str(output / 'observatory-library.png'))
    checkpoint('starting_run')
    page.get_by_role('button', name='New run', exact=True).click()
    page.get_by_role('button', name='Pause', exact=True).wait_for()
    page.get_by_role('button', name='Moonfall Pinball', exact=True).click()
    page.locator('.od-library-room__canvas').focus()
    checkpoint('launch_and_frames')
    page.keyboard.press('Space')
    timings = page.evaluate('''() => new Promise(resolve => {
      const frames=[]; let last, ticket;
      function frame(now) { if(last!==undefined) frames.push(now-last); last=now; ticket=requestAnimationFrame(frame); }
      ticket=requestAnimationFrame(frame);
      setTimeout(()=>{cancelAnimationFrame(ticket); resolve(frames)},2000);
    })''')
    require(len(timings) >= 2, 'animation_not_advancing')
    timings.sort()
    result['software_frame_intervals_ms'] = {'samples':len(timings),'median':timings[len(timings)//2],'p95':timings[min(len(timings)-1,int(len(timings)*.95))]}
    checkpoint('pause_and_save')
    page.get_by_role('button', name='Pause', exact=True).click()
    page.get_by_role('button', name='Save progress', exact=True).click()
    page.get_by_role('status').filter(has_text='Progress saved.').wait_for()
    stored = fetch()
    require(stored['status'] == 200 and stored['body']['state']['tick'] > 0, 'real_play_not_saved')
    require(stored['body']['state']['nextBallId'] > 1, 'ball_not_launched')
    checkpoint('http_denials_and_identity')
    require(fixture is not None, 'owned_fixture_missing')
    tokens = fixture.private_data['tokens']
    require(fixture.api.http(endpoint)[0] == 401, 'anonymous_progress_allowed')
    require(fixture.api.http(endpoint,tokens['limited'])[0] == 403, 'read_scope_not_enforced')
    peer_code, peer_body, _ = fixture.api.http(endpoint,tokens['child'])
    require(peer_code == 200 and json.loads(peer_body)['state'] is None, 'cross_member_disclosure')
    base = fixture.private_data['base_url']
    child_write = page.context.request.put(base+endpoint, headers={'Authorization':'Bearer '+tokens['child']}, data={'revision':0,'state':stored['body']['state']})
    require(child_write.status == 403, 'write_scope_not_enforced')
    malformed = page.context.request.put(base+endpoint, headers={'Authorization':'Bearer '+tokens['adult'],'Content-Type':'application/json'},data='{broken')
    require(malformed.status == 422, 'malformed_body_accepted')
    oversized = page.context.request.put(base+endpoint, headers={'Authorization':'Bearer '+tokens['adult'],'Content-Type':'application/json'},data=' '*70000)
    require(oversized.status == 413, 'oversized_body_accepted')
    result['real_http_identity_scope_and_body_denials'] = True
    checkpoint('capture_table')
    page.screenshot(path=str(output / 'moonfall-paused.png'))
    canvas_file = output / 'table-canvas.png'
    page.locator('.od-library-room__canvas').screenshot(path=str(canvas_file))
    with Image.open(canvas_file) as image:
        require(max(ImageStat.Stat(image.convert('RGB')).stddev) > 8, 'blank_render')
    result['real_launch_and_save'] = True
    result['saved_seed'] = stored['body']['state']['seed']
    result['saved_tick'] = stored['body']['state']['tick']

    # Reload must offer the actual server run and wait for explicit resume.
    checkpoint('reload_resume')
    open_room()
    page.get_by_role('button', name='Resume saved run', exact=True).click()
    page.get_by_role('button', name='Pause', exact=True).click()
    result['reload_resume'] = True
    checkpoint('settings')
    page.get_by_text('How to play and comfort', exact=True).click()
    page.get_by_role('checkbox', name='Reduced motion', exact=True).check()
    page.get_by_role('checkbox', name='High contrast targets', exact=True).check()
    page.get_by_label('Quality', exact=True).select_option('low')
    page.get_by_role('button', name='Save progress', exact=True).click()
    page.get_by_role('status').filter(has_text='Progress saved.').wait_for()
    checked = fetch()['body']['state']['settings']
    require(checked['quality'] == 'low' and checked['reducedMotion'] and checked['highContrast'], 'settings_not_saved')
    result['settings_saved'] = True

    # Real network denial: keep the mounted run and ask before discarding it.
    checkpoint('network_failure')
    page.route('**' + endpoint, lambda route: route.abort())
    page.get_by_role('button', name='Resume', exact=True).click()
    page.wait_for_timeout(200)
    page.get_by_role('button', name='Pause', exact=True).click()
    page.get_by_role('button', name='Save progress', exact=True).click()
    page.get_by_role('status').filter(has_text='could not be saved').wait_for()
    dialogs = []
    def cancel_leave(dialog):
        dialogs.append('unsaved' in dialog.message.lower())
        dialog.dismiss()
    page.once('dialog', cancel_leave)
    page.get_by_role('button', name='Close room', exact=True).click()
    page.get_by_role('button', name='Close room', exact=True).wait_for()
    require(dialogs == [True], 'failed_save_leave_dialog_missing')
    result['network_failure_keeps_room'] = True
    page.unroute('**' + endpoint)
    page.get_by_role('button', name='Retry connection', exact=True).click()
    page.get_by_role('button', name='Load server run', exact=True).click()

    # Force only a supported serialized result through the authenticated API.
    # This is a seeded result display check, not a claim of winning through play.
    checkpoint('seeded_result')
    saved = fetch()['body']
    terminal = dict(saved['state'])
    terminal.update(phase='game-over', ballsRemaining=0, balls=[], lastLaunch=False, lastRecover=False)
    require(fetch('PUT', {'revision': saved['revision'], 'state': terminal})['status'] == 200, 'seeded_result_rejected')
    open_room()
    page.get_by_role('button', name='Resume saved run', exact=True).click()
    page.get_by_role('heading', name='Run finished', exact=True).wait_for()
    page.screenshot(path=str(output / 'moonfall-seeded-result.png'))
    result['seeded_result_display'] = True
    checkpoint('reset')
    page.get_by_role('button', name='Reset progress', exact=True).click()
    page.get_by_role('button', name='Delete saved progress', exact=True).click()
    page.get_by_role('status').filter(has_text='Saved progress reset.').wait_for()
    require(fetch()['body']['state'] is None, 'reset_payload_retained')
    # A short losing run reached only by normal launches: no save injection.
    import time
    page.get_by_role('button', name='New run', exact=True).click()
    checkpoint('played_result')
    page.get_by_text('How to play and comfort', exact=True).click()
    page.get_by_label('Quality',exact=True).select_option('low')
    deadline = time.monotonic()+150
    while time.monotonic() < deadline and page.get_by_role('heading', name='Run finished', exact=True).count() == 0:
        if page.locator('.od-moonfall-phase').inner_text().startswith('Ball ready'):
            page.get_by_role('button', name='Launch ball', exact=True).click()
        page.wait_for_timeout(500)
    page.get_by_role('heading', name='Run finished', exact=True).wait_for(timeout=1000)
    page.screenshot(path=str(output/'moonfall-played-result.png'))
    result['result_through_normal_play'] = True
    checkpoint('teardown')
    page.get_by_role('button', name='Close room', exact=True).click()
    page.locator('.od-library-room__canvas').wait_for(state='detached')
    require(page.locator('.od-library-room__canvas').count() == 0, 'close_did_not_unmount')
    require(not errors, 'browser_exception')
    # Exercise simultaneous real PostgreSQL CAS through the owned HTTP listener.
    checkpoint('concurrent_cas')
    from concurrent.futures import ThreadPoolExecutor
    import threading
    import urllib.request
    import urllib.error
    current = json.loads(fixture.api.http(endpoint,tokens['adult'])[1])
    barrier = threading.Barrier(2)
    def writer():
        request = urllib.request.Request(base+endpoint, data=json.dumps({'revision':current['revision'],'state':stored['body']['state']}).encode(), method='PUT',headers={'Content-Type':'application/json','Authorization':'Bearer '+tokens['adult']})
        barrier.wait(timeout=10)
        try:
            with urllib.request.urlopen(request,timeout=10) as response: return response.status
        except urllib.error.HTTPError as error: return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(lambda _:writer(),range(2)))
    require(statuses == [200,409], 'concurrent_cas_did_not_reject_stale_writer')
    result['real_concurrent_cas'] = statuses
    result.update(status='passed', reset_and_teardown=True)
    checkpoint('complete')
