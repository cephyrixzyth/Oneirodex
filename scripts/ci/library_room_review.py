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
    shader_errors = []
    page.on('pageerror', lambda error: errors.append(type(error).__name__))
    page.on('console',lambda message: shader_errors.append('shader_compile') if message.type=='error' and 'Shader Error' in message.text else None)
    visual_only = os.environ.get('ROOM_BENCHMARK_VISUAL_ONLY') == '1'
    expected_materials = {role+'-'+kind+'.jpg' for role in ('walnut','floor','velvet') for kind in ('color','normal','roughness')}
    expected_materials.add('moonfall-playfield.svg')
    material_responses = {}
    cover_responses = {}
    def observe_material(response):
        from urllib.parse import urlsplit
        path = urlsplit(response.url).path
        name = path.rsplit('/',1)[-1]
        if path.startswith('/static/newstyle/rooms/aurora/') and name in expected_materials:
            material_responses[name] = response.status
        if path.startswith('/static/library/images/synthetic-room-cover-'):
            cover_responses[name] = response.status
    page.on('response',observe_material)
    if visual_only:
        report['capture_scope'] = 'visual-preview-only; no full game lifecycle qualification on this source'
        result['qualification_scope'] = 'visual-preview-only'
        page.set_default_timeout(60000)
    else:
        result['gameplay_viewport'] = {'width': 1000, 'height': 800}
        page.set_viewport_size(result['gameplay_viewport'])
        page.set_default_timeout(45000)

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

    def wait_for_game_action(name):
        menu = page.get_by_role('region', name='Moonfall Pinball controls')
        action = menu.get_by_role('button', name=name, exact=True)
        retry = menu.get_by_role('button', name='Retry connection', exact=True)
        action.or_(retry).first.wait_for(timeout=45000)
        if retry.is_visible():
            result['progress_initialization_retries'] = result.get('progress_initialization_retries', 0) + 1
            retry.click()
        action.wait_for(timeout=45000)
        return action

    def capture(name):
        # Playwright's visibility scrolling does not account for sticky chrome.
        # Center the real canvas so its top is not obscured in review images.
        page.locator('.od-library-room__canvas').evaluate(
            "element => element.scrollIntoView({block:'center',behavior:'instant'})")
        page.screenshot(path=str(output / name))

    def open_room():
        checkpoint('opening_room')
        page.goto(page.url.split('/library', 1)[0].split('/vr', 1)[0] + '/vr?room=open&vr_compat=collection', wait_until='domcontentloaded')
        page.get_by_role('group', name='Room stations', exact=True).wait_for()
        checkpoint('visiting_observatory')
        result['visit_label_matches'] = page.get_by_label('Visit room',exact=True).count()
        result['visit_option_present'] = page.evaluate("() => Array.from(document.querySelector('.od-library-room__controls select')?.options || []).some(option=>option.value==='oneirodex')")
        require(result['visit_label_matches'] == 1, 'visit_control_label_not_unique')
        require(result['visit_option_present'], 'observatory_option_missing')
        page.evaluate('''() => {
          const select=document.querySelector('.od-library-room__controls select');
          const trace={changeObserved:false}; window.__roomChoiceProbe=trace;
          select.addEventListener('change',()=>{
            trace.changeObserved=true; trace.observatoryAtEvent=select.value==='oneirodex';
            queueMicrotask(()=>{
              trace.observatoryAfterEvent=document.querySelector('.od-library-room__controls select')?.value==='oneirodex';
              trace.originalSelectConnected=select.isConnected;
            });
          },{once:true});
        }''')
        page.get_by_label('Visit room', exact=True).select_option('oneirodex')
        page.wait_for_function("() => document.querySelector('.od-library-room__controls select')?.value==='oneirodex'", polling=250)
        checkpoint('observatory_selected')
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
    page.wait_for_load_state('networkidle',timeout=60000)
    cover_urls = page.locator('.od-vr__card img').evaluate_all("images=>images.slice(0,4).map(image=>image.src)")
    require(len(cover_urls)==4 and all('/static/library/images/synthetic-room-cover-' in url for url in cover_urls),'synthetic_covers_missing')
    for url in cover_urls:
        response = page.context.request.get(url)
        require(response.status==200 and response.headers.get('content-type','').startswith('image/'),'synthetic_cover_http_failed')
        cover_responses[url.split('?',1)[0].rsplit('/',1)[-1]] = response.status
    result['authorized_synthetic_cover_count'] = len(cover_responses)
    case = page.locator('.od-vr__card').first
    case.wait_for()
    case_name = case.locator('span').inner_text()
    page.get_by_role('button',name='Library wall',exact=True).click()
    canvas = page.locator('.od-library-room__canvas')
    canvas.evaluate("element=>element.scrollIntoView({block:'center',behavior:'instant'})")
    box = canvas.bounding_box()
    # Project the first mounted cover through the actual authored library camera.
    # This uses ordinary pointer input, not a product debug route or selection hook.
    point = page.evaluate('''({width,height})=>{
      const yaw=-Math.atan2(3.2,2.55),pitch=Math.atan2(0.34,Math.hypot(3.2,2.55));
      const x=-2.22+3.2,y=1.99-1.65,z=-3.55+1;
      const viewX=Math.cos(yaw)*x-Math.sin(yaw)*z,rotatedZ=Math.sin(yaw)*x+Math.cos(yaw)*z;
      const viewY=y*Math.cos(pitch)+rotatedZ*Math.sin(pitch),viewZ=-y*Math.sin(pitch)+rotatedZ*Math.cos(pitch);
      const f=Math.tan(55*Math.PI/360);
      return {x:(viewX/(-viewZ*f*(width/height))+1)*width/2,y:(1-viewY/(-viewZ*f))*height/2};
    }''',{'width':box['width'],'height':box['height']})
    page.mouse.click(box['x']+point['x'],box['y']+point['y'])
    page.locator('.od-vr__detail h2').filter(has_text=case_name).wait_for()
    result['in_world_case_selection'] = True
    page.wait_for_load_state('networkidle',timeout=60000)
    page.get_by_role('button', name='Reading desk', exact=True).click()
    capture('observatory-reading.png')
    page.get_by_role('button', name='Library wall', exact=True).click()
    result['populated_catalog_selection'] = True
    capture('observatory-library.png')
    if visual_only:
        checkpoint('visual_materials')
        page.wait_for_load_state('networkidle',timeout=60000)
        result['material_assets'] = material_responses
        require(all(200 <= material_responses.get(name,0) < 300 or material_responses.get(name)==304 for name in expected_materials),'material_assets_missing')
        menu = page.get_by_role('region',name='Moonfall Pinball controls')
        retry = menu.get_by_role('button',name='Retry connection',exact=True)
        if retry.is_visible():
            result['visual_progress_retried'] = True
            retry.click()
        menu.get_by_role('button',name='Help',exact=True).wait_for(timeout=30000)
        for station,name in [('Room overview','observatory-overview'),('Lounge','observatory-lounge'),('Moonfall Pinball','moonfall-detail')]:
            checkpoint('visual_'+name)
            page.get_by_role('button',name=station,exact=True).click()
            page.evaluate('''() => new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))''')
            result.setdefault('preview_render_samples',{})[name] = page.evaluate('''() => new Promise(resolve=>{
              const gl=document.querySelector('.od-library-room__canvas').getContext('webgl2');
              const names=['drawArrays','drawElements','drawArraysInstanced','drawElementsInstanced'];
              const originals={}; let calls=0,lastCalls=0,lastTime;
              for(const name of names){originals[name]=gl[name];gl[name]=function(...args){calls++;return originals[name].apply(this,args)}}
              let complete=false;
              function finish(value){if(complete)return;complete=true;clearTimeout(timer);for(const name of names)gl[name]=originals[name];resolve(value)}
              const timer=setTimeout(()=>finish({timed_out:true}),15000);
              requestAnimationFrame(time=>{lastTime=time;lastCalls=calls;requestAnimationFrame(next=>finish({draw_calls:calls-lastCalls,frame_interval_ms:next-lastTime}))});
            })''')
            capture(name+'.png')
            page.locator('.od-library-room__canvas').screenshot(path=str(output/(name+'-canvas.png')))
        checkpoint('visual_low_and_help')
        menu.get_by_role('button',name='Help',exact=True).click()
        capture('moonfall-in-world-help.png')
        page.locator('.od-library-room__canvas').screenshot(path=str(output/'moonfall-in-world-help-canvas.png'))
        page.get_by_role('button',name='Back to game',exact=True).click()
        page.get_by_text('How to play and comfort',exact=True).click()
        page.evaluate('''()=>{
          const gl=document.querySelector('.od-library-room__canvas').getContext('webgl2');
          window.__roomTierUploads=[];window.__roomTierOriginals={};
          for(const name of ['texImage2D','texSubImage2D']){
            const original=gl[name];window.__roomTierOriginals[name]=original;
            gl[name]=function(...args){const image=args[args.length-1];if(image?.width&&image?.height&&window.__roomTierUploads.length<64)window.__roomTierUploads.push({width:image.width,height:image.height});return original.apply(this,args)};
          }
        }''')
        page.get_by_label('Quality',exact=True).select_option('low')
        page.evaluate('''()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))''')
        result['low_texture_uploads'] = page.evaluate('''()=>{
          const gl=document.querySelector('.od-library-room__canvas').getContext('webgl2');
          for(const [name,original] of Object.entries(window.__roomTierOriginals))gl[name]=original;
          return window.__roomTierUploads;
        }''')
        result['low_gl_error'] = page.evaluate("()=>document.querySelector('.od-library-room__canvas').getContext('webgl2').getError()")
        require(result['low_gl_error']==0,'low_texture_gl_error')
        require(sum(max(image['width'],image['height'])<=512 for image in result['low_texture_uploads'])>=9,'low_texture_sizes_not_applied')
        capture('moonfall-low.png')
        page.locator('.od-library-room__canvas').screenshot(path=str(output/'moonfall-low-canvas.png'))
        require(not errors,'browser_exception')
        require(not shader_errors,'shader_compile_failed')
        result['status'] = 'preview-captured'
        checkpoint('visual_preview_complete')
        return
    checkpoint('starting_run')
    wait_for_game_action('New run').click()
    page.get_by_role('button', name='Pause', exact=True).wait_for()
    page.get_by_role('button', name='Moonfall Pinball', exact=True).click()
    page.locator('.od-library-room__canvas').focus()
    checkpoint('launch_and_frames')
    page.keyboard.press('Space')
    timings = page.evaluate('''() => new Promise(resolve => {
      const frames=[]; let last, ticket, timer, finished=false;
      function finish() {
        if(finished) return; finished=true;
        cancelAnimationFrame(ticket); clearTimeout(timer); resolve(frames);
      }
      function frame(now) {
        if(last!==undefined) frames.push(now-last); last=now;
        if(frames.length>=4) finish(); else ticket=requestAnimationFrame(frame);
      }
      timer=setTimeout(finish,15000);
      ticket=requestAnimationFrame(frame);
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
    # Browser request contexts share the signed-in cookie jar; bearer controls
    # must use the fixture's owned, cookie-free transport instead.
    child_write = fixture.api.http(endpoint, tokens['child'], method='PUT', headers={'Content-Type':'application/json'},
                                   data=json.dumps({'revision':0,'state':stored['body']['state']}).encode())[0]
    result['child_write_status'] = child_write
    require(child_write == 403, 'write_scope_not_enforced')
    malformed = fixture.api.http(endpoint, tokens['adult'], method='PUT', headers={'Content-Type':'application/json'},data=b'{broken')[0]
    require(malformed == 422, 'malformed_body_accepted')
    oversized = fixture.api.http(endpoint, tokens['adult'], method='PUT', headers={'Content-Type':'application/json'},data=b' '*70000)[0]
    require(oversized == 413, 'oversized_body_accepted')
    result['real_http_identity_scope_and_body_denials'] = True
    checkpoint('capture_table')
    capture('moonfall-paused.png')
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
    checkpoint('resuming_saved_run')
    wait_for_game_action('Resume saved run').click()
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
    # The real checkpoint/autosave can fail and pause before the next click.
    # Wait for that outcome instead of racing a now-removed Pause button.
    page.get_by_role('status').filter(has_text='could not be saved').wait_for(timeout=30000)
    page.get_by_role('button', name='Continue without saving', exact=True).wait_for()
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
    checkpoint('resuming_seeded_result')
    wait_for_game_action('Resume saved run').click()
    page.get_by_role('heading', name='Run finished', exact=True).wait_for()
    capture('moonfall-seeded-result.png')
    result['seeded_result_display'] = True
    checkpoint('reset')
    page.get_by_role('button', name='Reset progress', exact=True).click()
    page.get_by_role('button', name='Delete saved progress', exact=True).click()
    page.get_by_role('status').filter(has_text='Saved progress reset.').wait_for()
    require(fetch()['body']['state'] is None, 'reset_payload_retained')
    # A losing run reached only by normal launches: no save injection.
    import time
    # Reduce software-rasterizer work for the long gameplay probe; full-size
    # room/table visual evidence was captured above. This is not a hardware FPS test.
    result['played_viewport'] = {'width':1000,'height':800}
    page.set_viewport_size(result['played_viewport'])
    page.get_by_role('button', name='New run', exact=True).click()
    checkpoint('played_result')
    page.get_by_text('How to play and comfort', exact=True).click()
    page.get_by_label('Quality',exact=True).select_option('low')
    played_start = time.monotonic()
    result['played_run_limit_seconds'] = 240
    deadline = played_start+240
    while time.monotonic() < deadline and page.get_by_role('heading', name='Run finished', exact=True).count() == 0:
        if page.locator('.od-moonfall-phase').inner_text().startswith('Ball ready'):
            page.get_by_role('button', name='Launch ball', exact=True).click()
        page.wait_for_timeout(500)
    result['played_elapsed_seconds'] = round(time.monotonic()-played_start,2)
    observed = fetch()
    if observed['status'] == 200 and observed['body']['state']:
        state = observed['body']['state']
        result['played_checkpoint'] = {key:state[key] for key in ('phase','tick','ballsRemaining','score')}
    page.get_by_role('heading', name='Run finished', exact=True).wait_for(timeout=1000)
    capture('moonfall-played-result.png')
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
