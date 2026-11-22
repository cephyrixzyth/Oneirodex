"""Populated, authenticated release screenshots on an explicit disposable CI run."""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import uuid

from probe_linux_packaged import ProbeFailure
from linux_connected_server import ConnectedServer, require_backend_ci, validate_control_url


ROOT = Path(__file__).resolve().parents[2]


def capture_checkpoint(output, report, phase):
    """Preserve an explicitly incomplete receipt even if the browser stalls."""
    report['phase'] = phase
    temporary = output/'report-in-progress.tmp'
    temporary.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    temporary.replace(output/'report-in-progress.json')
    print(json.dumps({'phase':phase}),flush=True)


def require_capture_ci(root, env, platform, uid):
    require_backend_ci(root, env, platform, uid)
    if env.get('RELEASE_VISUAL_ALLOWED') != '1':
        raise ProbeFailure('release_visual_not_explicitly_selected')


def capture_slug(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', value):
        raise ProbeFailure('release_visual_theme_slug_invalid')
    return value


def seed_owned(payload):
    require_capture_ci(ROOT, os.environ, sys.platform, getattr(os, 'geteuid', lambda: -1)())
    parsed = validate_control_url(os.environ.get('DATABASE_URL', ''))
    marker = os.environ.get('ONEIRODEX_CI_DATABASE_MARKER', '')
    if (not re.fullmatch(r'oneirodex_companion_test_[1-9][0-9]*_[a-f0-9]{12}', parsed.path.lstrip('/'))
            or not re.fullmatch(r'oneirodex-ci-connected-[a-f0-9]{32}', marker)
            or type(payload.get('user_id')) is not int
            or not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', payload.get('password', ''))):
        raise ProbeFailure('release_visual_seed_not_owned')
    sys.path.insert(0, str(ROOT))
    from sqlalchemy import create_engine, select, text
    from oneirodex.runtime_native.db_session import native_db, native_engine_session_scope
    from oneirodex.models import (User, UserPreference, Library, Game, GlobalSettings,
                                 ChatSpace, ChatSpaceMember, ChatChannel, ChatChannelMember, ChatMessage)
    from oneirodex.platform import LibraryPlatform
    engine = create_engine(urllib_url(parsed))
    try:
        with native_engine_session_scope(engine):
            db = native_db.session
            if db.scalar(text("SELECT shobj_description(oid,'pg_database') FROM pg_database WHERE datname=current_database()")) != marker:
                raise ProbeFailure('release_visual_database_marker_mismatch')
            user = db.get(User, payload['user_id'])
            if user is None or user.name != 'SyntheticCIAdult':
                raise ProbeFailure('release_visual_seed_user_mismatch')
            user.name = 'demo-curator'; user.role = 'admin'; user.set_password(payload['password'])
            user.avatarpath = 'newstyle/avatars/fox.svg'
            user.preferences = UserPreference(theme='default', icon_pack='outline', items_per_page=50)
            peer = User(name='demo-member', email='demo-member@example.test', role='user', state=True, is_email_verified=True)
            peer.avatarpath = 'newstyle/avatars/owl.svg'
            peer.set_password(secrets.token_urlsafe(40)); db.add(peer)
            existing = db.execute(select(Game).order_by(Game.id)).scalars().all()
            for game, title in zip(existing, ('Lunar Workshop', 'Evening Notebook')): game.name = title
            titles = ('Moon Garden','Evening Observatory','Fern Archive','Quiet Harbor','Aurora Workshop','Moss Lantern',
                      'Paper Voyager','Signal Grove','Star Orchard','Tidal Library','Night Lantern','Dream Atlas')
            platforms = (LibraryPlatform.PCWIN, LibraryPlatform.NES, LibraryPlatform.GB,
                         LibraryPlatform.SNES, LibraryPlatform.N64, LibraryPlatform.MAC)
            for index, platform in enumerate(platforms):
                library = Library(name=('Evening Collection','Pocket Adventures','Small Worlds','Garden Arcade','Star Maps','Studio Shelf')[index], platform=platform)
                db.add(library); db.flush()
                for title in titles[index*2:index*2+2]:
                    db.add(Game(uuid=str(uuid.uuid4()), name=title, library_uuid=library.uuid,
                                summary='An original synthetic catalog entry for release screenshots.'))
            settings = db.execute(select(GlobalSettings)).scalars().one()
            settings.smtp_enabled = False; settings.oidc_enabled = False
            space = db.execute(select(ChatSpace).filter_by(visibility='household').order_by(ChatSpace.id)).scalars().first()
            if space is None:
                space = ChatSpace(name='Household', slug='release-household', visibility='household', created_by_user_id=user.id)
                db.add(space); db.flush()
            channel = db.execute(select(ChatChannel).filter_by(space_id=space.id, kind='channel').order_by(ChatChannel.display_order, ChatChannel.id)).scalars().first()
            if channel is None:
                channel = ChatChannel(name='The lounge', slug='release-lounge', space_id=space.id, kind='channel', created_by_user_id=user.id)
                db.add(channel); db.flush()
            db.flush()
            for person in (user, peer):
                if db.execute(select(ChatSpaceMember).filter_by(space_id=space.id,user_id=person.id)).scalars().first() is None:
                    db.add(ChatSpaceMember(space_id=space.id,user_id=person.id,role='owner' if person is user else 'member'))
                if db.execute(select(ChatChannelMember).filter_by(channel_id=channel.id,user_id=person.id)).scalars().first() is None:
                    db.add(ChatChannelMember(channel_id=channel.id,user_id=person.id))
            for person, body in ((user,'The evening collection is ready.'),(peer,'Pick a room and make it yours.'),
                                 (user,'The new artwork keeps every shelf feeling at home.')):
                db.add(ChatMessage(channel_id=channel.id,user_id=person.id,body=body))
            db.commit()
            return {'username':user.name,'games':len(existing)+len(titles),'chat_message':'The evening collection is ready.'}
    finally:
        engine.dispose()


def urllib_url(parsed):
    import urllib.parse
    return urllib.parse.urlunsplit(parsed).replace('postgresql://','postgresql+psycopg2://',1)


def browser_review(base, username, password, output, report, room_fixture=None):
    sys.path.insert(0, str(ROOT/'scripts'))
    import capture_common as common
    import capture_docs_media as media
    from dataclasses import replace
    from playwright.sync_api import sync_playwright
    common.BASE = base; media.BASE = base
    media.SHOT_DIR = output/'screenshots'; media.SHOT_DIR.mkdir()
    media.README_ASSETS = output/'readme'; media.README_ASSETS.mkdir()
    themes = output/'themes'; themes.mkdir()
    with sync_playwright() as engine:
        # Explicit CPU renderer for trusted, disposable CI content. Never infer
        # desktop/headset GPU performance from this profile.
        browser = engine.chromium.launch(headless=True,args=['--enable-unsafe-swiftshader'])
        context = browser.new_context(viewport={'width':1600,'height':900},color_scheme='light')
        common.block_streams(context)
        page = context.new_page()
        page.set_default_timeout(20_000)
        page.set_default_navigation_timeout(30_000)
        failed_assets = set()
        page.on('response', lambda response: failed_assets.add(response.url.split('?',1)[0].removeprefix(base))
                if response.status >= 400 and response.url.startswith(base+'/static/') else None)
        try:
            capture_checkpoint(output,report,'real_login')
            page.goto(base+'/login',wait_until='domcontentloaded')
            name = page.locator('#username') if page.locator('#username').count() else page.get_by_label('Username',exact=True)
            field = page.locator('#password') if page.locator('#password').count() else page.get_by_label('Password',exact=True)
            name.fill(username); field.fill(password); field.press('Enter')
            page.wait_for_function("() => location.pathname !== '/login'")
            page.goto(base+'/library',wait_until='domcontentloaded')
            page.wait_for_function("() => document.querySelectorAll('a[href*=\"/game_details/\"]').length >= 10")
            if page.locator('html').get_attribute('data-theme') != 'default':
                raise ProbeFailure('release_visual_default_theme_not_selected')
            if 'dark' not in page.evaluate("getComputedStyle(document.documentElement).colorScheme"):
                raise ProbeFailure('release_visual_default_not_dark_with_light_os')
            report['default_dark_with_light_os'] = True
            selected = [shot for shot in media.SHOTS if shot.readme]
            def chat(page):
                media.prep_chat(page)
                page.locator('button.od-chat-channel').filter(has_text='The lounge').click()
                page.get_by_text('The evening collection is ready.',exact=True).first.wait_for(state='visible')
                report['populated_chat_visible'] = True
            selected = [replace(shot,prepare=chat) if shot.name=='chat-channels' else shot for shot in selected]
            capture_checkpoint(output,report,'populated_readme_capture')
            failures = media.capture(page,selected)
            if failures or not report.get('populated_chat_visible'):
                raise ProbeFailure('release_visual_readme_capture_failed')
            media.README_ASSETS.joinpath('hero-banner.png').write_bytes(media.README_ASSETS.joinpath('screenshot-library.png').read_bytes())
            page.goto(base+'/library',wait_until='domcontentloaded')
            media.prep_preferences(page)
            page.locator('[data-theme-preview]').first.wait_for(state='visible')
            slugs = page.locator('[data-theme-preview]').evaluate_all('(buttons)=>buttons.map(button=>button.dataset.themePreview)')
            if not 8 <= len(set(slugs)) <= 16: raise ProbeFailure('release_visual_theme_cards_missing')
            page.get_by_role('button',name='Close preferences',exact=True).click()
            checked = []
            for raw in slugs:
                slug = capture_slug(raw)
                capture_checkpoint(output,report,'theme_'+slug)
                page.goto(base+'/library',wait_until='domcontentloaded')
                media.prep_preferences(page)
                page.locator('[data-theme-preview="'+slug+'"]').click()
                with page.expect_navigation(wait_until='domcontentloaded'):
                    page.get_by_role('button',name='Save changes',exact=True).click()
                page.goto(base+'/library',wait_until='domcontentloaded')
                page.wait_for_function('(slug)=>document.documentElement.dataset.theme===slug',arg=slug)
                page.wait_for_function("() => document.querySelectorAll('a[href*=\"/game_details/\"]').length >= 10")
                page.wait_for_timeout(1200)
                if not common.page_is_healthy(page)[0]: raise ProbeFailure('release_visual_theme_page_unhealthy')
                if not page.evaluate('(slug)=>Array.from(document.images).some(image=>image.src.includes("_"+slug+"_t2.jpg"))',slug):
                    raise ProbeFailure('release_visual_member_cover_theme_mismatch')
                if not page.evaluate('(slug)=>Array.from(document.images).some(image=>image.src.includes("/themes/"+slug+"/avatars/fox.svg"))',slug):
                    raise ProbeFailure('release_visual_member_avatar_theme_mismatch')
                page.screenshot(path=str(themes/(slug+'.png')))
                checked.append(slug)
            if failed_assets:
                report['failed_asset_paths'] = sorted(failed_assets)[:24]
                raise ProbeFailure('release_visual_missing_static_assets')
            report['themes_verified'] = checked
            from library_room_review import review_library_room
            try:
                review_library_room(page, output, report, room_fixture)
            except Exception:
                try:
                    report['room_failure_projection'] = page.evaluate('''() => ({
                      onVrPage: location.pathname==='/vr',
                      canvasPresent: !!document.querySelector('.od-library-room__canvas'),
                      controlsPresent: !!document.querySelector('[aria-label="Room stations"]'),
                      gamePanelPresent: !!document.querySelector('.od-moonfall'),
                      renderFallback: document.body.textContent.includes('This browser could not open the 3D room.'),
                      roomExpanded: document.querySelector('.od-library-room__header button')?.getAttribute('aria-expanded')==='true'
                    })''')
                    page.screenshot(path=str(output/'room-failure.png'),timeout=15_000)
                except Exception:
                    report['room_failure_capture_unavailable'] = True
                raise
        finally:
            context.close(); browser.close()


def run():
    require_capture_ci(ROOT,os.environ,sys.platform,getattr(os,'geteuid',lambda:-1)())
    work = Path(os.environ['RUNNER_TEMP']).resolve(strict=True)/('release-visual-'+os.environ['GITHUB_RUN_ID'])
    work.mkdir(mode=0o700)
    output = ROOT/'.artifacts/release-visual'; output.mkdir(parents=True)
    report = {'status':'failed','version':(ROOT/'VERSION').read_text(encoding='ascii').strip(),'phase':'backend_start',
              'source_sha':os.environ.get('GITHUB_SHA',''), 'run_id':os.environ.get('GITHUB_RUN_ID','')}
    fixture = None
    try:
        fixture = ConnectedServer.open(ROOT,work,report)
        password = secrets.token_urlsafe(40)
        safe_ci = {key:os.environ[key] for key in ('GITHUB_ACTIONS','RUNNER_OS','GITHUB_REPOSITORY','GITHUB_RUN_ID','RELEASE_VISUAL_ALLOWED')}
        result = subprocess.run([sys.executable,str(Path(__file__).resolve()),'--seed-owned'],cwd=ROOT,
            env={**fixture.api.env,**safe_ci,'ONEIRODEX_CI_DATABASE_MARKER':fixture.marker},
            input=json.dumps({'user_id':fixture.private_data['ids']['adult']['user_id'],'password':password}).encode(),
            capture_output=True,timeout=120)
        if result.returncode or len(result.stdout)>8192: raise ProbeFailure('release_visual_seed_failed')
        data = json.loads(result.stdout)
        report['seeded_games'] = data['games']
        browser_review(fixture.private_data['base_url'],data['username'],password,output,report,fixture)
        report['status'] = 'passed'; report['phase'] = 'complete'
    except Exception as error:
        report['code'] = str(error) if isinstance(error,ProbeFailure) else type(error).__name__
    finally:
        if fixture is not None:
            try: fixture.close()
            except Exception:
                report['status']='failed'; report['cleanup_error']='release_visual_backend_cleanup_failed'
        report['files'] = [{'path':str(path.relative_to(output)).replace('\\','/'),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
                           for path in output.rglob('*.png')]
        (output/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(report,indent=2))
    return 0 if report['status']=='passed' else 1


if __name__ == '__main__':
    if sys.argv[1:] == ['--seed-owned']:
        try: print(json.dumps(seed_owned(json.loads(sys.stdin.buffer.read(2048)))))
        except Exception: sys.exit(1)
    elif sys.argv[1:] == ['--run']: sys.exit(run())
    else: sys.exit(2)
