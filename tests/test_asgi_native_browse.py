from __future__ import annotations

import asyncio
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from flask import Flask
from flask_login import LoginManager

import asgi
from oneirodex.runtime_native import (
    acquire_status,
    acquire_actions,
    social_reads,
    game_reads,
    filter_reads,
    playtime,
    related_media,
    saved_filters,
    batch_favorite,
    batch_status,
    batch_wishlist,
    batch_refresh,
    member_game_state,
    favorites,
    member_meta,
    vr_reads,
    social_writes,
    admin_pilot,
    browse,
    oidc_status,
    auth_demo,
    remote_play_status,
    settings_module_status,
    library_health,
    game_health,
    quality_profiles,
    status_reads,
    device_status,
    ai_status,
    library_platforms,
    library_reads,
    arr_status,
    discover_reads,
    account_summary,
    account_preferences,
    locale as locale_routes,
    account_stock_avatar,
    account_tokens,
    account_avatar_upload,
    account_password,
    loading_icon_admin,
    client_reads,
    announcements,
    news_feeds,
    collection_reads,
    wishlist,
    notifications,
    chat_emoji_read,
    chat_reads,
    layouts,
    wanted_updates,
    updates_reads,
    updates_scan,
    release_calendar,
    ownership_providers,
    ownership_actions,
    game_servers as game_server_routes,
    emulator_mutations as emulator_mutation_routes,
    game_mods as game_mod_routes,
    scan_unmatched_reads as unmatched_reads,
    scan_unmatched_mutations as unmatched_mutations,
    scan_unmatched_feedback as unmatched_feedback,
    library_tools as native_library_tools,
    library_tools_mutations as native_library_tools_mutations,
    library_admin_mutations as native_library_admin_mutations,
    game_delete_mutations as native_game_delete_mutations,
    scan_job_reads as native_scan_job_reads,
    admin_newsletters as native_admin_newsletters,
    igdb_availability as native_igdb_availability,
    igdb_company_role as native_igdb_company_role,
    storage_hardlinks as native_storage_hardlinks,
    malware_scan_mutation as native_malware_scan_mutation,
    auth_confirmation as native_auth_confirmation,
    auth_login as native_auth_login,
    auth_form_posts as native_auth_form_posts,
    auth_logout as native_auth_logout,
    auth_pages as native_auth_pages,
    setup_pages as native_setup_pages,
    setup_transition as native_setup_transition,
    auth_registration as native_auth_registration,
    password_reset_confirm as native_password_reset_confirm,
    admin_server_settings as native_admin_server_settings,
    admin_ops_reads as native_admin_ops_reads,
    scan_job_mutations as native_scan_job_mutations,
    support_reads as native_support_reads,
    theme_fonts_read as native_theme_fonts_read,
    provider_catalog_reads as native_provider_catalog_reads,
    integration_settings as native_integration_settings,
    ownership_admin_reads as native_ownership_admin_reads,
    artwork_provider_search as native_artwork_provider_search,
    artwork_apply_mutation as native_artwork_apply_mutation,
    patch_catalog_routes as native_patch_catalog,
    download_request_reads as native_download_request_reads,
    manual_identify_reads as native_manual_identify_reads,
    manual_identify_mutations as native_manual_identify_mutations,
    retroachievements_settings as native_retroachievements_settings,
    admin_policy_settings as native_admin_policy_settings,
    launcher_import_reads as native_launcher_import_reads,
    download_mutations as native_download_mutations,
    support_mutations as native_support_mutations,
    launcher_import_mutations as native_launcher_import_mutations,
    admin_attract_mode as native_admin_attract_mode,
    admin_features as native_admin_features,
    admin_scan_filters as native_admin_scan_filters,
    admin_plugins_read as native_admin_plugins_read,
    integrations_inventory as native_integrations_inventory,
    library_tools_manual_identify as native_manual_identify,
    emulator_reads,
    system_path_check,
    system_file_types,
)
from oneirodex.runtime_native.session_compat import (
    dump_session_cookie, generate_csrf_token, load_session_cookie,
)


class FakeBrowseData:
    def query(self, args, user):
        assert user.id == 7
        assert args.get('page', 1, type=int) == 3
        return object()

    def payload(self, _result):
        return {'games': [], 'total': 0, 'pages': 0, 'current_page': 3}


class FakeAcquireStatusData:
    def status(self, user):
        assert user.id == 7
        return {'enabled': True, 'native_ready': True, 'can_send': False}


class FakeAcquireActionData:
    def __init__(self):
        self.calls = []
        self.arr_on = True
        self.debrid_on = True

    def arr_enabled(self, *, config=None):
        return self.arr_on

    def debrid_enabled(self):
        return self.debrid_on

    def search(self, query, *, current_label):
        self.calls.append(('search', query, current_label))
        return {'q': query, 'results': [{'title': 'Fixture result'}], 'warnings': []}

    def validate_url(self, url):
        self.calls.append(('validate', url))
        return True, url

    def send(self, url, provider):
        self.calls.append(('send', url, provider))
        return {'queued': True}

    def safe_error(self, _exc, *, indexer=False):
        return 'Safe provider failure'


class FakeSocialReadData:
    def __init__(self):
        self.activity_calls = []

    def activity(self, user, *, limit, friends_only):
        self.activity_calls.append((user.id, limit, friends_only))
        return {
            'activity': [{'game_name': 'Fixture'}],
            'now_playing': [],
            'friends_only': friends_only,
        }

    def status(self, user):
        assert user.id == 7
        return {
            'community_chat_url': None, 'community_chat_label': None,
            'friend_count': 2, 'pending_incoming': 1,
            'now_playing': [], 'presence': [],
        }

    def friends(self, user):
        assert user.id == 7
        return {'friends': [{'id': 9, 'status': 'accepted', 'direction': 'incoming'}]}

    def profile(self, user, user_id, flask_app):
        return None if user_id == 404 else {
            'user': {'id': user_id, 'name': 'Fixture'},
            'presence': {'state': 'offline'},
            'is_self': user_id == user.id,
            'is_friend': user_id == 9,
            'total_seconds': 120,
            'recent_games': [],
        }

    def profile_compare(self, user, user_id, other_id):
        if user.id not in {user_id, other_id}:
            return 'Forbidden', 403
        return {
            'left': {'id': user_id, 'name': 'Fixture'},
            'right': {'id': other_id, 'name': 'Friend'},
            'shared_games': [],
        }, 200


class FakeGameReadData:
    def __init__(self):
        self.calls = []
        self.allowed = True
        self.assists_on = True
        self.searches = []

    def search(self, args, user):
        self.searches.append((user.id, args.get('query'), args.get('genre')))
        return [{'id': 1, 'uuid': 'game-1', 'name': 'Fixture game'}]

    def next_custom_igdb_id(self):
        self.calls.append(('next_custom_igdb_id',))
        return 2000000421

    def library(self, library_uuid):
        self.calls.append(('library', library_uuid))
        return SimpleNamespace(uuid=library_uuid, name='Target')

    def can_access_library(self, user, library):
        self.calls.append(('library_access', user.id, library.uuid))
        return self.allowed

    def move_game(self, game, library, user):
        self.calls.append(('move_game', game.uuid, library.uuid, user.id))
        return {'message': f'Game moved to {library.name}'}

    def game(self, game_uuid):
        self.calls.append(('game', game_uuid))
        return SimpleNamespace(uuid=game_uuid) if game_uuid != 'missing' else None

    def can_access(self, user, game):
        self.calls.append(('access', user.id, game.uuid))
        return self.allowed

    def set_input_family(self, game, input_family):
        self.calls.append(('set_input_family', game.uuid, input_family))
        return {
            'uuid': game.uuid, 'input_family': input_family,
            'families': ['joystick', 'spinner', 'lightgun', 'trackball'],
        }

    def details(self, game, user):
        self.calls.append(('details', user.id, game.uuid))
        return {'uuid': game.uuid, 'name': 'Fixture game'}

    def more_from(self, game, user):
        self.calls.append(('more_from', user.id, game.uuid))
        return {'sections': []}

    def editions(self, game, user):
        self.calls.append(('editions', user.id, game.uuid))
        return {'uuid': game.uuid, 'editions': [], 'system_count': 0}

    def versions(self, game, user):
        self.calls.append(('versions', user.id, game.uuid))
        return {'game_uuid': game.uuid, 'versions': [{'uuid': 'version-1'}]}

    def freshness(self, game, user):
        self.calls.append(('freshness', user.id, game.uuid))
        return {'game_uuid': game.uuid, 'status': 'unknown'}

    def screenshots(self, game_uuid, user):
        self.calls.append(('screenshots', user.id, game_uuid))
        return ['/static/library/images/fixture-shot.webp']

    def assists_enabled(self, *, config=None):
        self.calls.append(('assists_enabled',))
        return self.assists_on

    def assists(self, game, user, *, config=None, package_root=None):
        self.calls.append(('assists', user.id, game.uuid))
        return {'enabled': True, 'pack': {'title': 'Fixture'}, 'overlay_links': []}

    def save_assists(self, game, body, *, config=None, package_root=None):
        self.calls.append(('save_assists', game.uuid, body.title))
        return {'pack': {'title': body.title or game.name}, 'overlay_links': []}

    def images(self, game_uuid, user, *, raw_kind):
        self.calls.append(('images', user.id, game_uuid, raw_kind))
        if raw_kind not in {'all', 'cover', 'screenshot'}:
            raise ValueError('Invalid image kind')
        return {
            'game_uuid': game_uuid, 'kind_filter': raw_kind,
            'allowed_kinds': ['cover', 'screenshot'],
            'images': [], 'count': 0,
        }

    def check_freshness(self, game, user):
        self.calls.append(('check_freshness', user.id, game.uuid))
        return {'status': 'current'}

    def rollback(self):
        self.calls.append(('rollback',))

class FakeFilterReadData:
    def __init__(self):
        self.calls = []

    def bundle(self, user):
        self.calls.append(('bundle', user.id))
        return {
            'libraries': [{'uuid': 'library-1', 'name': 'Fixture'}],
            'libraryPlatforms': [], 'igdbPlatforms': [], 'genres': [],
            'themes': [], 'gameModes': [], 'playerPerspectives': [],
            'ownershipStores': [],
        }

    def library_platforms(self, user, *, include_completion):
        self.calls.append(('platforms', user.id, include_completion))
        return [{'id': 'SNES', 'name': 'Super Nintendo', 'game_count': 3}]

    def taxonomy(self, name):
        self.calls.append(('taxonomy', name))
        return [{'id': 1, 'name': name.title()}]


class FakePlaytimeData:
    def __init__(self):
        self.calls = []

    def start(self, user, body):
        self.calls.append(('start', user.id, body.game_uuid, body.client))
        return SimpleNamespace(to_dict=lambda: {'id': 40, 'status': 'active'})

    def session(self, user, session_id):
        self.calls.append(('session', user.id, session_id))
        if session_id != 40:
            return None
        return SimpleNamespace(to_dict=lambda: {'id': 40, 'status': 'active'})

    def heartbeat(self, session):
        self.calls.append(('heartbeat',))
        return session

    def stop(self, session):
        self.calls.append(('stop',))
        return session

    def me(self, user):
        self.calls.append(('me', user.id))
        return {'total_seconds': 120, 'games': [{'game_uuid': 'game-1'}]}

    def game(self, user, game_uuid):
        self.calls.append(('game', user.id, game_uuid))
        if game_uuid == 'missing':
            return None, None
        return None, {
            'user_id': user.id, 'game_uuid': game_uuid, 'total_seconds': 0,
            'session_count': 0, 'last_played_at': None,
        }

    def share_svg(self, user, game_uuid):
        self.calls.append(('share_svg', user.id, game_uuid))
        if game_uuid == 'missing':
            return None, ('Game not found', 'not_found')
        return '<svg xmlns="http://www.w3.org/2000/svg"></svg>', None


class FakeRelatedMediaData:
    def __init__(self):
        self.calls = []
        self.allowed = True

    def game(self, game_uuid):
        self.calls.append(('game', game_uuid))
        return SimpleNamespace(uuid=game_uuid) if game_uuid != 'missing' else None

    def can_access(self, user, game):
        self.calls.append(('access', user.id, game.uuid))
        return self.allowed

    def items(self, game_uuid):
        self.calls.append(('items', game_uuid))
        return [{'id': 3, 'media_kind': 'film', 'title': 'Fixture adaptation'}]

    def create(self, game_uuid, user, payload):
        self.calls.append(('create', game_uuid, user.id, payload))
        return {'id': 9, **payload}

    def delete(self, game_uuid, item_id):
        self.calls.append(('delete', game_uuid, item_id))
        return item_id == 9


class FakeSavedFilterData:
    def __init__(self):
        self.rows = {1: self._row(1, 'Favorite RPGs')}
        self.calls = []

    @staticmethod
    def _row(filter_id, name, tree=None, is_collection=False):
        row = SimpleNamespace(
            id=filter_id, name=name,
            tree=tree or {'field': 'is_vr', 'value': True},
            is_collection=is_collection,
        )
        row.to_dict = lambda: {
            'id': row.id, 'name': row.name, 'tree': row.tree,
            'is_collection': row.is_collection,
        }
        return row

    def list(self, user):
        self.calls.append(('list', user.id))
        return list(self.rows.values())

    def get(self, user, filter_id):
        self.calls.append(('get', user.id, filter_id))
        return self.rows.get(filter_id) if user.id == 7 else None

    def name_exists(self, user, name, *, excluding=None):
        return any(row.name == name and row.id != excluding for row in self.rows.values())

    def create(self, user, *, name, tree, is_collection):
        self.calls.append(('create', user.id, name, tree, is_collection))
        row = self._row(2, name, tree, is_collection)
        self.rows[row.id] = row
        return row

    def save(self, row=None):
        self.calls.append(('save', getattr(row, 'id', None)))

    def delete(self, row):
        self.calls.append(('delete', row.id))
        self.rows.pop(row.id, None)

    def rollback(self):
        self.calls.append(('rollback',))

    def preview(self, user, tree, limit):
        from oneirodex.utils.filter_tree import parse_filter_tree

        parsed = parse_filter_tree(tree)
        self.calls.append(('preview', user.id, parsed, limit))
        return {'count': 4, 'sample': [{'uuid': 'game-1', 'name': 'Fixture'}] if limit else []}


class FakeBatchFavoriteData:
    def __init__(self):
        self.calls = []
        self.forbidden = {'blocked'}
        self.commit_fails = False

    def state(self, user, uuids):
        self.calls.append(('state', user.id, list(uuids)))
        games = {
            uuid: SimpleNamespace(uuid=uuid)
            for uuid in uuids if uuid != 'missing'
        }
        return games, {'already'}

    def can_access(self, user, game):
        return game.uuid not in self.forbidden

    def set_favorite(self, user, game, favorite):
        self.calls.append(('set', user.id, game.uuid, favorite))

    def commit(self):
        self.calls.append(('commit',))
        if self.commit_fails:
            raise RuntimeError('private db info')

    def rollback(self):
        self.calls.append(('rollback',))


class FakeBatchStatusData:
    def __init__(self):
        self.calls = []
        self.forbidden = {'blocked'}

    def state(self, user, uuids):
        self.calls.append(('state', user.id, list(uuids)))
        return (
            {uuid: SimpleNamespace(uuid=uuid) for uuid in uuids if uuid != 'missing'},
            {'already': 'completed', 'game-a': 'unplayed'},
        )

    def can_access(self, user, game):
        return game.uuid not in self.forbidden

    def write(self, user_id, uuid, *, current, status, now):
        self.calls.append(('write', user_id, uuid, current, status, now.tzinfo is not None))

    def status_info(self, status):
        return {'status': status}

    def commit(self):
        self.calls.append(('commit',))

    def rollback(self):
        self.calls.append(('rollback',))


class FakeBatchWishlistData:
    def __init__(self):
        self.calls = []
        self.pending = [SimpleNamespace(
            id=11, title='Already pending', linked_game_uuid='pending', status='pending',
        )]

    def can_request_games(self, user):
        return user.role != 'child'

    def state(self, user, uuids):
        self.calls.append(('state', user.id, list(uuids)))
        games = {
            uuid: SimpleNamespace(uuid=uuid, name=uuid.replace('-', ' ').title())
            for uuid in uuids if uuid != 'missing'
        }
        return games, list(self.pending)

    def can_access(self, user, game):
        return game.uuid != 'blocked'

    def create(self, user_id, title, uuid):
        self.calls.append(('create', user_id, title, uuid))
        return SimpleNamespace(id=22, title=title[:255], status='pending')

    def delete(self, row):
        self.calls.append(('delete', row.id))

    def commit(self):
        self.calls.append(('commit',))

    def rollback(self):
        self.calls.append(('rollback',))

    def log_created(self, count, *, audit_user=None):
        self.calls.append(('log', count, audit_user))


class FakeBatchRefreshData:
    def __init__(self):
        self.calls = []

    def state(self, uuids):
        self.calls.append(('state', list(uuids)))
        now = datetime.now(timezone.utc)
        return {
            uuid: SimpleNamespace(
                uuid=uuid, name=uuid.title(), igdb_id=42,
                freshness_checked_at=(now if uuid == 'fresh' else now - timedelta(days=2)),
                freshness_status='known', updates=[], extras=[], urls=[],
            )
            for uuid in uuids if uuid != 'missing'
        }

    def admin_games(self, _limit, library_uuid=None, *, fetch_n=None):
        self.calls.append(('admin_games', library_uuid, fetch_n))
        now = datetime.now(timezone.utc)
        return [SimpleNamespace(
            uuid='stale', name='Stale',
            freshness_checked_at=now - timedelta(days=2), freshness_status='known',
            updates=[], extras=[], urls=[],
        )]

    def can_access(self, user, game):
        return game.uuid != 'blocked'

    def check_freshness(self, game):
        self.calls.append(('freshness', game.uuid))
        return {'status': 'current', 'confidence': 0.8}

    def enqueue_images(self, app, uuid):
        self.calls.append(('enqueue', uuid))

    def commit(self):
        self.calls.append(('commit',))

    def rollback(self):
        self.calls.append(('rollback',))


class FakeMemberGameStateData:
    def __init__(self):
        self.calls = []
        self.favorites = set()
        self.statuses = {'game-a': 'unplayed'}

    def game(self, uuid):
        self.calls.append(('game', uuid))
        return None if uuid == 'missing' else SimpleNamespace(uuid=uuid)

    def can_access(self, user, game):
        return game.uuid != 'blocked'

    def is_favorite(self, user, game):
        return game.uuid in self.favorites

    def set_favorite(self, user, game, favorite):
        self.calls.append(('favorite', user.id, game.uuid, favorite))
        if favorite:
            self.favorites.add(game.uuid)
        else:
            self.favorites.discard(game.uuid)

    def status(self, user_id, game_uuid):
        return self.statuses.get(game_uuid)

    def write_status(self, user_id, game_uuid, status):
        self.calls.append(('status', user_id, game_uuid, status))
        if status:
            self.statuses[game_uuid] = status
        else:
            self.statuses.pop(game_uuid, None)

    def commit(self):
        self.calls.append(('commit',))


class FakeFavoritesData:
    def __init__(self):
        self.calls = []

    def payload(self, user, args):
        self.calls.append((user.id, list(args.items(multi=True))))
        return {
            'games': [], 'total': 0, 'pages': 0,
            'current_page': args.get('page', 1, type=int) or 1,
        }


class FakeMemberMetaData:
    def username_exists(self, username):
        return username.lower() == 'taken'

    def icon_packs(self, user, *, static_url_path='/static'):
        return {
            'packs': [{
                'id': 'outline',
                'css_url': f'{static_url_path}/library/icon-themes/outline/pack.css',
            }],
            'current': 'outline',
        }


class FakeVrReadData:
    def enabled(self, flask_app):
        return flask_app.config.get('ENABLE_VR_BROWSE') == '1'

    def catalog(self, user, *, page, per_page, compatibility):
        return {
            'page': page, 'pages': 1, 'total': 1,
            'games': [{'uuid': 'vr-1', 'name': 'Headset title', 'vr_compat': compatibility or 'native_vr'}],
        }

    def detail(self, user, game_uuid):
        if game_uuid == 'blocked':
            return None, 'forbidden'
        if game_uuid == 'missing':
            return None, 'not_found'
        return {
            'uuid': game_uuid, 'name': 'Headset title', 'vr_profiles': [],
        }, None

    def accessible_game(self, user, game_uuid):
        if game_uuid == 'missing':
            return None, 'not_found'
        if game_uuid == 'blocked':
            return None, 'forbidden'
        return SimpleNamespace(uuid=game_uuid, vr_compat=None, vr_profiles=[]), None

    def profiles_payload(self, game):
        return {
            'uuid': game.uuid, 'vr_profiles': [], 'vr_compat': 'native_vr',
            'vr_compat_stored': game.vr_compat, 'kinds': ['native', 'injector', 'flat'],
        }

    def save_profile(self, game, kind, body):
        return SimpleNamespace(to_dict=lambda: {
            'kind': kind, 'runtime': body.runtime, 'profile_url': body.profile_url,
            'notes': body.notes, 'source': body.source,
        })

    def delete_profile(self, game, kind):
        return kind == 'injector'

    def save_compat(self, game, value):
        return {
            'uuid': game.uuid, 'vr_compat': value,
            'vr_compat_stored': value, 'is_vr': value in {'native_vr', 'injector_profile'},
        }

    def rollback(self):
        pass


class FakeSocialWriteData:
    def __init__(self):
        self.calls = []

    def request(self, user, payload):
        self.calls.append(('request', user.id, payload))
        return {
            'sent': False,
            'message': 'If that username exists, a friend request was sent.',
        }, 200, None

    def reject(self, user, friendship_id):
        self.calls.append(('reject', user.id, friendship_id))
        return None, None

    def block(self, user, friendship_id):
        self.calls.append(('block', user.id, friendship_id))
        return {'friendship': {'id': friendship_id, 'status': 'blocked'}}, None

    def accept(self, user, friendship_id):
        self.calls.append(('accept', user.id, friendship_id))
        return {'friendship': {'id': friendship_id, 'status': 'accepted'}}, None

    def delete(self, user, friendship_id):
        self.calls.append(('delete', user.id, friendship_id))
        return None, None


class FakeOidcStatusData:
    def report(self):
        return {'ready': False, 'live_verified': False, 'message': 'Not configured'}


class FakeRemotePlayStatusData:
    def status(self, *, config=None):
        return {'enabled': False, 'configured': False}


class FakeSettingsModuleStatusData:
    def status(self, *, config=None):
        return {'arr': {'on': False, 'label': 'Off'}, 'ai': {'on': False, 'label': 'Off'}}


class FakeLibraryHealthData:
    def summarize(self, *, limit, library_uuid):
        assert limit == 12
        assert library_uuid == 'library-a'
        return {'count': 0, 'average_score': None, 'library_uuid': 'library-a'}


class FakeGameHealthData:
    def find(self, game_uuid):
        assert game_uuid == 'game-123'
        return SimpleNamespace(uuid='game-123')

    def can_access(self, user, game):
        return user.id == 7 and game.uuid == 'game-123'

    def score(self, game):
        return {'uuid': game.uuid, 'score': 72, 'grade': 'fair'}


class FakeQualityProfilesData:
    def list(self):
        return {'version': 2, 'active_id': 'balanced', 'profiles': []}

    def set_active(self, profile_id):
        return {'version': 2, 'active_id': profile_id, 'profiles': []}

    def score(self, *, title, size_bytes, profile_id):
        return {'title': title, 'size_bytes': size_bytes, 'profile_id': profile_id}


class FakeSimpleStatusData:
    def __init__(self, payload):
        self.payload = payload

    def status(self, *, config=None):
        return self.payload


class FakeProbeStatusData:
    def __init__(self, payload):
        self.payload = payload
        self.probes = []

    def status(self, *, probe, config=None):
        self.probes.append(probe)
        return {**self.payload, 'probe_requested': probe}

    def read_config(self, *, config=None):
        return {'enabled': False, 'secret_configured': True}

    def save_config(self, payload, *, config=None):
        return {'enabled': payload.get('enabled', False), 'secret_configured': True}


class FakeAiStatusData:
    def status(self, *, config=None):
        return {
            'enabled': True,
            'auto_apply_enabled': False,
            'reachable': False,
            'base_url': 'http://ollama.test:11434',
            'model': 'small-model',
            'error': 'Ollama unreachable',
        }

    def read_config(self, *, config=None):
        return {'enabled': False, 'ollama_model': 'small-model'}

    def save_config(self, payload, *, config=None):
        return {'enabled': payload.get('enabled', False), 'ollama_model': 'small-model'}

    def enabled(self, *, config=None):
        return True

    def unmatched_folder(self, _folder_id):
        return None

    def folder_platform(self, _library_uuid):
        return None

    def triage(self, name, platform, *, config=None):
        return {'query': name, 'platform': platform, 'suggestions': [{'title': 'Fixture'}]}

    def game_name_and_summary(self, game_uuid):
        return ('Fixture game', 'Fixture summary') if game_uuid == 'game-1' else None

    def notes(self, context, *, config=None):
        return {'game_name': context['game_name'], 'notes': 'Fixture note'}

    def auto_apply_enabled(self, *, config=None):
        return True

    def apply(self, game_uuid, title, *, config=None):
        return {'applied': True, 'unchanged': False, 'game_uuid': game_uuid, 'name': title}


class FakeLibraryPlatformsData:
    def platforms(self):
        return [
            SimpleNamespace(name='PC', value='Windows PC'),
            SimpleNamespace(name='NES', value='Nintendo Entertainment System'),
        ]


class FakeLibraryReadData:
    def __init__(self):
        self.calls = []
        self.watch_enabled = True

    def list_for_user(self, user):
        self.calls.append(('list', user.id))
        return [{'uuid': 'lib-1', 'name': 'Fixture library', 'game_count': 3}]

    def can_access(self, user, library_uuid):
        self.calls.append(('access', user.id, library_uuid))
        return library_uuid != 'blocked'

    def library(self, library_uuid):
        self.calls.append(('library', library_uuid))
        return None if library_uuid == 'missing' else SimpleNamespace(uuid=library_uuid)

    def public_fields(self, library):
        return {'uuid': library.uuid, 'name': 'Fixture library'}

    def watch_fields(self, library):
        return {
            'uuid': library.uuid, 'name': 'Fixture library',
            'watch_enabled': self.watch_enabled,
            'watch_effective': bool(self.watch_enabled),
            'watch_global_enabled': True,
        }

    def update_watch(self, library, value):
        self.calls.append(('update_watch', library.uuid, value))
        self.watch_enabled = value

    def reorder(self, order):
        self.calls.append(('reorder', list(order)))

    def rollback(self):
        self.calls.append(('rollback',))

    def batch_edit(self, payload, user):
        self.calls.append(('batch_edit', user.id, dict(payload)))
        return {
            'ok': True, 'error': None, 'error_code': None, 'success': True,
            'updated': 1, 'skipped': 0, 'failed': 0, 'count': 1,
            'results': [{'uuid': 'lib-1', 'status': 'updated'}],
        }, 200


class FakeArrStatusData:
    def status(self, *, config=None):
        return {
            'enabled': True,
            'module': 'arr',
            'status': 'ready',
            'connectors': [{'id': 'native_indexers', 'configured': True}],
            'hardlink_pipeline_enabled': True,
            'hardlink_helpers_enabled': True,
            'hardlink_apply_allowed': False,
            'indexer_warnings': [],
        }


class FakeDiscoverReadsData:
    def __init__(self):
        self.saved = []

    def sections(self, user):
        assert user.id == 7
        return {'sections': [{'id': 'recent', 'games': []}], 'feed_token': 'feed-123'}

    def row(self, user, identifier, *, offset, feed_token, **kwargs):
        assert user.id == 7
        assert (identifier, offset, feed_token, kwargs) == ('recent', 5, 'feed-123', {})
        return {'identifier': identifier, 'offset': offset, 'games': []}

    def zone(self, user, slug):
        assert user.id == 7
        assert slug == 'by-era'
        return {'slug': slug, 'sections': []}

    def genre_hub(self, user, genre):
        assert user.id == 7
        assert genre == 'Action/Adventure'
        return {'genre': genre, 'sections': []}

    def genre_by_id(self, genre_id):
        assert genre_id == 5
        return SimpleNamespace(id=5, name='Arcade')

    def surprise(self, user, genre, exclude):
        assert user.id == 7
        assert (genre.id, genre.name, exclude) == (5, 'Arcade', ['game-a', 'game-b'])
        return {'game': None, 'reason': 'no_games', 'genre': {'id': 5, 'name': 'Arcade'}, 'genres': []}

    def pins(self, user):
        assert user.id == 7
        return {'pins': ['recent'], 'hidden': [], 'max_pins': 3, 'available': ['recent']}

    def save_pins(self, user, payload):
        self.saved.append((user.id, dict(payload)))
        return {'pins': payload.get('pins', []), 'hidden': [], 'max_pins': 3, 'available': ['recent']}


class FakeAccountSummaryData:
    def summary(self, user, *, static_url=None, package_root=None):
        assert user.id == 7
        return {
            'username': 'member-seven',
            'email': 'member7@example.test',
            'role': 'user',
            'avatar_path': '/static/avatars/member.png',
            'avatar_url': '/static/avatars/member.png',
            'stock_avatars': [],
            'invite_quota': 3,
            'invites_used': 1,
            'invites_remaining': 2,
            'invites_unlimited': False,
            'smtp_enabled': False,
        }

    def invites(self, user, *, origin=None):
        assert user.id == 7
        return {
            'invites': [{
                'token': 'opaque-invite-token',
                'email': 'friend@example.test',
                'url': 'https://games.example.test/invite/opaque-invite-token',
                'created_at': None,
                'expires_at': None,
                'expired': False,
            }],
            'quota': 3,
            'remaining': 2,
            'unlimited': False,
            'smtp_enabled': False,
            'ttl_hours': 48,
            'site_url_configured': True,
        }

    def create(self, user, email, *, origin=None):
        assert user.id == 7
        return {
            'invite': {'token': 'created-invite', 'email': email},
            'emailed': False,
            'remaining': 1,
            'unlimited': False,
        }

    def delete(self, user, token):
        assert user.id == 7
        return {'revoked': token, 'remaining': 2}


class FakeAccountPreferencesData:
    def choices(self, user):
        assert user.id == 7
        return {
            'preferences': {'theme': 'default', 'tile_size': '50'},
            'choices': {'themes': [{'id': 'default'}]},
            'member_engine_choice': 'system',
            'is_admin': False,
        }

    def update(self, user, payload):
        assert user.id == 7
        return {'preferences': {'theme': 'default', **payload}}, 200


class FakeAccountStockAvatarData:
    def set_stock(self, avatar_id, user, _flask_app):
        assert user.id == 7
        return f'/static/avatars/{avatar_id}.svg', None

    def avatar_url(self, path):
        return path

    def commit(self):
        pass

    def rollback(self):
        pass


class FakeAccountTokensData:
    def list_for_user(self, user_id):
        assert user_id == 7
        return []

    def revoke(self, token_id, user_id):
        assert (token_id, user_id) == (19, 7)
        return True


class FakeAccountAvatarUploadData:
    def save(self, file, user, _flask_app):
        assert user.id == 7
        return f'library/images/avatars_users/{file.filename}', None

    def avatar_url(self, path):
        return '/' + path

    def commit(self):
        pass

    def rollback(self):
        pass


class FakeAccountPasswordData:
    def __init__(self):
        self.user = SimpleNamespace(
            id=7,
            password='OldPassword1!',
            password_hash='old-hash',
            check_password=lambda value: value == 'OldPassword1!',
            set_password=lambda value: None,
            get_id=lambda: '7:new-fingerprint',
        )

    def get_user(self, user_id):
        assert user_id == 7
        return self.user

    def commit(self):
        pass

    def rollback(self):
        pass


class FakeClientReadData:
    def capabilities(self, device_kind, token, user):
        assert user.id == 7
        assert token is None
        return {
            'device_kind': device_kind or 'companion',
            'allows': ['browse', 'browser_play', 'presence', 'social'],
            'denies': ['download', 'install', 'native_play', 'uninstall', 'update'],
        }

    def lifecycle(self, user_id):
        assert user_id == 7
        return {'records': [{'game_uuid': 'game-7', 'state': 'installed'}]}

    def save_lifecycle(self, user_id, records, *, replace=False):
        assert (user_id, records, replace) == (7, [], False)
        return {'records': []}

    def heartbeat(
        self, user_id, device_id, device_kind, device_name, client_version,
        user_agent, token, user,
    ):
        assert user_id == 7
        assert user.id == 7
        assert device_kind is None
        assert token is None
        return {'device_id': device_id, 'commands': []}

    def find_game(self, game_uuid):
        return None

    def can_access_game(self, _user, _game):
        return True

    def find_version(self, _game, _kind, _version_uuid):
        return None

    def enqueue(self, user_id, game_uuid, action, **kwargs):
        return {'id': 'command-outer', 'user_id': user_id, 'game_uuid': game_uuid, 'action': action}

    def claim(self, _user_id, *, limit=None):
        return []

    def acknowledge(self, _user_id, ids):
        return len(ids)

    def negative_acknowledge(self, _user_id, ids):
        return len(ids)


class FakeAnnouncementData:
    def __init__(self):
        self.include_drafts = []

    def list(self, *, include_drafts):
        self.include_drafts.append(include_drafts)
        return [{'id': 3, 'title': 'Fixture announcement'}]

    def create(self, *, title, body, published, author_user_id):
        assert (title, body, published, author_user_id) == (
            'Maintenance', 'Tonight', True, 7,
        )
        return {'id': 4, 'title': title, 'body': body, 'published': published}


class FakeOwnershipProviderData:
    def __init__(self):
        self.decisions = []

    def capabilities(self):
        return {
            'schema_version': 1,
            'providers': [{
                'id': 'steam', 'name': 'Steam',
                'policy_enabled': True, 'account_readiness': 'not_checked',
            }],
        }

    def connections(self, user):
        assert user.id == 7
        return {'connections': [{'store': 'steam', 'status': 'connected'}]}

    def summary(self, user):
        assert user.id == 7
        return {'connected': ['steam'], 'titles': 1}

    def titles(self, user, after_id, status):
        assert (user.id, after_id, status) == (7, 4, 'needs_review')
        return {'titles': [{'id': 5, 'name': 'Fixture title'}], 'next_after_id': None}

    def candidates(self, user, title_id):
        assert (user.id, title_id) == (7, 5)
        return {'title_id': 5, 'candidates': [{'game_uuid': 'visible-game'}]}

    def decide(self, user, title_id, expected_revision, game_uuid, *, undo):
        self.decisions.append((title_id, expected_revision, game_uuid, undo))
        if expected_revision != 2:
            from oneirodex.utils.ownership_review import ReviewError

            raise ReviewError('Ownership decision changed; refresh before retrying', 'conflict')
        return {
            'title_id': title_id, 'matched_game_uuid': game_uuid,
            'match_reviewed': True, 'match_revision': expected_revision + 1,
        }

    def rollback(self):
        self.decisions.append(('rollback',))

    def cancel_sync(self, user_id, store):
        assert (user_id, store) == (7, 'gog')
        return {'job': {'id': 8, 'store': store, 'cancel_requested': True}}, None


class FakeEmulatorReadData:
    def __init__(self):
        self.saved = []

    def all(self):
        return {'emulators': ['retroarch'], 'profiles': {'NES': 'nestopia'}}

    def platform(self, name):
        if name != 'NES':
            raise KeyError(name)
        return {
            'platform': name, 'emulators': ['nestopia'],
            'preferred': 'nestopia', 'defaults': ['nestopia'],
        }

    def profiles(self):
        return {'profiles': {'NES': 'nestopia'}, 'catalog': {'NES': ['nestopia']}}

    def save_profiles(self, profiles):
        self.saved.append(profiles)
        return {'profiles': profiles, 'catalog': {'NES': ['nestopia']}}

    def browser_player_settings(self):
        return {'engine': 'webretro', 'autoplay': False}

    def save_browser_player_settings(self, payload):
        self.saved.append(('browser', payload))
        return {'engine': payload.get('engine', 'webretro'), 'autoplay': False}


class FakePathAvailabilityData:
    def __init__(self):
        self.calls = []

    def allowed_bases(self, _app):
        return ['/allowed']

    def validate(self, path, bases, _logger=None):
        self.calls.append(('validate', path, bases))
        return (path.startswith('/allowed/'), 'Path is outside allowed roots')

    def exists(self, path):
        self.calls.append(('exists', path))
        return path == '/allowed/existing.bin'


class FakeSystemFileTypeData:
    def __init__(self):
        self.records = {'allowed': [{'id': 1, 'value': 'exe'}], 'ignored': []}
        self.calls = []

    def list(self, category):
        return self.records[category]

    def create(self, category, value):
        self.calls.append(('create', category, value))
        record = {'id': 2, 'value': value}
        self.records[category].append(record)
        return record

    def update(self, category, record_id, value):
        self.calls.append(('update', category, record_id, value))
        if record_id != 1:
            raise system_file_types.FileTypeMissing
        return {'id': record_id, 'value': value}

    def delete(self, category, record_id):
        self.calls.append(('delete', category, record_id))
        if record_id != 1:
            raise system_file_types.FileTypeMissing

    def rollback(self):
        self.calls.append(('rollback',))


class FakeNewsFeedData:
    def __init__(self):
        self.calls = []

    def gaming(self, *, limit):
        self.calls.append(('gaming', limit))
        return [{'title': 'Fixture headline'}], ['Example News']

    def sources(self):
        return ['Example News']

    def connected_stores(self, user_id):
        self.calls.append(('connected', user_id))
        return {'steam', 'epic'}

    def free_games(self, *, store, limit, connected_stores):
        self.calls.append(('free', store, limit, connected_stores))
        return [{'id': 'offer-1'}]

    def claim_assist(self, offer_id, user_id):
        self.calls.append(('claim', offer_id, user_id))
        if offer_id == 404:
            return None
        if offer_id == 409:
            return {'ok': False, 'error': 'Store is not connected'}
        return {'ok': True, 'claimed': True, 'offer_id': offer_id}


class FakeCollectionReadData:
    def list(self, user, *, admin_access):
        assert user.id == 7
        assert admin_access is False
        return {'collections': [{
            'uuid': 'collection-1', 'name': 'Fixture shelf',
            'can_edit': True, 'item_count': 1,
        }]}

    def detail(self, user, collection_uuid, *, admin_access):
        assert user.id == 7
        assert admin_access is False
        if collection_uuid == 'missing':
            return None, 404
        return {
            'uuid': collection_uuid,
            'name': 'Fixture shelf',
            'items': [{'game_uuid': 'game-1'}],
            'item_count': 1,
            'can_edit': True,
        }, 200

    def create(self, user, body):
        assert user.id == 7
        assert (body.name, body.description, body.is_public) == ('Shelf', 'About', True)
        return {'uuid': 'created-collection', 'name': body.name, 'item_count': 0}

    def update(self, user, collection_uuid, payload, *, admin_access):
        assert (user.id, collection_uuid, payload, admin_access) == (
            7, 'collection-1', {'name': 'Renamed'}, False,
        )
        return {'uuid': collection_uuid, 'name': 'Renamed'}, None

    def delete(self, user, collection_uuid, *, admin_access):
        assert (user.id, collection_uuid, admin_access) == (7, 'collection-1', False)
        return {'uuid': collection_uuid}, None

    def add_item(self, user, collection_uuid, game_uuid, *, admin_access):
        assert (user.id, collection_uuid, game_uuid, admin_access) == (
            7, 'collection-1', 'game-1', False,
        )
        return {'game_uuid': game_uuid}, None, 201

    def remove_item(self, user, collection_uuid, game_uuid, *, admin_access):
        assert (user.id, collection_uuid, game_uuid, admin_access) == (
            7, 'collection-1', 'game-1', False,
        )
        return {'game_uuid': game_uuid}, None

    def reorder(self, user, collection_uuid, game_uuids, *, admin_access):
        assert (user.id, collection_uuid, game_uuids, admin_access) == (
            7, 'collection-1', ['game-1'], False,
        )
        return {'uuid': collection_uuid, 'items': [{'game_uuid': 'game-1'}]}, None


class FakeWishlistData:
    def list(self, user, *, include_all):
        assert user.id == 7
        return [{'id': 23, 'title': 'Fixture request', 'all': include_all}]

    def create(self, user, title, notes):
        assert (user.id, title, notes) == (7, 'New request', 'Please add it')
        return {'id': 24, 'title': title, 'notes': notes}, 201, None

    def cancel(self, user, request_id, *, librarian):
        assert (user.id, request_id, librarian) == (7, 23, False)
        return {'id': request_id}, None

    def resolve(self, user, request_id, body):
        assert (user.id, request_id, body.status) == (7, 23, 'fulfilled')
        return {'id': request_id, 'status': body.status}, None


class FakeNotificationData:
    def __init__(self):
        self.calls = []
        self.bus_calls = []
        self.prefs = SimpleNamespace(**{
            'notify_friend_requests': True,
            'notify_activity': True,
            'notify_mentions': True,
            'notify_chat': True,
            'notify_free_games': True,
            'email_notify_social': True,
            'email_digest_daily': False,
            'share_activity': True,
        })

    def list(self, user_id, *, limit, unread_only):
        self.calls.append(('list', user_id, limit, unread_only))
        return {'notifications': [], 'unread_count': 0, 'empty': True}

    def mark_read(self, user_id, ids, *, all_read):
        self.calls.append(('mark', user_id, ids, all_read))
        return {'marked': len(ids) if not all_read else 4, 'unread_count': 0}

    def preferences(self, user):
        assert user.id == 7
        return self.prefs

    def update_preferences(self, user, payload):
        assert user.id == 7
        self.calls.append(('preferences', dict(payload)))
        for key, value in payload.items():
            if hasattr(self.prefs, key):
                setattr(self.prefs, key, bool(value))

    def bus_status(self):
        self.bus_calls.append('status')
        return {'configured': True, 'apprise_configured': False, 'ntfy_configured': True}

    def emit_test(self):
        self.bus_calls.append('emit')
        return True

    def publish_test_event(self, user):
        self.bus_calls.append(('publish_event', user.name))
        return {'type': 'test', 'message': 'ping', 'user': user.name}


class FakeWantedUpdateData:
    def __init__(self):
        self.calls = []

    def list(self, user_id):
        assert user_id == 7
        return [{'id': 'wanted-1', 'game_uuid': 'game-1', 'kind': 'update'}]

    def game_access(self, user, game_uuid):
        assert (user.id, game_uuid) == (7, 'game-1')
        return True, True

    def add(self, user_id, body):
        self.calls.append(('add', user_id, body.game_uuid, body.kind))
        return {'id': 'wanted-new', 'game_uuid': body.game_uuid, 'kind': body.kind}

    def fulfill(self, user_id, body):
        self.calls.append(('fulfill', user_id, body.game_uuid, body.kind))
        return 2


class FakeUpdateReadData:
    def __init__(self):
        self.calls = []

    def inbox(self, user, *, limit, library_uuid):
        self.calls.append(('inbox', user.id, limit, library_uuid))
        return {'count': 0, 'limit': limit, 'items': [], 'freshness_check': {}}

    def store_search(self, user, *, name, source, limit):
        self.calls.append(('search', user.id, name, source, limit))
        return {'q': name, 'source': source, 'results': [{'name': 'Fixture store hit'}]}


class FakeUpdateScanData:
    def __init__(self):
        self.calls = []
        self.result = {
            'requested': 2, 'checked': 1,
            'behind': [{'uuid': 'game-1', 'name': 'Fixture', 'status': 'behind'}],
            'behind_count': 1, 'errors': [], 'remaining': 3,
            'limit': 50, 'only_stale': False,
        }

    def scan(self, user, *, limit, library_uuid, only_stale):
        self.calls.append((user.id, limit, library_uuid, only_stale))
        return self.result


class FakeLocaleData:
    def __init__(self):
        self.value = 'es'
        self.calls = []

    def get(self, _user):
        return self.value

    def set(self, user, locale):
        self.calls.append((user.id, locale))
        self.value = locale


def _run(app, path, *, cookie=None, session_cookie_name='session', extra_cookies=None, method='GET', json_body=None, form_body=None, headers=None, base_url='http://testserver'):
    async def perform():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=base_url
        ) as client:
            if cookie:
                client.cookies.set(session_cookie_name, cookie)
            for name, value in (extra_cookies or {}).items():
                client.cookies.set(name, value)
            return await client.request(
                method, path, json=json_body, data=form_body, headers=headers,
                follow_redirects=False,
            )

    return asyncio.run(perform())


def _runtime(monkeypatch, *, admin=False):
    monkeypatch.delenv('ONEIRODEX_NATIVE_ADMIN_PILOT', raising=False)
    flask_app = Flask(__name__)
    flask_app.config.update(
        SECRET_KEY='native-asgi-browse-secret', TESTING=True,
        SQLALCHEMY_DATABASE_URI='sqlite://', SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    from oneirodex import db

    db.init_app(flask_app)
    manager = LoginManager(flask_app)
    manager.login_view = 'login.login'
    manager.login_message = 'Please log in to access this page.'
    user = SimpleNamespace(
        id=7,
        role='admin' if admin else 'user',
        state=True,
        is_active=True,
        is_authenticated=True,
        session_fingerprint=lambda: 'fp',
    )
    manager.user_loader(lambda identity: user if identity == '7:fp' else None)
    flask_app._fake_user = user
    flask_app.add_url_rule('/login', endpoint='login.login', view_func=lambda: 'login')
    flask_app.add_url_rule(
        '/browse_games', endpoint='legacy_browse', view_func=lambda: 'legacy'
    )
    flask_app.add_url_rule(
        '/api/acquire/status', endpoint='legacy_acquire_status', view_func=lambda: 'legacy'
    )
    flask_app.add_url_rule(
        '/api/acquire/search', endpoint='legacy_acquire_search',
        view_func=lambda: 'legacy', methods=['GET'],
    )
    flask_app.add_url_rule(
        '/api/acquire/download', endpoint='legacy_acquire_download',
        view_func=lambda: 'legacy', methods=['POST'],
    )
    flask_app.add_url_rule(
        '/api/social/status', endpoint='legacy_social_status',
        view_func=lambda: 'legacy', methods=['GET'],
    )
    flask_app.add_url_rule(
        '/api/social/friends', endpoint='legacy_social_friends',
        view_func=lambda: 'legacy', methods=['GET'],
    )
    flask_app.add_url_rule(
        '/api/oidc/status', endpoint='legacy_oidc_status', view_func=lambda: 'legacy'
    )
    flask_app.add_url_rule(
        '/api/remote-play/status', endpoint='legacy_remote_play_status',
        view_func=lambda: 'legacy',
    )
    flask_app.add_url_rule(
        '/api/settings/module-status', endpoint='legacy_settings_module_status',
        view_func=lambda: 'legacy',
    )
    flask_app.add_url_rule(
        '/api/health/library', endpoint='legacy_library_health', view_func=lambda: 'legacy'
    )
    flask_app.add_url_rule(
        '/api/health/games/<game_uuid>', endpoint='legacy_game_health',
        view_func=lambda game_uuid: 'legacy',
    )
    flask_app.add_url_rule(
        '/api/quality-profiles', endpoint='legacy_quality_profiles', view_func=lambda: 'legacy'
    )
    flask_app.add_url_rule(
        '/api/admin/challenge-solver/status', endpoint='legacy_challenge_solver_status',
        view_func=lambda: 'legacy',
    )
    flask_app.add_url_rule(
        '/api/admin/ambient-lighting/status', endpoint='legacy_ambient_lighting_status',
        view_func=lambda: 'legacy',
    )
    flask_app.add_url_rule(
        '/api/ai/status', endpoint='legacy_ai_status', view_func=lambda: 'legacy'
    )
    flask_app.add_url_rule(
        '/api/admin/library_platforms', endpoint='legacy_library_platforms',
        view_func=lambda: 'legacy',
    )
    flask_app.add_url_rule(
        '/api/arr/status', endpoint='legacy_arr_status', view_func=lambda: 'legacy'
    )
    flask_app.add_url_rule(
        '/api/discover/sections', endpoint='legacy_discover_sections', view_func=lambda: 'legacy'
    )
    flask_app.add_url_rule(
        '/api/discover/rows/<identifier>', endpoint='legacy_discover_row',
        view_func=lambda identifier: 'legacy',
    )
    flask_app.add_url_rule(
        '/api/discover/pins', endpoint='legacy_discover_pins',
        view_func=lambda: 'legacy pins write', methods=['GET', 'PUT'],
    )
    flask_app.add_url_rule(
        '/api/account/summary', endpoint='legacy_account_summary', view_func=lambda: 'legacy'
    )
    flask_app.add_url_rule(
        '/api/account/invites', endpoint='legacy_account_invites',
        view_func=lambda: 'legacy invite create', methods=['GET', 'POST'],
    )
    flask_app.add_url_rule(
        '/api/account/invites/<token>', endpoint='legacy_account_invite_delete',
        view_func=lambda token: 'legacy invite delete', methods=['DELETE'],
    )
    flask_app.add_url_rule(
        '/api/account/preferences', endpoint='legacy_account_preferences',
        view_func=lambda: 'legacy preferences', methods=['GET', 'PUT'],
    )
    flask_app.add_url_rule(
        '/api/account/avatar/stock', endpoint='legacy_account_stock_avatar',
        view_func=lambda: 'legacy stock avatar', methods=['POST'],
    )
    flask_app.add_url_rule(
        '/api/account/avatar', endpoint='legacy_account_avatar',
        view_func=lambda: 'legacy avatar upload', methods=['POST'],
    )
    flask_app.add_url_rule(
        '/api/account/password', endpoint='legacy_account_password',
        view_func=lambda: 'legacy account password', methods=['POST'],
    )
    flask_app.add_url_rule(
        '/api/client/capabilities', endpoint='legacy_client_capabilities',
        view_func=lambda: 'legacy capabilities',
    )
    flask_app.add_url_rule(
        '/api/client/lifecycle', endpoint='legacy_client_lifecycle',
        view_func=lambda: 'legacy lifecycle',
    )
    flask_app.add_url_rule(
        '/api/client/heartbeat', endpoint='legacy_client_heartbeat',
        view_func=lambda: 'legacy heartbeat', methods=['POST'],
    )
    flask_app.add_url_rule(
        '/api/client/commands', endpoint='legacy_client_commands',
        view_func=lambda: 'legacy client commands', methods=['GET', 'POST'],
    )
    flask_app.add_url_rule(
        '/api/client/commands/ack', endpoint='legacy_client_commands_ack',
        view_func=lambda: 'legacy command ack', methods=['POST'],
    )
    flask_app.add_url_rule(
        '/api/client/commands/nack', endpoint='legacy_client_commands_nack',
        view_func=lambda: 'legacy command nack', methods=['POST'],
    )
    flask_app.add_url_rule(
        '/api/announcements', endpoint='legacy_announcements',
        view_func=lambda: 'legacy announcements', methods=['GET', 'POST'],
    )
    flask_app.add_url_rule(
        '/api/news/gaming', endpoint='legacy_gaming_news', view_func=lambda: 'legacy news'
    )
    flask_app.add_url_rule(
        '/api/news/free-games', endpoint='legacy_free_games', view_func=lambda: 'legacy free games'
    )
    flask_app.add_url_rule(
        '/api/collections', endpoint='legacy_collections', view_func=lambda: 'legacy collections'
    )
    flask_app.add_url_rule(
        '/api/collections/<collection_uuid>', endpoint='legacy_collection_detail',
        view_func=lambda collection_uuid: 'legacy collection detail',
    )
    flask_app.add_url_rule(
        '/api/requests', endpoint='legacy_requests', view_func=lambda: 'legacy requests',
        methods=['GET', 'POST'],
    )
    flask_app.add_url_rule(
        '/api/requests/<int:request_id>', endpoint='legacy_request',
        view_func=lambda request_id: 'legacy request', methods=['PATCH', 'DELETE'],
    )
    flask_app.add_url_rule(
        '/api/notifications', endpoint='legacy_notifications',
        view_func=lambda: 'legacy notifications', methods=['GET'],
    )
    flask_app.add_url_rule(
        '/api/notifications/read', endpoint='legacy_notifications_read',
        view_func=lambda: 'legacy notifications read', methods=['POST'],
    )
    flask_app.add_url_rule(
        '/api/notifications/preferences', endpoint='legacy_notification_preferences',
        view_func=lambda: 'legacy notification preferences', methods=['GET', 'POST'],
    )
    flask_app.add_url_rule(
        '/api/updates/wanted', endpoint='legacy_wanted_updates',
        view_func=lambda: 'legacy wanted updates', methods=['GET', 'POST'],
    )
    flask_app.add_url_rule(
        '/api/updates/wanted/fulfill', endpoint='legacy_wanted_fulfill',
        view_func=lambda: 'legacy wanted fulfill', methods=['POST'],
    )
    flask_app.add_url_rule(
        '/api/updates/inbox', endpoint='legacy_updates_inbox',
        view_func=lambda: 'legacy updates inbox', methods=['GET'],
    )
    flask_app.add_url_rule(
        '/api/updates/store_search', endpoint='legacy_updates_store_search',
        view_func=lambda: 'legacy updates search', methods=['GET'],
    )
    flask_app.add_url_rule(
        '/api/updates/scan', endpoint='legacy_updates_scan',
        view_func=lambda: 'legacy updates scan', methods=['POST'],
    )
    flask_app.add_url_rule(
        '/api/calendar', endpoint='legacy_release_calendar', view_func=lambda: 'legacy calendar'
    )
    flask_app.add_url_rule(
        '/api/tokens', endpoint='legacy_api_tokens', view_func=lambda: 'legacy tokens',
        methods=['GET', 'POST'],
    )
    flask_app.add_url_rule(
        '/api/tokens/<int:token_id>', endpoint='legacy_api_token_delete',
        view_func=lambda token_id: 'legacy token delete', methods=['DELETE'],
    )
    flask_app.before_request(
        lambda: (_ for _ in ()).throw(AssertionError('Flask request dispatch used'))
    )
    monkeypatch.setattr(asgi, 'create_app', lambda: flask_app)
    monkeypatch.setattr(admin_pilot, '_native_auth_backend', lambda _app: (
        lambda _user_id: user,
        lambda _prefix: None,
        lambda _token: None,
    ))
    monkeypatch.setattr(browse, 'BrowseDataAccess', lambda: FakeBrowseData())
    monkeypatch.setattr(
        acquire_status, 'AcquireStatusData', lambda: FakeAcquireStatusData()
    )
    fake_acquire_actions = FakeAcquireActionData()
    monkeypatch.setattr(
        acquire_actions, 'AcquireActionData', lambda: fake_acquire_actions
    )
    fake_social_reads = FakeSocialReadData()
    monkeypatch.setattr(social_reads, 'SocialReadData', lambda: fake_social_reads)
    fake_game_reads = FakeGameReadData()
    monkeypatch.setattr(game_reads, 'GameReadData', lambda: fake_game_reads)
    fake_filter_reads = FakeFilterReadData()
    monkeypatch.setattr(filter_reads, 'FilterReadData', lambda _app: fake_filter_reads)
    fake_playtime = FakePlaytimeData()
    monkeypatch.setattr(playtime, 'PlaytimeData', lambda: fake_playtime)
    fake_related_media = FakeRelatedMediaData()
    monkeypatch.setattr(related_media, 'RelatedMediaData', lambda: fake_related_media)
    fake_saved_filters = FakeSavedFilterData()
    monkeypatch.setattr(saved_filters, 'SavedFilterData', lambda: fake_saved_filters)
    fake_batch_favorite = FakeBatchFavoriteData()
    monkeypatch.setattr(batch_favorite, 'BatchFavoriteData', lambda: fake_batch_favorite)
    fake_batch_status = FakeBatchStatusData()
    monkeypatch.setattr(batch_status, 'BatchStatusData', lambda: fake_batch_status)
    fake_batch_wishlist = FakeBatchWishlistData()
    monkeypatch.setattr(batch_wishlist, 'BatchWishlistData', lambda: fake_batch_wishlist)
    fake_batch_refresh = FakeBatchRefreshData()
    monkeypatch.setattr(batch_refresh, 'BatchRefreshData', lambda: fake_batch_refresh)
    fake_member_game_state = FakeMemberGameStateData()
    monkeypatch.setattr(
        member_game_state, 'MemberGameStateData', lambda: fake_member_game_state,
    )
    fake_favorites = FakeFavoritesData()
    monkeypatch.setattr(favorites, 'FavoritesData', lambda: fake_favorites)
    fake_member_meta = FakeMemberMetaData()
    monkeypatch.setattr(member_meta, 'MemberMetaData', lambda: fake_member_meta)
    fake_vr_reads = FakeVrReadData()
    monkeypatch.setattr(vr_reads, 'VrReadData', lambda: fake_vr_reads)
    fake_social_writes = FakeSocialWriteData()
    monkeypatch.setattr(social_writes, 'SocialWriteData', lambda: fake_social_writes)
    monkeypatch.setattr(oidc_status, 'OidcStatusData', lambda: FakeOidcStatusData())
    monkeypatch.setattr(
        remote_play_status, 'RemotePlayStatusData', lambda: FakeRemotePlayStatusData()
    )
    monkeypatch.setattr(
        settings_module_status, 'SettingsModuleStatusData',
        lambda: FakeSettingsModuleStatusData(),
    )
    monkeypatch.setattr(
        library_health, 'LibraryHealthData', lambda: FakeLibraryHealthData()
    )
    monkeypatch.setattr(game_health, 'GameHealthData', lambda: FakeGameHealthData())
    monkeypatch.setattr(
        quality_profiles, 'QualityProfilesData', lambda: FakeQualityProfilesData()
    )
    monkeypatch.setattr(
        status_reads, 'StorageStatusData',
        lambda: FakeSimpleStatusData({'helpers_enabled': False, 'allow_apply': False}),
    )
    monkeypatch.setattr(
        status_reads, 'MalwareScanStatusData',
        lambda: FakeSimpleStatusData({'enabled': False, 'block_on_hit': False}),
    )
    monkeypatch.setattr(
        status_reads, 'RtcStatusData',
        lambda: FakeSimpleStatusData({'enabled': False, 'url': None}),
    )
    monkeypatch.setattr(
        device_status, 'ChallengeSolverStatusData',
        lambda: FakeProbeStatusData({'enabled': True, 'provider': 'local'}),
    )
    monkeypatch.setattr(
        device_status, 'AmbientLightingStatusData',
        lambda: FakeProbeStatusData({'enabled': False, 'device': None}),
    )
    monkeypatch.setattr(ai_status, 'AiStatusData', lambda: FakeAiStatusData())
    monkeypatch.setattr(
        library_platforms, 'LibraryPlatformsData', lambda: FakeLibraryPlatformsData()
    )
    fake_library_reads = FakeLibraryReadData()
    monkeypatch.setattr(library_reads, 'LibraryReadData', lambda: fake_library_reads)
    monkeypatch.setattr(arr_status, 'ArrStatusData', lambda: FakeArrStatusData())
    fake_discover_reads = FakeDiscoverReadsData()
    monkeypatch.setattr(
        discover_reads, 'DiscoverReadsData', lambda: fake_discover_reads
    )
    monkeypatch.setattr(
        account_summary, 'AccountSummaryData', lambda: FakeAccountSummaryData()
    )
    monkeypatch.setattr(
        account_summary, 'AccountInvitesData', lambda: FakeAccountSummaryData()
    )
    monkeypatch.setattr(
        account_preferences, 'AccountPreferencesData', lambda _app=None: FakeAccountPreferencesData()
    )
    monkeypatch.setattr(
        account_stock_avatar, 'StockAvatarData', lambda: FakeAccountStockAvatarData()
    )
    monkeypatch.setattr(
        'oneirodex.utils.release_calendar.fetch_release_calendar',
        lambda **_kwargs: [{'name': 'Fixture release'}],
    )
    monkeypatch.setattr(
        account_tokens, 'PersonalTokenData', lambda: FakeAccountTokensData()
    )
    monkeypatch.setattr(
        account_avatar_upload, 'AccountAvatarUploadData',
        lambda: FakeAccountAvatarUploadData(),
    )
    monkeypatch.setattr(
        account_password, 'AccountPasswordData', lambda: FakeAccountPasswordData()
    )
    monkeypatch.setattr(
        client_reads, 'ClientReadData', lambda: FakeClientReadData()
    )
    monkeypatch.setattr(
        announcements, 'AnnouncementData', lambda: FakeAnnouncementData()
    )
    fake_ownership = FakeOwnershipProviderData()
    monkeypatch.setattr(
        ownership_providers, 'OwnershipProviderData',
        lambda: fake_ownership,
    )
    fake_emulator = FakeEmulatorReadData()
    monkeypatch.setattr(emulator_reads, 'EmulatorReadData', lambda: fake_emulator)
    fake_path_check = FakePathAvailabilityData()
    monkeypatch.setattr(
        system_path_check, 'PathAvailabilityData', lambda: fake_path_check,
    )
    fake_file_types = FakeSystemFileTypeData()
    monkeypatch.setattr(
        system_file_types, 'SystemFileTypeData', lambda: fake_file_types,
    )
    fake_news = FakeNewsFeedData()
    monkeypatch.setattr(news_feeds, 'NewsFeedData', lambda: fake_news)
    monkeypatch.setattr(
        collection_reads, 'CollectionReadData', lambda: FakeCollectionReadData()
    )
    monkeypatch.setattr(wishlist, 'WishlistData', lambda: FakeWishlistData())
    fake_notifications = FakeNotificationData()
    monkeypatch.setattr(notifications, 'NotificationData', lambda: fake_notifications)
    fake_wanted = FakeWantedUpdateData()
    monkeypatch.setattr(wanted_updates, 'WantedUpdateData', lambda: fake_wanted)
    fake_update_reads = FakeUpdateReadData()
    monkeypatch.setattr(updates_reads, 'UpdateReadData', lambda: fake_update_reads)
    fake_update_scan = FakeUpdateScanData()
    monkeypatch.setattr(updates_scan, 'UpdateScanData', lambda: fake_update_scan)
    fake_locale = FakeLocaleData()
    monkeypatch.setattr(locale_routes, 'LocaleData', lambda: fake_locale)
    runtime = asgi.LazyASGIApp()
    runtime._fake_acquire_actions = fake_acquire_actions
    runtime._fake_social_reads = fake_social_reads
    runtime._fake_game_reads = fake_game_reads
    runtime._fake_discover_reads = fake_discover_reads
    runtime._fake_library_reads = fake_library_reads
    runtime._fake_filter_reads = fake_filter_reads
    runtime._fake_playtime = fake_playtime
    runtime._fake_related_media = fake_related_media
    runtime._fake_saved_filters = fake_saved_filters
    runtime._fake_batch_favorite = fake_batch_favorite
    runtime._fake_batch_status = fake_batch_status
    runtime._fake_batch_wishlist = fake_batch_wishlist
    runtime._fake_batch_refresh = fake_batch_refresh
    runtime._fake_member_game_state = fake_member_game_state
    runtime._fake_favorites = fake_favorites
    runtime._fake_member_meta = fake_member_meta
    runtime._fake_vr_reads = fake_vr_reads
    runtime._fake_notifications = fake_notifications
    runtime._fake_social_writes = fake_social_writes
    runtime._fake_wanted = fake_wanted
    runtime._fake_update_reads = fake_update_reads
    runtime._fake_update_scan = fake_update_scan
    runtime._fake_ownership = fake_ownership
    runtime._fake_emulator = fake_emulator
    runtime._fake_path_check = fake_path_check
    runtime._fake_file_types = fake_file_types
    runtime._fake_locale = fake_locale
    runtime._fake_news = fake_news
    return flask_app, runtime


def _signed_session():
    return dump_session_cookie(
        {'_user_id': '7:fp', '_fresh': True}, 'native-asgi-browse-secret'
    )


def _signed_session_with_csrf():
    session = {'_user_id': '7:fp', '_fresh': True}
    token = generate_csrf_token(session, 'native-asgi-browse-secret')
    return dump_session_cookie(session, 'native-asgi-browse-secret'), token


def test_native_locale_read_preserves_supported_values_and_envelope_headers(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)

    response = _run(runtime, '/api/locale', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json() == {'locale': 'es', 'supported': ['en', 'es']}
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_native_locale_read_does_not_push_flask_app_context(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('native locale route pushed a Flask app context')
    )

    response = _run(runtime, '/api/locale', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json()['locale'] == 'es'


def test_native_locale_write_preserves_csrf_session_and_preference_cookie(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    cookie, csrf = _signed_session_with_csrf()

    async def save():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.post(
                '/api/locale', json={'locale': 'es-MX'},
                headers={'X-CSRFToken': csrf},
            )

    response = asyncio.run(save())

    assert response.status_code == 200
    assert response.json() == {'locale': 'es', 'supported': ['en', 'es']}
    assert response.cookies.get('gt_locale') == 'es'
    assert response.cookies.get('session')
    assert runtime._fake_locale.calls == [(7, 'es')]


def test_native_locale_write_rejects_missing_csrf_without_mutation(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)

    async def save():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', _signed_session())
            return await client.post('/api/locale', json={'locale': 'es'})

    response = asyncio.run(save())

    assert response.status_code == 400
    assert runtime._fake_locale.calls == []


def _bearer_runtime(monkeypatch, scopes):
    import hashlib

    _flask_app, runtime = _runtime(monkeypatch)
    user = SimpleNamespace(
        id=7, role='user', state=True, is_active=True, is_authenticated=True,
    )
    token = SimpleNamespace(
        user_id=7, token_hash=hashlib.sha256(b'social-test').hexdigest(),
        revoked_at=None, expires_at=None, scopes=list(scopes),
        has_scope=lambda scope: scope in scopes,
        is_expired=lambda _now=None: False,
    )
    monkeypatch.setattr(
        admin_pilot, '_native_auth_backend',
        lambda _app: (
            lambda user_id: user if user_id == 7 else None,
            lambda prefix: token if prefix == 'deadbeef' else None,
            lambda _token: None,
        ),
    )
    return runtime, 'Bearer gt_deadbeef_social-test'


def test_lazy_asgi_dispatches_authenticated_browse_without_flask_request(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    response = _run(runtime, '/browse_games?page=3', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json() == {
        'games': [], 'total': 0, 'pages': 0, 'current_page': 3,
    }
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.headers['content-security-policy']


def test_native_auth_uses_shared_fingerprint_resolver_not_flask_login_callback(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    flask_app.login_manager._user_callback = lambda _identity: (_ for _ in ()).throw(
        AssertionError('FastAPI auth called Flask-Login user_loader')
    )

    response = _run(runtime, '/browse_games?page=3', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json()['current_page'] == 3


def test_lazy_asgi_browse_preserves_login_redirect_and_flash(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    response = _run(runtime, '/browse_games?page=3')

    assert response.status_code == 302, response.text
    assert response.headers['location'] == '/login?next=%2Fbrowse_games%3Fpage%3D3'
    assert response.headers['content-type'] == 'text/html; charset=utf-8'
    assert response.text == (
        '<!doctype html>\n'
        '<html lang=en>\n'
        '<title>Redirecting...</title>\n'
        '<h1>Redirecting...</h1>\n'
        '<p>You should be redirected automatically to the target URL: '
        '<a href="/login?next=%2Fbrowse_games%3Fpage%3D3">'
        '/login?next=%2Fbrowse_games%3Fpage%3D3</a>. If not, click the link.\n'
    )
    session_cookie = response.cookies.get('session')
    assert session_cookie
    decoded = flask_app.session_interface.get_signing_serializer(flask_app).loads(session_cookie)
    assert decoded['_flashes'] == [('message', 'Please log in to access this page.')]


def test_lazy_asgi_restricted_matches_flask_login_redirect_body(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    response = _run(runtime, '/restricted')

    assert response.status_code == 302
    assert response.headers['location'] == '/login?next=%2Frestricted'
    assert response.headers['content-type'] == 'text/html; charset=utf-8'
    assert response.text == (
        '<!doctype html>\n'
        '<html lang=en>\n'
        '<title>Redirecting...</title>\n'
        '<h1>Redirecting...</h1>\n'
        '<p>You should be redirected automatically to the target URL: '
        '<a href="/login?next=%2Frestricted">/login?next=%2Frestricted</a>. '
        'If not, click the link.\n'
    )


def test_lazy_asgi_dispatches_authenticated_acquire_status_without_flask_request(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    asyncio.run(runtime._ensure_flask())
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('Flask app context used')
    )
    response = _run(runtime, '/api/acquire/status', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json() == {
        'enabled': True,
        'native_ready': True,
        'can_send': False,
        'ok': True,
        'error': None,
        'error_code': None,
        'success': True,
    }
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_lazy_asgi_acquire_status_head_matches_get_headers_without_a_body(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    get = _run(runtime, '/api/acquire/status', cookie=_signed_session())

    async def perform_head():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', _signed_session())
            return await client.head('/api/acquire/status')

    head = asyncio.run(perform_head())
    assert head.status_code == get.status_code == 200
    assert head.content == b''
    assert head.headers['content-length'] == str(len(get.content))


def test_lazy_asgi_acquire_status_preserves_login_redirect_and_flash(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    response = _run(runtime, '/api/acquire/status')

    assert response.status_code == 302
    assert response.headers['location'] == (
        '/login?next=%2Fapi%2Facquire%2Fstatus'
    )
    assert response.text.endswith(
        '<a href="/login?next=%2Fapi%2Facquire%2Fstatus">'
        '/login?next=%2Fapi%2Facquire%2Fstatus</a>. If not, click the link.\n'
    )
    session_cookie = response.cookies.get('session')
    assert session_cookie
    decoded = flask_app.session_interface.get_signing_serializer(flask_app).loads(session_cookie)
    assert decoded['_flashes'] == [('message', 'Please log in to access this page.')]


def test_lazy_asgi_dispatches_acquire_search_without_provider_network(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    asyncio.run(runtime._ensure_flask())
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('Flask app context used')
    )
    response = _run(
        runtime, '/api/acquire/search?q=Fixture&current=1.0', cookie=_signed_session()
    )

    assert response.status_code == 200
    assert response.json() == {
        'q': 'Fixture', 'results': [{'title': 'Fixture result'}], 'warnings': [],
    }
    assert runtime._fake_acquire_actions.calls == [('search', 'Fixture', '1.0')]
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_lazy_asgi_dispatches_acquire_send_through_safe_adapter(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()

    async def send_download():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.post(
                '/api/acquire/download',
                json={'url': 'https://downloads.example.test/item.torrent', 'provider': 'qbittorrent'},
                headers={'X-CSRFToken': csrf},
            )

    response = asyncio.run(send_download())
    assert response.status_code == 200
    assert response.json()['provider'] == 'qbittorrent'
    assert response.json()['result'] == {'queued': True}
    assert runtime._fake_acquire_actions.calls == [
        ('validate', 'https://downloads.example.test/item.torrent'),
        ('send', 'https://downloads.example.test/item.torrent', 'qbittorrent'),
    ]


def test_lazy_asgi_acquire_send_requires_librarian_without_provider_call(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    cookie, csrf = _signed_session_with_csrf()

    async def send_download():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.post(
                '/api/acquire/download', json={'magnet': 'magnet:?xt=urn:fixture'},
                headers={'X-CSRFToken': csrf},
            )

    response = asyncio.run(send_download())
    assert response.status_code == 403
    assert response.json()['error'] == 'Librarian or admin required'
    assert runtime._fake_acquire_actions.calls == []


@pytest.mark.parametrize(
    ('path', 'expected_key'),
    [('/api/social/status', 'friend_count'), ('/api/social/friends', 'friends')],
)
def test_native_social_reads_dispatch_with_read_scope(monkeypatch, path, expected_key):
    runtime, authorization = _bearer_runtime(monkeypatch, ['read:social'])
    async def get_data():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            return await client.get(path, headers={'Authorization': authorization})

    response = asyncio.run(get_data())
    assert response.status_code == 200
    assert expected_key in response.json()
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_native_social_reads_do_not_push_flask_context(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    asyncio.run(runtime._ensure_flask())
    monkeypatch.setattr(
        flask_app, 'app_context',
        lambda: (_ for _ in ()).throw(AssertionError('Flask app context used')),
    )
    monkeypatch.setattr(
        flask_app, 'test_request_context',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError('Flask request context used')
        ),
    )

    response = _run(runtime, '/api/users/9/profile', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json()['user']['id'] == 9


def test_native_activity_feed_preserves_first_query_values_and_clamped_limit(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    response = _run(
        runtime,
        '/api/activity?limit=500&limit=2&friends_only=yes&friends_only=0',
        cookie=_signed_session(),
    )

    assert response.status_code == 200
    assert response.json() == {
        'activity': [{'game_name': 'Fixture'}],
        'now_playing': [],
        'friends_only': True,
    }
    assert runtime._fake_social_reads.activity_calls == [(7, 100, True)]


def test_native_activity_feed_restricts_child_accounts(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    flask_app._fake_user.role = 'child'

    response = _run(runtime, '/api/activity', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json() == {
        'activity': [], 'now_playing': [], 'restricted': True,
    }
    assert runtime._fake_social_reads.activity_calls == []


def test_native_activity_feed_requires_read_social_scope_for_bearer(monkeypatch):
    runtime, authorization = _bearer_runtime(monkeypatch, ['read:library'])
    response = asyncio.run(
        _get_with_authorization(runtime, '/api/activity', authorization)
    )

    assert response.status_code == 403
    assert response.json()['error'] == 'Missing scope: read:social'
    assert runtime._fake_social_reads.activity_calls == []


@pytest.mark.parametrize(
    ('suffix', 'expected'),
    [
        ('details', {'uuid': 'game-1', 'name': 'Fixture game'}),
        ('more_from', {'sections': [], 'ok': True, 'error': None,
                       'error_code': None, 'success': True}),
        ('editions', {'uuid': 'game-1', 'editions': [], 'system_count': 0,
                      'ok': True, 'error': None, 'error_code': None,
                      'success': True}),
        ('freshness', {'game_uuid': 'game-1', 'status': 'unknown'}),
    ],
)
def test_native_game_detail_reads_dispatch_without_flask_request(monkeypatch, suffix, expected):
    _flask_app, runtime = _runtime(monkeypatch)

    response = _run(runtime, f'/api/games/game-1/{suffix}', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json() == expected
    assert runtime._fake_game_reads.calls == [
        ('game', 'game-1'), ('access', 7, 'game-1'), (suffix, 7, 'game-1'),
    ]
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_native_game_versions_requires_library_scope_and_hides_paths(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    path = '/api/games/123e4567-e89b-12d3-a456-426614174000/versions'
    response = _run(runtime, path, cookie=_signed_session())

    assert response.status_code == 200
    assert response.json() == {
        'game_uuid': '123e4567-e89b-12d3-a456-426614174000',
        'versions': [{'uuid': 'version-1'}],
    }
    assert runtime._fake_game_reads.calls[-1] == (
        'versions', 7, '123e4567-e89b-12d3-a456-426614174000',
    )


def test_native_game_versions_rejects_invalid_uuid_before_lookup(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    response = _run(runtime, '/api/games/not-a-uuid/versions', cookie=_signed_session())

    assert response.status_code == 400
    assert response.json()['error'] == 'Invalid game UUID'
    assert runtime._fake_game_reads.calls == []


def test_native_game_versions_requires_read_library_for_bearer(monkeypatch):
    runtime, authorization = _bearer_runtime(monkeypatch, ['read:social'])
    response = asyncio.run(_get_with_authorization(
        runtime,
        '/api/games/123e4567-e89b-12d3-a456-426614174000/versions',
        authorization,
    ))

    assert response.status_code == 403
    assert response.json()['error_code'] == 'forbidden'
    assert runtime._fake_game_reads.calls == []


def test_native_game_freshness_check_requires_csrf_and_uses_fake_adapter(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    cookie, csrf = _signed_session_with_csrf()

    async def run_check(headers):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.post(
                '/api/games/game-1/freshness/check', headers=headers,
            )

    rejected = asyncio.run(run_check({}))
    assert rejected.status_code == 400
    assert runtime._fake_game_reads.calls == []

    accepted = asyncio.run(run_check({'X-CSRFToken': csrf}))
    assert accepted.status_code == 200
    assert accepted.json() == {'status': 'current'}
    assert runtime._fake_game_reads.calls[-1] == ('check_freshness', 7, 'game-1')


@pytest.mark.parametrize(
    ('game_uuid', 'allowed', 'expected_status', 'expected_code'),
    [('missing', True, 404, 'not_found'), ('game-1', False, 403, 'forbidden')],
)
def test_native_game_detail_reads_preserve_not_found_and_acl_refusals(
    monkeypatch, game_uuid, allowed, expected_status, expected_code,
):
    _flask_app, runtime = _runtime(monkeypatch)
    runtime._fake_game_reads.allowed = allowed

    response = _run(
        runtime, f'/api/games/{game_uuid}/details', cookie=_signed_session(),
    )

    assert response.status_code == expected_status
    assert response.json()['error_code'] == expected_code


def test_native_next_custom_igdb_id_keeps_signed_in_bare_payload_and_head(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    asyncio.run(runtime._ensure_flask())
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('Flask app context used')
    )

    response = _run(runtime, '/api/get_next_custom_igdb_id', cookie=_signed_session())
    head = _run(
        runtime, '/api/get_next_custom_igdb_id', cookie=_signed_session(), method='HEAD',
    )

    assert response.status_code == 200
    assert response.json() == {'next_id': 2000000421}
    assert head.status_code == 200 and head.content == b''
    assert runtime._fake_game_reads.calls == [
        ('next_custom_igdb_id',), ('next_custom_igdb_id',),
    ]


def test_native_game_search_preserves_first_query_values_and_member_payload(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    response = _run(
        runtime,
        '/api/search?query=first&query=second&genre=RPG&genre=Puzzle',
        cookie=_signed_session(),
    )

    assert response.status_code == 200
    assert response.json() == [{'id': 1, 'uuid': 'game-1', 'name': 'Fixture game'}]
    assert runtime._fake_game_reads.searches == [(7, 'first', 'RPG')]


def test_native_game_search_rejects_long_query_before_search(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    response = _run(
        runtime, f"/api/search?query={'x' * 101}", cookie=_signed_session(),
    )

    assert response.status_code == 400
    assert response.json()['error'] == 'Search term too long'
    assert runtime._fake_game_reads.searches == []


def test_native_filter_bundle_returns_member_filter_contract(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    response = _run(runtime, '/api/filters/bundle', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json()['libraries'] == [{'uuid': 'library-1', 'name': 'Fixture'}]
    assert response.json()['ownershipStores'] == []
    assert runtime._fake_filter_reads.calls == [('bundle', 7)]


def test_native_filter_reads_do_not_push_flask_app_context(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)

    def forbidden_app_context():
        raise AssertionError('native filter route pushed a Flask app context')

    flask_app.app_context = forbidden_app_context
    for path in ('/api/filters/bundle', '/api/library_platforms', '/api/genres'):
        response = _run(runtime, path, cookie=_signed_session())
        assert response.status_code == 200


@pytest.mark.parametrize(
    ('query', 'expected'),
    [('include_completion=1&include_completion=0', True),
     ('include_completion=True', False), ('', False)],
)
def test_native_library_platforms_preserve_first_value_flag(monkeypatch, query, expected):
    _flask_app, runtime = _runtime(monkeypatch)
    suffix = f'?{query}' if query else ''
    response = _run(runtime, f'/api/library_platforms{suffix}', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json() == [{'id': 'SNES', 'name': 'Super Nintendo', 'game_count': 3}]
    assert runtime._fake_filter_reads.calls == [('platforms', 7, expected)]


def test_native_get_libraries_preserves_member_payload_and_head_without_flask_context(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    asyncio.run(runtime._ensure_flask())
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('Flask app context used')
    )

    response = _run(runtime, '/api/get_libraries', cookie=_signed_session())
    head = _run(runtime, '/api/get_libraries', cookie=_signed_session(), method='HEAD')

    assert response.status_code == 200
    assert response.json() == [{
        'uuid': 'lib-1', 'name': 'Fixture library', 'game_count': 3,
    }]
    assert head.status_code == 200 and head.content == b''
    assert runtime._fake_library_reads.calls == [('list', 7), ('list', 7)]


def test_native_library_detail_and_watch_reads_keep_acl_and_not_found_order(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)

    detail = _run(runtime, '/api/library/lib-1', cookie=_signed_session())
    watch = _run(runtime, '/api/library/lib-1/watch', cookie=_signed_session())
    blocked = _run(runtime, '/api/library/blocked', cookie=_signed_session())
    missing = _run(runtime, '/api/library/missing', cookie=_signed_session())

    assert detail.status_code == watch.status_code == 200
    assert detail.json() == {'uuid': 'lib-1', 'name': 'Fixture library'}
    assert watch.json() == {
        'uuid': 'lib-1', 'name': 'Fixture library', 'watch_enabled': True,
        'watch_effective': True, 'watch_global_enabled': True,
    }
    assert blocked.status_code == 403
    assert missing.status_code == 404
    assert runtime._fake_library_reads.calls == [
        ('access', 7, 'lib-1'), ('library', 'lib-1'),
        ('access', 7, 'lib-1'), ('library', 'lib-1'),
        ('access', 7, 'blocked'), ('access', 7, 'missing'), ('library', 'missing'),
    ]


def test_native_admin_library_detail_requires_admin_and_keeps_envelope(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch, admin=True)
    response = _run(
        runtime, '/api/admin/libraries/lib-1', cookie=_signed_session(),
    )

    assert response.status_code == 200
    assert response.json()['uuid'] == 'lib-1'
    assert response.json()['success'] is True
    assert runtime._fake_library_reads.calls == [('library', 'lib-1')]

    flask_app._fake_user.role = 'user'
    denied = _run(
        runtime, '/api/admin/libraries/lib-1', cookie=_signed_session(),
    )
    assert denied.status_code == 403
    assert denied.json()['error'] == 'Admin required'


def test_native_library_watch_write_requires_librarian_csrf_and_value(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    flask_app._fake_user.role = 'librarian'
    cookie, csrf = _signed_session_with_csrf()

    async def send(payload, *, with_csrf=True):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            headers = {'X-CSRFToken': csrf} if with_csrf else {}
            return await client.put(
                '/api/library/lib-1/watch', json=payload, headers=headers,
            )

    rejected = asyncio.run(send({'watch_enabled': False}, with_csrf=False))
    invalid = asyncio.run(send({'watch_enabled': 'maybe'}))
    saved = asyncio.run(send({'watch_enabled': False}))

    assert rejected.status_code == 400
    assert invalid.status_code == 400
    assert saved.status_code == 200
    assert saved.json() == {
        'uuid': 'lib-1', 'name': 'Fixture library', 'watch_enabled': False,
        'watch_effective': False, 'watch_global_enabled': True,
    }
    assert runtime._fake_library_reads.calls == [
        ('access', 7, 'lib-1'), ('library', 'lib-1'),
        ('access', 7, 'lib-1'), ('library', 'lib-1'),
        ('update_watch', 'lib-1', False),
    ]


def test_native_reorder_libraries_requires_admin_csrf_and_keeps_body_status(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()

    async def send(with_csrf):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            headers = {'X-CSRFToken': csrf} if with_csrf else {}
            return await client.post(
                '/api/reorder_libraries', json={'order': ['lib-1', 'lib-2']},
                headers=headers,
            )

    rejected = asyncio.run(send(False))
    accepted = asyncio.run(send(True))

    assert rejected.status_code == 400
    assert accepted.status_code == 200
    assert accepted.json()['status'] == 'success'
    assert runtime._fake_library_reads.calls == [('reorder', ['lib-1', 'lib-2'])]


def test_native_reorder_libraries_rejects_malformed_or_non_object_json(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()

    async def send(body):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.post(
                '/api/reorder_libraries', content=body,
                headers={'X-CSRFToken': csrf, 'Content-Type': 'application/json'},
            )

    malformed = asyncio.run(send('{'))
    non_object = asyncio.run(send('[]'))

    assert malformed.status_code == 400
    assert malformed.json()['error_code'] == 'bad_request'
    assert non_object.status_code == 400
    assert non_object.json()['error_code'] == 'bad_request'
    assert runtime._fake_library_reads.calls == []


def test_native_batch_edit_libraries_requires_admin_csrf_and_preserves_envelope(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()

    async def send(with_csrf):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            headers = {'X-CSRFToken': csrf} if with_csrf else {}
            return await client.post(
                '/api/admin/libraries/batch/edit',
                json={'library_uuids': ['lib-1'], 'scan_depth': 2},
                headers=headers,
            )

    rejected = asyncio.run(send(False))
    accepted = asyncio.run(send(True))

    assert rejected.status_code == 400
    assert accepted.status_code == 200
    assert accepted.json()['results'][0]['status'] == 'updated'
    assert runtime._fake_library_reads.calls == [(
        'batch_edit', 7, {'library_uuids': ['lib-1'], 'scan_depth': 2},
    )]


def test_native_batch_edit_empty_selection_uses_shared_error_envelope():
    body, status = library_reads.LibraryReadData().batch_edit({}, user=None)

    assert status == 400
    assert body == {
        'ok': False,
        'error': 'library_uuids required (list) or library_uuid',
        'error_code': 'bad_request',
        'message': 'library_uuids required (list) or library_uuid',
        'success': False,
        'status': 'rejected',
    }


def test_native_playtime_me_and_per_game_reads_dispatch(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    asyncio.run(runtime._ensure_flask())
    monkeypatch.setattr(
        flask_app, 'app_context',
        lambda: (_ for _ in ()).throw(AssertionError('Flask app context used')),
    )
    mine = _run(runtime, '/api/playtime/me', cookie=_signed_session())
    game = _run(runtime, '/api/playtime/games/game-1', cookie=_signed_session())
    missing = _run(runtime, '/api/playtime/games/missing', cookie=_signed_session())

    assert mine.status_code == game.status_code == 200
    assert mine.json() == {'total_seconds': 120, 'games': [{'game_uuid': 'game-1'}]}
    assert game.json()['total_seconds'] == 0
    assert missing.status_code == 403
    assert missing.json()['error'] == 'Forbidden'


def test_native_playtime_share_svg_dispatch_preserves_acl_payload(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    asyncio.run(runtime._ensure_flask())
    monkeypatch.setattr(
        flask_app, 'app_context',
        lambda: (_ for _ in ()).throw(AssertionError('Flask app context used')),
    )
    response = _run(runtime, '/api/playtime/share/game-1.svg', cookie=_signed_session())
    head = _run(runtime, '/api/playtime/share/game-1.svg', cookie=_signed_session(), method='HEAD')
    missing = _run(runtime, '/api/playtime/share/missing.svg', cookie=_signed_session())

    assert response.status_code == 200
    assert response.headers['content-type'].startswith('image/svg+xml')
    assert response.text.startswith('<svg')
    assert head.status_code == 200 and head.content == b''
    assert missing.status_code == 404
    assert missing.json()['error_code'] == 'not_found'
    assert runtime._fake_playtime.calls == [
        ('share_svg', 7, 'game-1'), ('share_svg', 7, 'game-1'),
        ('share_svg', 7, 'missing'),
    ]


@pytest.mark.parametrize(
    ('method', 'path', 'body', 'expected_call'),
    [
        ('POST', '/api/playtime/sessions', {'game_uuid': 'game-1', 'client': 'web'},
         ('start', 7, 'game-1', 'web')),
        ('POST', '/api/playtime/sessions/40/heartbeat', None, ('heartbeat',)),
        ('POST', '/api/playtime/sessions/40/stop', None, ('stop',)),
    ],
)
def test_native_playtime_mutations_require_csrf_and_use_fake_adapter(
    monkeypatch, method, path, body, expected_call,
):
    _flask_app, runtime = _runtime(monkeypatch)
    cookie, csrf = _signed_session_with_csrf()

    async def call(headers):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.request(method, path, json=body, headers=headers)

    rejected = asyncio.run(call({}))
    assert rejected.status_code == 400
    assert runtime._fake_playtime.calls == []

    accepted = asyncio.run(call({'X-CSRFToken': csrf}))
    assert accepted.status_code == (201 if expected_call[0] == 'start' else 200)
    assert runtime._fake_playtime.calls[-1] == expected_call


def test_native_playtime_mutations_require_write_scope_for_bearer(monkeypatch):
    routes = [
        ('/api/playtime/sessions', {'game_uuid': 'game-1', 'client': 'web'}),
        ('/api/playtime/sessions/40/heartbeat', None),
        ('/api/playtime/sessions/40/stop', None),
    ]
    runtime, read_only = _bearer_runtime(monkeypatch, ['read:library'])
    for path, body in routes:
        denied = _run(
            runtime, path, method='POST', json_body=body,
            headers={'Authorization': read_only},
        )
        assert denied.status_code == 403, (path, denied.text)
    assert runtime._fake_playtime.calls == []

    runtime, writable = _bearer_runtime(
        monkeypatch, ['read:library', 'write:library'],
    )
    statuses = [
        _run(runtime, path, method='POST', json_body=body,
             headers={'Authorization': writable}).status_code
        for path, body in routes
    ]
    assert statuses == [201, 200, 200]


def test_native_playtime_start_preserves_validation_and_user_owned_session_boundary(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    cookie, csrf = _signed_session_with_csrf()

    async def invalid_start():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.post(
                '/api/playtime/sessions', json={'unknown': 'field'},
                headers={'X-CSRFToken': csrf},
            )

    invalid = asyncio.run(invalid_start())
    assert invalid.status_code == 422
    assert invalid.json()['detail']
    assert runtime._fake_playtime.calls == []

    response = _run(runtime, '/api/playtime/sessions/41/heartbeat', cookie=cookie)
    assert response.status_code == 405


def test_native_related_media_read_preserves_acl_and_facets(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    response = _run(
        runtime, '/api/games/game-1/related_media', cookie=_signed_session(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload['ok'] is True
    assert payload['game_uuid'] == 'game-1'
    assert payload['available_kinds'] == ['film']
    assert payload['counts'] == {'film': 1}
    assert runtime._fake_related_media.calls == [
        ('game', 'game-1'), ('access', 7, 'game-1'), ('items', 'game-1'),
    ]


def test_native_related_media_read_does_not_push_flask_app_context(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    asyncio.run(runtime._ensure_flask())
    monkeypatch.setattr(
        flask_app, 'app_context',
        lambda: (_ for _ in ()).throw(AssertionError('Flask app context used')),
    )

    response = _run(
        runtime, '/api/games/game-1/related_media', cookie=_signed_session(),
    )

    assert response.status_code == 200
    assert response.json()['game_uuid'] == 'game-1'


@pytest.mark.parametrize(
    ('payload', 'expected_message'),
    [
        ({'title': 'Fixture', 'media_kind': 'game'}, 'media_kind must be one of:'),
        ({'title': 'Fixture', 'media_kind': 'film', 'external_url': 'file:///tmp'},
         'Link must be an http(s) URL'),
    ],
)
def test_native_related_media_create_validates_and_requires_librarian_csrf(
    monkeypatch, payload, expected_message,
):
    flask_app, runtime = _runtime(monkeypatch)
    flask_app._fake_user.role = 'librarian'
    cookie, csrf = _signed_session_with_csrf()

    async def create(headers):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.post(
                '/api/games/game-1/related_media', json=payload, headers=headers,
            )

    rejected = asyncio.run(create({}))
    assert rejected.status_code == 400
    assert runtime._fake_related_media.calls == []

    response = asyncio.run(create({'X-CSRFToken': csrf}))
    assert response.status_code == 400
    assert expected_message in response.json()['error']
    assert runtime._fake_related_media.calls == [('game', 'game-1')]


def test_native_related_media_create_and_delete_require_librarian_role(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    flask_app._fake_user.role = 'librarian'
    cookie, csrf = _signed_session_with_csrf()

    async def mutations():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            create = await client.post(
                '/api/games/game-1/related_media',
                json={'title': 'Fixture adaptation', 'media_kind': 'film'},
                headers={'X-CSRFToken': csrf},
            )
            delete = await client.delete(
                '/api/games/game-1/related_media/9',
                headers={'X-CSRFToken': csrf},
            )
            return create, delete

    created, deleted = asyncio.run(mutations())
    assert created.status_code == 201
    assert created.json()['item']['media_kind'] == 'film'
    assert deleted.status_code == 200
    assert deleted.json()['removed'] == 9
    assert runtime._fake_related_media.calls[-1] == ('delete', 'game-1', 9)


def test_native_related_media_mutations_reject_non_librarians(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    cookie, csrf = _signed_session_with_csrf()

    async def delete():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.delete(
                '/api/games/game-1/related_media/9',
                headers={'X-CSRFToken': csrf},
            )

    response = asyncio.run(delete())
    assert response.status_code == 403
    assert response.json()['error'] == 'Librarian or admin required'
    assert runtime._fake_related_media.calls == []


def test_native_game_screenshots_and_images_reads_dispatch_with_acl(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    screenshots = _run(
        runtime, '/api/game_screenshots/game-1', cookie=_signed_session(),
    )
    images = _run(
        runtime,
        '/api/game_images/game-1?kind=screenshot&kind=cover',
        cookie=_signed_session(),
    )

    assert screenshots.status_code == images.status_code == 200
    assert screenshots.json() == ['/static/library/images/fixture-shot.webp']
    assert images.json()['kind_filter'] == 'screenshot'
    assert runtime._fake_game_reads.calls == [
        ('game', 'game-1'), ('access', 7, 'game-1'), ('screenshots', 7, 'game-1'),
        ('game', 'game-1'), ('access', 7, 'game-1'),
        ('images', 7, 'game-1', 'screenshot'),
    ]


def test_native_game_images_bad_kind_returns_legacy_error_envelope(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    response = _run(
        runtime, '/api/game_images/game-1?kind=not-a-kind', cookie=_signed_session(),
    )

    assert response.status_code == 400
    assert response.json()['error'] == 'Invalid image kind'


def test_native_game_assists_reads_preserve_disabled_and_acl_contract(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    response = _run(runtime, '/api/games/game-1/assists', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json() == {
        'enabled': True, 'pack': {'title': 'Fixture'}, 'overlay_links': [],
    }
    assert runtime._fake_game_reads.calls == [
        ('assists_enabled',), ('game', 'game-1'), ('access', 7, 'game-1'),
        ('assists', 7, 'game-1'),
    ]

    runtime2_app, runtime2 = _runtime(monkeypatch)
    runtime2._fake_game_reads.assists_on = False
    disabled = _run(runtime2, '/api/games/game-1/assists', cookie=_signed_session())
    assert disabled.status_code == 200
    assert disabled.json() == {'enabled': False, 'pack': None}
    assert runtime2._fake_game_reads.calls == [('assists_enabled',)]


def test_native_game_assists_save_requires_admin_csrf_and_schema(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    flask_app._fake_user.role = 'admin'
    cookie, csrf = _signed_session_with_csrf()

    async def save(headers, payload):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.put(
                '/api/games/game-1/assists', json=payload, headers=headers,
            )

    rejected = asyncio.run(save({}, {'title': 'Fixture pack'}))
    assert rejected.status_code == 400
    assert runtime._fake_game_reads.calls == []

    invalid = asyncio.run(save({'X-CSRFToken': csrf}, {'unknown': True}))
    assert invalid.status_code == 422
    assert runtime._fake_game_reads.calls == [('assists_enabled',)]

    saved = asyncio.run(save({'X-CSRFToken': csrf}, {'title': 'Fixture pack'}))
    assert saved.status_code == 200
    assert saved.json()['pack']['title'] == 'Fixture pack'
    assert runtime._fake_game_reads.calls[-3:] == [
        ('assists_enabled',), ('game', 'game-1'), ('save_assists', 'game-1', 'Fixture pack'),
    ]


def test_native_game_assists_save_refuses_non_admin(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    cookie, csrf = _signed_session_with_csrf()

    async def save():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.put(
                '/api/games/game-1/assists', json={'title': 'Fixture'},
                headers={'X-CSRFToken': csrf},
            )

    response = asyncio.run(save())
    assert response.status_code == 403
    assert response.json()['error'] == 'Admin required'
    assert runtime._fake_game_reads.calls == []


def test_native_game_input_family_patch_preserves_librarian_csrf_acl_and_schema(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    flask_app._fake_user.role = 'librarian'
    cookie, csrf = _signed_session_with_csrf()

    async def send(payload, *, with_csrf=True):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            headers = {'X-CSRFToken': csrf} if with_csrf else {}
            return await client.patch(
                '/api/games/game-1/input_family', json=payload, headers=headers,
            )

    no_csrf = asyncio.run(send({'input_family': 'spinner'}, with_csrf=False))
    assert no_csrf.status_code == 400
    assert runtime._fake_game_reads.calls == []

    invalid = asyncio.run(send({'input_family': 'dance mat'}))
    assert invalid.status_code == 422
    assert runtime._fake_game_reads.calls == []

    saved = asyncio.run(send({'input_family': 'spinner'}))
    assert saved.status_code == 200
    assert {
        key: saved.json()[key] for key in ('uuid', 'input_family', 'families')
    } == {
        'uuid': 'game-1', 'input_family': 'spinner',
        'families': ['joystick', 'spinner', 'lightgun', 'trackball'],
    }
    assert runtime._fake_game_reads.calls == [
        ('game', 'game-1'), ('access', 7, 'game-1'),
        ('set_input_family', 'game-1', 'spinner'),
    ]

    blocked_runtime_app, blocked_runtime = _runtime(monkeypatch)
    blocked_runtime_app._fake_user.role = 'user'
    blocked_cookie, blocked_csrf = _signed_session_with_csrf()
    blocked = _run(
        blocked_runtime, '/api/games/game-1/input_family', cookie=blocked_cookie,
        method='PATCH', json_body={'input_family': 'lightgun'},
        headers={'X-CSRFToken': blocked_csrf},
    )
    assert blocked.status_code == 403
    assert blocked_runtime._fake_game_reads.calls == []


def test_native_move_game_to_library_preserves_librarian_csrf_and_access_checks(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    flask_app._fake_user.role = 'librarian'
    cookie, csrf = _signed_session_with_csrf()

    async def send(payload, *, with_csrf=True):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            headers = {'X-CSRFToken': csrf} if with_csrf else {}
            return await client.post(
                '/api/move_game_to_library', json=payload, headers=headers,
            )

    denied = asyncio.run(send({
        'game_uuid': 'game-1', 'target_library_uuid': 'lib-a',
    }, with_csrf=False))
    assert denied.status_code == 400
    assert runtime._fake_game_reads.calls == []

    saved = asyncio.run(send({
        'game_uuid': 'game-1', 'target_library_uuid': 'lib-a',
    }))
    assert saved.status_code == 200
    assert saved.json()['message'] == 'Game moved to Target'
    assert runtime._fake_game_reads.calls == [
        ('game', 'game-1'), ('library', 'lib-a'), ('access', 7, 'game-1'),
        ('library_access', 7, 'lib-a'), ('move_game', 'game-1', 'lib-a', 7),
    ]


def test_native_saved_filter_reads_fields_and_private_rows(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    asyncio.run(runtime._ensure_flask())
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('Flask app context used')
    )
    fields = _run(runtime, '/api/filters/fields', cookie=_signed_session())
    saved = _run(runtime, '/api/filters/saved', cookie=_signed_session())

    assert fields.status_code == saved.status_code == 200
    assert fields.json()['ok'] is True
    assert fields.json()['fields']
    assert saved.json()['filters'] == [
        {
            'id': 1, 'name': 'Favorite RPGs',
            'tree': {'field': 'is_vr', 'value': True}, 'is_collection': False,
        },
    ]
    assert runtime._fake_saved_filters.calls == [('list', 7)]


def test_native_saved_filter_create_validates_csrf_tree_and_conflicts(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    cookie, csrf = _signed_session_with_csrf()

    async def create(headers, payload):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.post('/api/filters/saved', json=payload, headers=headers)

    payload = {
        'name': 'VR picks', 'tree': {'field': 'is_vr', 'value': True},
        'is_collection': True,
    }
    csrf_denied = asyncio.run(create({}, payload))
    assert csrf_denied.status_code == 400
    assert runtime._fake_saved_filters.calls == []

    invalid_tree = asyncio.run(create(
        {'X-CSRFToken': csrf},
        {'name': 'Bad tree', 'tree': {'field': 'full_disk_path', 'value': 'secret'}},
    ))
    assert invalid_tree.status_code == 400
    assert invalid_tree.json()['detail']['path']
    assert runtime._fake_saved_filters.calls == []

    duplicate = asyncio.run(create(
        {'X-CSRFToken': csrf},
        {'name': 'Favorite RPGs', 'tree': {'field': 'is_vr', 'value': True}},
    ))
    assert duplicate.status_code == 409
    assert duplicate.json()['error_code'] == 'conflict'

    created = asyncio.run(create({'X-CSRFToken': csrf}, payload))
    assert created.status_code == 201
    assert created.json()['filter']['name'] == 'VR picks'


def test_native_saved_filter_update_delete_are_owner_scoped_and_csrf_protected(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    cookie, csrf = _signed_session_with_csrf()

    async def mutate(method, path, payload=None):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.request(
                method, path, json=payload, headers={'X-CSRFToken': csrf},
            )

    updated = asyncio.run(mutate(
        'PUT', '/api/filters/saved/1', {'name': 'Updated', 'is_collection': True},
    ))
    assert updated.status_code == 200
    assert updated.json()['filter']['name'] == 'Updated'
    assert updated.json()['filter']['is_collection'] is True

    deleted = asyncio.run(mutate('DELETE', '/api/filters/saved/1'))
    assert deleted.status_code == 200
    assert deleted.json()['deleted'] == 1

    missing = asyncio.run(mutate('DELETE', '/api/filters/saved/99'))
    assert missing.status_code == 404
    assert missing.json()['error'] == 'Filter not found'


def test_native_saved_filter_mutations_require_write_scope_for_bearer(monkeypatch):
    payload = {
        'name': 'Bearer filter', 'tree': {'field': 'is_vr', 'value': True},
        'is_collection': False,
    }
    runtime, read_only = _bearer_runtime(monkeypatch, ['read:library'])
    for method, path, body in (
        ('POST', '/api/filters/saved', payload),
        ('PUT', '/api/filters/saved/1', {'name': 'Updated'}),
        ('DELETE', '/api/filters/saved/1', None),
    ):
        response = _run(
            runtime, path, method=method, json_body=body,
            headers={'Authorization': read_only},
        )
        assert response.status_code == 403, (path, response.text)
    assert runtime._fake_saved_filters.calls == []

    runtime, writable = _bearer_runtime(
        monkeypatch, ['read:library', 'write:library'],
    )
    created = _run(
        runtime, '/api/filters/saved', method='POST', json_body=payload,
        headers={'Authorization': writable},
    )
    updated = _run(
        runtime, '/api/filters/saved/1', method='PUT', json_body={'name': 'Updated'},
        headers={'Authorization': writable},
    )
    deleted = _run(
        runtime, '/api/filters/saved/1', method='DELETE',
        headers={'Authorization': writable},
    )
    assert (created.status_code, updated.status_code, deleted.status_code) == (201, 200, 200)


def test_native_saved_filter_preview_keeps_bounded_member_sample(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    cookie, csrf = _signed_session_with_csrf()

    async def preview(payload):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.post(
                '/api/filters/preview', json=payload,
                headers={'X-CSRFToken': csrf},
            )

    response = asyncio.run(preview({
        'tree': {'field': 'is_vr', 'value': True}, 'limit': 1,
    }))
    assert response.status_code == 200
    assert response.json()['count'] == 4
    assert response.json()['sample'] == [{'uuid': 'game-1', 'name': 'Fixture'}]
    assert runtime._fake_saved_filters.calls[-1][0] == 'preview'


def test_native_batch_favorite_keeps_order_dedupe_acl_and_partial_payload(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    cookie, csrf = _signed_session_with_csrf()

    async def send(headers):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.post(
                '/api/games/batch/favorite',
                json={
                    'uuids': ['game-a', 'game-a', 'missing', 'blocked', 'already'],
                    'favorite': True,
                },
                headers=headers,
            )

    denied = asyncio.run(send({}))
    assert denied.status_code == 400
    assert runtime._fake_batch_favorite.calls == []

    response = asyncio.run(send({'X-CSRFToken': csrf}))
    assert response.status_code == 200
    assert response.json() == {
        'ok': True,
        'updated': [{'uuid': 'game-a', 'favorite': True}],
        'skipped': [
            {'uuid': 'missing', 'reason': 'not_found'},
            {'uuid': 'blocked', 'reason': 'forbidden'},
            {'uuid': 'already', 'reason': 'already_set'},
        ],
        'errors': [], 'limit': 100, 'favorite': True,
        'requested': 4, 'count': 1,
    }
    assert runtime._fake_batch_favorite.calls == [
        ('state', 7, ['game-a', 'missing', 'blocked', 'already']),
        ('set', 7, 'game-a', True), ('commit',),
    ]


def test_native_batch_favorite_validation_caps_and_commit_error_are_safe(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    cookie, csrf = _signed_session_with_csrf()

    async def send(payload):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.post(
                '/api/games/batch/favorite', json=payload,
                headers={'X-CSRFToken': csrf},
            )

    invalid = asyncio.run(send({'uuids': []}))
    assert invalid.status_code == 422
    assert invalid.json()['limit'] == 100

    oversized = asyncio.run(send({'uuids': ['g'] * 101, 'favorite': True}))
    assert oversized.status_code == 400
    assert oversized.json()['requested'] == 101

    runtime._fake_batch_favorite.commit_fails = True
    failed = asyncio.run(send({'uuids': ['game-a'], 'favorite': True}))
    assert failed.status_code == 500
    assert failed.json()['error'] == 'Could not save the change'
    assert 'private db info' not in failed.text
    assert runtime._fake_batch_favorite.calls[-1] == ('rollback',)


def test_native_batch_status_keeps_acl_partial_success_and_empty_clear(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    cookie, csrf = _signed_session_with_csrf()

    async def send(payload):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.post(
                '/api/games/batch/status', json=payload,
                headers={'X-CSRFToken': csrf},
            )

    response = asyncio.run(send({
        'uuids': ['game-a', 'already', 'missing', 'blocked'],
        'status': 'completed',
    }))
    assert response.status_code == 200
    assert response.json() == {
        'ok': True,
        'updated': [{'uuid': 'game-a', 'status': 'completed'}],
        'skipped': [
            {'uuid': 'already', 'reason': 'already_set'},
            {'uuid': 'missing', 'reason': 'not_found'},
            {'uuid': 'blocked', 'reason': 'forbidden'},
        ],
        'errors': [], 'limit': 100, 'status': 'completed',
        'status_info': {'status': 'completed'}, 'requested': 4, 'count': 1,
    }

    cleared = asyncio.run(send({'uuids': ['game-a'], 'status': ''}))
    assert cleared.status_code == 200
    assert cleared.json()['updated'] == [{'uuid': 'game-a', 'status': None}]
    assert runtime._fake_batch_status.calls[-2][0:5] == (
        'write', 7, 'game-a', 'unplayed', None,
    )


def test_native_batch_wishlist_add_and_remove_keep_partial_results(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    cookie, csrf = _signed_session_with_csrf()

    async def send(payload):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.post(
                '/api/games/batch/wishlist', json=payload,
                headers={'X-CSRFToken': csrf},
            )

    added = asyncio.run(send({
        'uuids': ['game-a', 'pending', 'missing', 'blocked', 'game-a'],
    }))
    assert added.status_code == 200
    assert added.json() == {
        'ok': True,
        'updated': [{
            'uuid': 'game-a', 'request_id': 22,
            'title': 'Game A', 'status': 'pending',
        }],
        'skipped': [
            {'uuid': 'pending', 'reason': 'already_pending'},
            {'uuid': 'missing', 'reason': 'not_found'},
            {'uuid': 'blocked', 'reason': 'forbidden'},
        ],
        'errors': [], 'limit': 50, 'requested': 4, 'count': 1,
    }
    assert runtime._fake_batch_wishlist.calls[-3:] == [
        ('create', 7, 'Game A', 'game-a'), ('commit',), ('log', 1, 7),
    ]

    removed = asyncio.run(send({'uuids': ['pending', 'game-a'], 'action': 'remove'}))
    assert removed.status_code == 200
    assert removed.json()['updated'] == [{'uuid': 'pending', 'id': 11}]
    assert removed.json()['skipped'] == [{'uuid': 'game-a', 'reason': 'not_pending'}]
    assert removed.json()['action'] == 'remove'


def test_native_batch_wishlist_empty_action_does_not_push_flask_context(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('native wishlist route pushed a Flask app context')
    )
    cookie, csrf = _signed_session_with_csrf()

    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.post(
                '/api/games/batch/wishlist', json={'uuids': []},
                headers={'X-CSRFToken': csrf},
            )

    response = asyncio.run(send())

    assert response.status_code == 200
    assert response.json()['ok'] is True
    assert response.json()['requested'] == 0


def test_native_batch_favorite_and_status_empty_actions_are_flask_context_free(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('native batch mutation pushed a Flask app context')
    )
    cookie, csrf = _signed_session_with_csrf()

    async def send(path, payload):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.post(
                path, json=payload, headers={'X-CSRFToken': csrf},
            )

    favorite = asyncio.run(send(
        '/api/games/batch/favorite', {'uuids': [], 'favorite': True}
    ))
    status = asyncio.run(send(
        '/api/games/batch/status', {'uuids': [], 'status': ''}
    ))

    assert favorite.status_code == status.status_code == 200
    assert favorite.json()['requested'] == status.json()['requested'] == 0


def test_native_batch_wishlist_rejects_child_and_invalid_action(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    cookie, csrf = _signed_session_with_csrf()

    async def send(payload):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.post(
                '/api/games/batch/wishlist', json=payload,
                headers={'X-CSRFToken': csrf},
            )

    flask_app._fake_user.role = 'child'
    denied = asyncio.run(send({'uuids': ['game-a']}))
    assert denied.status_code == 403
    assert denied.json()['error'] == 'Wishlist requests are not available for this account'
    assert runtime._fake_batch_wishlist.calls == []

    flask_app._fake_user.role = 'user'
    invalid = asyncio.run(send({'uuids': ['game-a'], 'action': 'queue'}))
    assert invalid.status_code == 400
    assert invalid.json()['error'] == 'action must be add or remove'
    assert runtime._fake_batch_wishlist.calls == []


def test_native_batch_freshness_keeps_stale_acl_and_partial_contract(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    asyncio.run(runtime._ensure_flask())
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('Flask app context used')
    )
    cookie, csrf = _signed_session_with_csrf()

    async def send(payload):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.post(
                '/api/games/batch/freshness/check', json=payload,
                headers={'X-CSRFToken': csrf},
            )

    response = asyncio.run(send({
        'uuids': ['stale', 'fresh', 'blocked', 'missing'],
    }))
    assert response.status_code == 200
    assert response.json() == {
        'ok': True,
        'updated': [{
            'uuid': 'stale', 'name': 'Stale', 'status': 'current', 'confidence': 0.8,
        }],
        'skipped': [
            {'uuid': 'fresh', 'reason': 'fresh'},
            {'uuid': 'blocked', 'reason': 'forbidden'},
            {'uuid': 'missing', 'reason': 'not_found'},
        ],
        'errors': [], 'limit': 50, 'only_stale': True,
        'requested': 4, 'count': 1,
    }
    assert runtime._fake_batch_refresh.calls == [
        ('state', ['stale', 'fresh', 'blocked', 'missing']),
        ('freshness', 'stale'), ('commit',),
    ]


def test_native_admin_freshness_refresh_requires_admin_csrf_and_keeps_result(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch, admin=True)
    asyncio.run(runtime._ensure_flask())
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('Flask app context used')
    )
    cookie, csrf = _signed_session_with_csrf()

    async def send(payload, *, with_csrf=True):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            headers = {'X-CSRFToken': csrf} if with_csrf else {}
            return await client.post(
                '/api/admin/freshness/refresh', json=payload, headers=headers,
            )

    denied = asyncio.run(send({'limit': 3}, with_csrf=False))
    assert denied.status_code == 400
    assert runtime._fake_batch_refresh.calls == []

    response = asyncio.run(send({'limit': 3, 'library_uuid': 'lib-a'}))
    assert response.status_code == 200
    assert response.json() == {
        'updated': [{'uuid': 'stale', 'name': 'Stale', 'status': 'current'}],
        'errors': [], 'count': 1, 'skipped_fresh': 0,
        'library_uuid': 'lib-a', 'limit': 3,
    }
    assert runtime._fake_batch_refresh.calls == [
        ('admin_games', 'lib-a', 15), ('freshness', 'stale'), ('commit',),
    ]


def test_native_batch_image_refresh_requires_librarian_and_queues(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    asyncio.run(runtime._ensure_flask())
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('Flask app context used')
    )
    cookie, csrf = _signed_session_with_csrf()

    async def send(payload):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.post(
                '/api/games/batch/refresh_images', json=payload,
                headers={'X-CSRFToken': csrf},
            )

    denied = asyncio.run(send({'uuids': ['game-a']}))
    assert denied.status_code == 403
    assert denied.json()['error'] == 'Librarian or admin required'
    assert runtime._fake_batch_refresh.calls == []

    flask_app._fake_user.role = 'librarian'
    queued = asyncio.run(send({'uuids': ['game-a', 'blocked', 'missing']}))
    assert queued.status_code == 202
    assert queued.json() == {
        'ok': True,
        'queued': [{'uuid': 'game-a', 'name': 'Game-A', 'status': 'queued'}],
        'skipped': [
            {'uuid': 'blocked', 'reason': 'forbidden'},
            {'uuid': 'missing', 'reason': 'not_found'},
        ],
        'errors': [], 'limit': 20, 'requested': 3, 'count': 1,
    }


def test_native_member_library_write_apis_require_write_scope(monkeypatch):
    routes = [
        ('/api/games/batch/wishlist', {'uuids': [], 'action': 'add'}),
        ('/api/games/batch/freshness/check', {'uuids': []}),
        ('/api/games/game-a/freshness/check', {}),
    ]
    runtime, read_only = _bearer_runtime(monkeypatch, ['read:library'])
    for path, body in routes:
        denied = _run(
            runtime, path, method='POST', json_body=body,
            headers={'Authorization': read_only},
        )
        assert denied.status_code == 403, (path, denied.text)

    runtime, writable = _bearer_runtime(
        monkeypatch, ['read:library', 'write:library'],
    )
    statuses = [
        _run(runtime, path, method='POST', json_body=body,
             headers={'Authorization': writable}).status_code
        for path, body in routes
    ]
    assert statuses == [200, 200, 200]


def test_native_single_game_favorite_and_status_actions_keep_contracts(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    monkeypatch.setattr(
        flask_app,
        'app_context',
        lambda: (_ for _ in ()).throw(AssertionError('Flask app context used')),
    )
    cookie, csrf = _signed_session_with_csrf()

    async def send(method, path, payload=None):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.request(
                method, path, json=payload,
                headers={'X-CSRFToken': csrf},
            )

    favorite = asyncio.run(send('GET', '/api/check_favorite/game-a'))
    assert favorite.status_code == 200
    assert favorite.json() == {'is_favorite': False}

    toggled = asyncio.run(send('POST', '/api/toggle_favorite/game-a'))
    assert toggled.status_code == 200
    assert toggled.json()['is_favorite'] is True
    assert runtime._fake_member_game_state.calls[-2:] == [
        ('favorite', 7, 'game-a', True), ('commit',),
    ]

    status = asyncio.run(send('GET', '/api/get_game_status/game-a'))
    assert status.status_code == 200
    assert status.json()['status'] == 'unplayed'

    updated = asyncio.run(send('POST', '/api/set_game_status/game-a', {'status': 'completed'}))
    assert updated.status_code == 200
    assert updated.json()['status'] == 'completed'
    assert 'Status updated to' in updated.json()['message']

    cleared = asyncio.run(send('POST', '/api/set_game_status/game-a', {'status': ''}))
    assert cleared.status_code == 200
    assert cleared.json()['status'] is None
    assert cleared.json()['message'] == 'Status cleared'


def test_native_library_writes_require_write_scope_for_bearer_tokens(monkeypatch):
    paths = [
        ('/api/toggle_favorite/game-a', None),
        ('/api/set_game_status/game-a', {'status': 'completed'}),
        ('/api/requests', {'title': 'New request', 'notes': 'Please add it'}),
        ('/api/updates/wanted', {'game_uuid': 'game-1', 'kind': 'dlc'}),
        ('/api/updates/wanted/fulfill', {'game_uuid': 'game-1', 'kind': 'dlc'}),
        ('/api/games/batch/favorite', {'uuids': ['game-a'], 'favorite': True}),
        ('/api/games/batch/status', {'uuids': ['game-a'], 'status': 'completed'}),
    ]

    runtime, read_only = _bearer_runtime(monkeypatch, ['read:library'])
    for path, body in paths:
        response = _run(
            runtime, path, method='POST', json_body=body,
            headers={'Authorization': read_only},
        )
        assert response.status_code == 403, (path, response.text)

    assert runtime._fake_member_game_state.calls == []
    assert runtime._fake_batch_favorite.calls == []
    assert runtime._fake_batch_status.calls == []

    runtime, writable = _bearer_runtime(
        monkeypatch, ['read:library', 'write:library'],
    )
    for path, body in paths:
        response = _run(
            runtime, path, method='POST', json_body=body,
            headers={'Authorization': writable},
        )
        assert response.status_code in (200, 201), (path, response.text)

    assert ('favorite', 7, 'game-a', True) in runtime._fake_member_game_state.calls
    assert ('status', 7, 'game-a', 'completed') in runtime._fake_member_game_state.calls
    assert ('set', 7, 'game-a', True) in runtime._fake_batch_favorite.calls
    assert any(call[0] == 'write' and call[1:5] == (7, 'game-a', 'unplayed', 'completed')
               for call in runtime._fake_batch_status.calls)


def test_native_account_preferences_write_requires_library_write_scope(monkeypatch):
    runtime, read_only = _bearer_runtime(monkeypatch, ['read:library'])
    denied = _run(
        runtime, '/api/account/preferences', method='PUT', json_body={'tile_size': '72'},
        headers={'Authorization': read_only},
    )
    assert denied.status_code == 403

    runtime, writable = _bearer_runtime(
        monkeypatch, ['read:library', 'write:library'],
    )
    allowed = _run(
        runtime, '/api/account/preferences', method='PUT', json_body={'tile_size': '72'},
        headers={'Authorization': writable},
    )
    assert allowed.status_code == 200, allowed.text


def test_native_collection_write_requires_library_write_scope(monkeypatch):
    payload = {'name': 'Shelf', 'description': 'About'}
    runtime, read_only = _bearer_runtime(monkeypatch, ['read:library'])
    denied = _run(
        runtime, '/api/collections', method='POST', json_body=payload,
        headers={'Authorization': read_only},
    )
    assert denied.status_code == 403

    runtime, writable = _bearer_runtime(
        monkeypatch, ['read:library', 'write:library'],
    )
    allowed = _run(
        runtime, '/api/collections', method='POST', json_body=payload,
        headers={'Authorization': writable},
    )
    assert allowed.status_code == 201, allowed.text


def test_native_wishlist_cancel_requires_library_write_scope(monkeypatch):
    runtime, read_only = _bearer_runtime(monkeypatch, ['read:library'])
    denied = _run(
        runtime, '/api/requests/23', method='DELETE',
        headers={'Authorization': read_only},
    )
    assert denied.status_code == 403

    runtime, writable = _bearer_runtime(
        monkeypatch, ['read:library', 'write:library'],
    )
    allowed = _run(
        runtime, '/api/requests/23', method='DELETE',
        headers={'Authorization': writable},
    )
    assert allowed.status_code == 200, allowed.text


def test_native_favorites_keeps_first_value_query_and_head_behavior(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    cookie = _signed_session()

    async def send(method):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.request(
                method,
                '/api/favorites?page=2&page=3&per_page=200&name=alpha&item_kind=game',
            )

    response = asyncio.run(send('GET'))
    assert response.status_code == 200
    assert response.json()['current_page'] == 2
    assert runtime._fake_favorites.calls == [(
        7,
        [('page', '2'), ('page', '3'), ('per_page', '200'),
         ('name', 'alpha'), ('item_kind', 'game')],
    )]

    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('Flask app context used')
    )

    head = asyncio.run(send('HEAD'))
    assert head.status_code == 200
    assert head.content == b''


def test_native_member_meta_routes_keep_auth_and_validation(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    cookie, csrf = _signed_session_with_csrf()

    async def send(method, path, payload=None, with_csrf=True):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            headers = {'X-CSRFToken': csrf} if with_csrf else {}
            return await client.request(method, path, json=payload, headers=headers)

    monkeypatch.setattr(
        flask_app,
        'app_context',
        lambda: (_ for _ in ()).throw(AssertionError('Flask app context used')),
    )
    role = asyncio.run(send('GET', '/api/current_user_role'))
    role_head = asyncio.run(send('HEAD', '/api/current_user_role'))
    assert role.json() == {'role': 'user'}
    packs = asyncio.run(send('GET', '/api/icon-packs'))
    packs_head = asyncio.run(send('HEAD', '/api/icon-packs'))
    assert packs.json()['current'] == 'outline'
    assert role_head.status_code == 200 and role_head.content == b''
    assert packs_head.status_code == 200 and packs_head.content == b''
    assert packs.json()['packs'][0]['id'] == 'outline'
    assert packs.json()['packs'][0]['css_url'].startswith('/static/library/icon-themes/')

    existing = asyncio.run(send('POST', '/api/check_username', {'username': 'Taken'}))
    assert existing.status_code == 200
    assert existing.json() == {'exists': True}
    missing = asyncio.run(send('POST', '/api/check_username', {}))
    assert missing.status_code == 422
    assert missing.json()['error'] == 'Invalid request.'
    no_csrf = asyncio.run(send(
        'POST', '/api/check_username', {'username': 'free'}, with_csrf=False,
    ))
    assert no_csrf.status_code == 400


def test_native_current_user_role_does_not_push_flask_context(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    monkeypatch.setattr(
        flask_app,
        'app_context',
        lambda: (_ for _ in ()).throw(AssertionError('Flask app context used')),
    )

    response = _run(runtime, '/api/current_user_role', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json() == {'role': 'user'}


@pytest.mark.parametrize('catalogue', [
    'genres', 'themes', 'game_modes', 'player_perspectives', 'igdb_platforms',
])
def test_native_filter_taxonomies_keep_authenticated_catalogue_shape(monkeypatch, catalogue):
    _flask_app, runtime = _runtime(monkeypatch)
    cookie = _signed_session()

    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.get(f'/api/{catalogue}')

    response = asyncio.run(send())
    assert response.status_code == 200
    assert response.json() == [{'id': 1, 'name': catalogue.title()}]


def test_native_member_profiles_keep_social_scope_and_acl_response_shapes(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    cookie = _signed_session()

    async def send(path, authorization=None):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            headers = {'Authorization': authorization} if authorization else {}
            return await client.get(path, headers=headers)

    profile = asyncio.run(send('/api/users/9/profile'))
    assert profile.status_code == 200
    assert profile.json()['user'] == {'id': 9, 'name': 'Fixture'}
    assert profile.json()['is_friend'] is True

    missing = asyncio.run(send('/api/users/404/profile'))
    assert missing.status_code == 404
    assert missing.json()['error'] == 'Not found'

    compare = asyncio.run(send('/api/users/7/compare/9'))
    assert compare.status_code == 200
    assert compare.json()['right'] == {'id': 9, 'name': 'Friend'}

    forbidden = asyncio.run(send('/api/users/8/compare/9'))
    assert forbidden.status_code == 403
    assert forbidden.json()['error'] == 'Forbidden'


def test_native_vr_reads_keep_feature_gate_pagination_and_acl(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    cookie = _signed_session()

    async def send(path, method='GET'):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.request(method, path)

    disabled = asyncio.run(send('/api/vr/catalog'))
    assert disabled.status_code == 403
    assert disabled.json()['error'] == 'VR browse is disabled'

    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('Flask app context used')
    )
    flask_app.config['ENABLE_VR_BROWSE'] = '1'
    catalog = asyncio.run(send(
        '/api/vr/catalog?page=2&page=4&per_page=500&vr_compat=native_vr',
    ))
    assert catalog.status_code == 200
    assert catalog.json()['page'] == 2
    assert catalog.json()['games'][0]['vr_compat'] == 'native_vr'

    invalid = asyncio.run(send('/api/vr/catalog?page=bad'))
    assert invalid.status_code == 400
    assert invalid.json()['error'] == 'Invalid pagination'

    detail = asyncio.run(send('/api/vr/games/vr-1'))
    assert detail.status_code == 200
    assert detail.json()['uuid'] == 'vr-1'
    blocked = asyncio.run(send('/api/vr/games/blocked'))
    assert blocked.status_code == 403
    assert blocked.json()['error'] == 'Forbidden'


def test_native_vr_profile_routes_keep_librarian_csrf_and_validation(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    flask_app._fake_user.role = 'librarian'
    cookie, csrf = _signed_session_with_csrf()

    async def send(method, path, payload=None, with_csrf=True):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            headers = {'X-CSRFToken': csrf} if with_csrf else {}
            return await client.request(method, path, json=payload, headers=headers)

    profiles = asyncio.run(send('GET', '/api/games/game-a/vr_profiles'))
    assert profiles.status_code == 200
    assert profiles.json()['kinds'] == ['native', 'injector', 'flat']
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('Flask app context used')
    )

    saved = asyncio.run(send('PUT', '/api/games/game-a/vr_profiles/injector', {
        'runtime': 'openxr', 'profile_url': 'https://example.invalid/profile',
        'notes': 'Fixture notes', 'source': 'librarian',
    }))
    assert saved.status_code == 200
    assert saved.json()['profile']['kind'] == 'injector'

    invalid = asyncio.run(send('PUT', '/api/games/game-a/vr_profiles/native', {
        'profile_url': 'file:///etc/passwd',
    }))
    assert invalid.status_code == 422
    malformed_kind_and_body = asyncio.run(send(
        'PUT', '/api/games/game-a/vr_profiles/unknown', {'profile_url': 'file:///bad'},
    ))
    assert malformed_kind_and_body.status_code == 422
    invalid_kind = asyncio.run(send(
        'PUT', '/api/games/game-a/vr_profiles/unknown', {
            'runtime': 'openxr', 'profile_url': 'https://example.invalid',
        },
    ))
    assert invalid_kind.status_code == 400

    no_csrf = asyncio.run(send(
        'PATCH', '/api/games/game-a/vr_compat', {'vr_compat': 'flat'}, with_csrf=False,
    ))
    assert no_csrf.status_code == 400

    compat = asyncio.run(send(
        'PATCH', '/api/games/game-a/vr_compat', {'vr_compat': 'flat'},
    ))
    assert compat.status_code == 200
    assert compat.json()['vr_compat'] == 'flat'

    deleted = asyncio.run(send('DELETE', '/api/games/game-a/vr_profiles/injector'))
    assert deleted.status_code == 200
    absent = asyncio.run(send('DELETE', '/api/games/game-a/vr_profiles/native'))
    assert absent.status_code == 404


@pytest.mark.parametrize(
    ('path', 'method', 'expected'),
    [('/api/check_favorite/missing', 'GET', 'Game not found'),
     ('/api/check_favorite/blocked', 'GET', 'Forbidden'),
     ('/api/get_game_status/blocked', 'GET', 'Game not found'),
     ('/api/set_game_status/game-a', 'POST', 'Invalid status value')],
)
def test_native_single_game_actions_keep_acl_and_validation(monkeypatch, path, method, expected):
    _flask_app, runtime = _runtime(monkeypatch)
    cookie, csrf = _signed_session_with_csrf()

    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            payload = {'status': 'unknown'} if method == 'POST' else None
            return await client.request(
                method, path, json=payload, headers={'X-CSRFToken': csrf},
            )

    response = asyncio.run(send())
    assert response.status_code in ({400} if expected == 'Invalid status value' else {403, 404})
    assert response.json()['error'] == expected


@pytest.mark.parametrize(
    ('payload', 'expected'),
    [({'uuids': ['game-a']}, 'status required'),
     ({'uuids': ['game-a'], 'status': 4}, 'status must be a string'),
     ({'uuids': ['game-a'], 'status': 'unknown'}, 'Invalid status value')],
)
def test_native_batch_status_rejects_invalid_values(monkeypatch, payload, expected):
    _flask_app, runtime = _runtime(monkeypatch)
    cookie, csrf = _signed_session_with_csrf()

    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.post(
                '/api/games/batch/status', json=payload,
                headers={'X-CSRFToken': csrf},
            )

    response = asyncio.run(send())
    assert response.status_code == 400
    assert response.json()['error'] == expected
    assert runtime._fake_batch_status.calls == []


def test_native_social_reads_deny_bearer_without_read_scope(monkeypatch):
    runtime, authorization = _bearer_runtime(monkeypatch, ['read:library'])
    response = asyncio.run(_get_with_authorization(runtime, '/api/social/status', authorization))

    assert response.status_code == 403
    assert response.json()['error'] == 'Missing scope: read:social'


async def _get_with_authorization(runtime, path, authorization):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
    ) as client:
        return await client.get(path, headers={'Authorization': authorization})


@pytest.mark.parametrize(
    ('method', 'path', 'body', 'expected_operation'),
    [
        ('POST', '/api/social/friends', {'username': 'unknown'}, 'request'),
        ('POST', '/api/social/friends/11/reject', None, 'reject'),
        ('POST', '/api/social/friends/11/block', None, 'block'),
        ('POST', '/api/social/friends/11/accept', None, 'accept'),
        ('DELETE', '/api/social/friends/11', None, 'delete'),
    ],
)
def test_native_social_mutations_dispatch_with_browser_csrf(
    monkeypatch, method, path, body, expected_operation,
):
    flask_app, runtime = _runtime(monkeypatch)
    cookie, csrf = _signed_session_with_csrf()

    async def mutate():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.request(
                method, path, json=body, headers={'X-CSRFToken': csrf}
            )

    response = asyncio.run(mutate())
    assert response.status_code == 200
    assert response.json()['ok'] is True
    assert runtime._fake_social_writes.calls[0][0] == expected_operation
    assert response.headers['x-content-type-options'] == 'nosniff'
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('Flask app context used')
    )
    repeated = asyncio.run(mutate())
    assert repeated.status_code == 200


@pytest.mark.parametrize('json_body', [1, [1], 'truthy'])
def test_native_social_request_matches_legacy_internal_error_for_truthy_non_object_json(
    monkeypatch, json_body,
):
    _flask_app, runtime = _runtime(monkeypatch)
    cookie, csrf = _signed_session_with_csrf()

    response = _run(
        runtime,
        '/api/social/friends',
        cookie=cookie,
        method='POST',
        json_body=json_body,
        headers={'X-CSRFToken': csrf},
    )

    assert response.status_code == 500
    assert response.json()['error_code'] == 'internal'
    assert response.json()['error'] == 'Something went wrong on our end. The error has been logged.'
    assert runtime._fake_social_writes.calls == []


def test_native_social_persistence_failure_uses_safe_api_error(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    cookie, csrf = _signed_session_with_csrf()

    def fail_request(*_args, **_kwargs):
        raise RuntimeError('synthetic persistence failure')

    monkeypatch.setattr(runtime._fake_social_writes, 'request', fail_request)

    async def post_request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=runtime, raise_app_exceptions=False,
            ),
            base_url='http://testserver',
        ) as client:
            client.cookies.set('session', cookie)
            return await client.post(
                '/api/social/friends',
                json={'username': 'friend'},
                headers={'X-CSRFToken': csrf},
            )

    response = asyncio.run(post_request())

    assert response.status_code == 500
    assert response.headers['content-type'].startswith('application/json')
    assert response.json() == {
        'ok': False,
        'error': 'Something went wrong on our end. The error has been logged.',
        'error_code': 'internal',
        'message': 'Something went wrong on our end. The error has been logged.',
        'success': False,
    }
    assert 'synthetic persistence failure' not in response.text


def test_native_social_mutations_require_write_scope_for_bearer(monkeypatch):
    runtime, authorization = _bearer_runtime(monkeypatch, ['read:social'])

    async def mutate():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            return await client.post(
                '/api/social/friends', json={'username': 'unknown'},
                headers={'Authorization': authorization},
            )

    response = asyncio.run(mutate())
    assert response.status_code == 403
    assert response.json()['error'] == 'Missing scope: write:social'
    assert runtime._fake_social_writes.calls == []


def test_native_social_mutations_allow_write_scope_without_browser_csrf(monkeypatch):
    runtime, authorization = _bearer_runtime(
        monkeypatch, ['read:social', 'write:social']
    )

    async def mutate():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            return await client.post(
                '/api/social/friends', json={'username': 'unknown'},
                headers={'Authorization': authorization},
            )

    response = asyncio.run(mutate())
    assert response.status_code == 200
    assert response.json()['sent'] is False
    assert runtime._fake_social_writes.calls[0][0] == 'request'


def test_lazy_asgi_dispatches_admin_oidc_status_without_flask_request(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    response = _run(runtime, '/api/oidc/status', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json() == {
        'ready': False, 'live_verified': False, 'message': 'Not configured',
    }
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_lazy_asgi_dispatches_admin_module_status_without_flask_request(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch, admin=True)
    monkeypatch.setattr(
        flask_app,
        'app_context',
        lambda: (_ for _ in ()).throw(AssertionError('Flask app context used')),
    )
    response = _run(runtime, '/api/settings/module-status', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json() == {
        'arr': {'on': False, 'label': 'Off'},
        'ai': {'on': False, 'label': 'Off'},
    }
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_lazy_asgi_dispatches_admin_library_health_without_flask_request(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    response = _run(
        runtime,
        '/api/health/library?limit=12&library_uuid=library-a',
        cookie=_signed_session(),
    )

    assert response.status_code == 200
    assert response.json() == {
        'count': 0, 'average_score': None, 'library_uuid': 'library-a',
    }
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_lazy_asgi_dispatches_member_game_health_with_acl_without_flask_request(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    response = _run(
        runtime,
        '/api/health/games/game-123',
        cookie=_signed_session(),
    )

    assert response.status_code == 200
    assert response.json() == {'uuid': 'game-123', 'score': 72, 'grade': 'fair'}
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_lazy_asgi_dispatches_admin_quality_profile_list_without_flask_request(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch, admin=True)
    monkeypatch.setattr(
        flask_app,
        'app_context',
        lambda: (_ for _ in ()).throw(AssertionError('Flask app context used')),
    )
    response = _run(runtime, '/api/quality-profiles', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json() == {'version': 2, 'active_id': 'balanced', 'profiles': []}
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_lazy_asgi_dispatches_quality_profile_actions_without_flask_request(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch, admin=True)
    monkeypatch.setattr(
        flask_app, 'app_context',
        lambda: (_ for _ in ()).throw(AssertionError('Flask app context used')),
    )
    cookie, csrf = _signed_session_with_csrf()
    active = _run(
        runtime, '/api/quality-profiles/active', cookie=cookie, method='PUT',
        json_body={'active_id': 'strict'}, headers={'X-CSRFToken': csrf},
    )
    score = _run(
        runtime, '/api/quality-profiles/score', cookie=cookie, method='POST',
        json_body={'title': 'Game 1080p'}, headers={'X-CSRFToken': csrf},
    )

    assert active.status_code == 200
    assert active.json()['active_id'] == 'strict'
    assert score.status_code == 200
    assert score.json() == {'title': 'Game 1080p', 'size_bytes': None, 'profile_id': None}
    assert active.headers['x-content-type-options'] == 'nosniff'


def test_lazy_asgi_dispatches_native_read_only_status_routes_without_flask_request(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch, admin=True)
    monkeypatch.setattr(
        flask_app,
        'app_context',
        lambda: (_ for _ in ()).throw(AssertionError('Flask app context used')),
    )
    cases = (
        ('/api/storage/status', {'helpers_enabled': False, 'allow_apply': False}),
        ('/api/admin/malware-scan/status', {'enabled': False, 'block_on_hit': False}),
        ('/api/rtc/status', {'enabled': False, 'url': None}),
    )
    for path, payload in cases:
        response = _run(runtime, path, cookie=_signed_session())
        assert response.status_code == 200
        assert response.json() == payload
        assert response.headers['x-content-type-options'] == 'nosniff'


def test_lazy_asgi_dispatches_native_device_status_without_running_probe_or_flask(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    cases = (
        ('/api/admin/challenge-solver/status?probe=yes', {'enabled': True, 'provider': 'local'}),
        ('/api/admin/ambient-lighting/status?probe=no', {'enabled': False, 'device': None}),
    )
    for path, payload in cases:
        response = _run(runtime, path, cookie=_signed_session())
        assert response.status_code == 200
        assert response.json() == {**payload, 'probe_requested': path.endswith('probe=yes')}
        assert response.headers['x-content-type-options'] == 'nosniff'


def test_lazy_asgi_dispatches_device_config_and_probe_actions_with_csrf(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch, admin=True)
    monkeypatch.setattr(
        flask_app, 'app_context',
        lambda: (_ for _ in ()).throw(AssertionError('Flask app context used')),
    )
    cookie, csrf = _signed_session_with_csrf()

    async def call():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver',
        ) as client:
            client.cookies.set('session', cookie)
            return await client.put(
                '/api/admin/ambient-lighting/config', json={'enabled': True},
                headers={'X-CSRFToken': csrf},
            ), await client.post(
                '/api/admin/challenge-solver/test', headers={'X-CSRFToken': csrf},
            )

    config, probe = asyncio.run(call())
    assert config.status_code == 200
    assert config.json()['enabled'] is True
    assert config.json()['secret_configured'] is True
    assert probe.status_code == 200
    assert probe.json()['probe_requested'] is True


def test_lazy_asgi_dispatches_ai_status_with_legacy_error_field_without_network_or_flask(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch, admin=True)
    monkeypatch.setattr(
        flask_app,
        'app_context',
        lambda: (_ for _ in ()).throw(AssertionError('Flask app context used')),
    )
    response = _run(runtime, '/api/ai/status', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json() == {
        'enabled': True,
        'auto_apply_enabled': False,
        'reachable': False,
        'base_url': 'http://ollama.test:11434',
        'model': 'small-model',
        'error': 'Ollama unreachable',
    }
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_lazy_asgi_dispatches_ai_config_and_actions_with_csrf_without_flask(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch, admin=True)
    monkeypatch.setattr(
        flask_app, 'app_context',
        lambda: (_ for _ in ()).throw(AssertionError('Flask app context used')),
    )
    cookie, csrf = _signed_session_with_csrf()

    async def call():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver',
        ) as client:
            client.cookies.set('session', cookie)
            config = await client.put(
                '/api/ai/config', json={'enabled': True},
                headers={'X-CSRFToken': csrf},
            )
            triage = await client.post(
                '/api/ai/triage', json={'name': 'Fixture', 'platform': 'NES'},
                headers={'X-CSRFToken': csrf},
            )
            notes = await client.post(
                '/api/ai/doctor-notes',
                json={'game_uuid': 'game-1', 'issues': ['missing-cover']},
                headers={'X-CSRFToken': csrf},
            )
            applied = await client.post(
                '/api/ai/apply-triage', json={'game_uuid': 'game-1', 'title': 'Fixture'},
                headers={'X-CSRFToken': csrf},
            )
            return config, triage, notes, applied

    config, triage, notes, applied = asyncio.run(call())
    assert config.status_code == 200
    assert config.json()['status'] == 'saved'
    assert config.json()['enabled'] is True
    assert triage.status_code == 200
    assert triage.json()['suggestions'] == [{'title': 'Fixture'}]
    assert notes.status_code == 200
    assert notes.json() == {'game_name': 'Fixture game', 'notes': 'Fixture note'}
    assert applied.status_code == 201
    assert applied.json()['name'] == 'Fixture'


def test_lazy_asgi_dispatches_library_platform_options_without_flask_or_database(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch, admin=True)
    monkeypatch.setattr(
        flask_app,
        'app_context',
        lambda: (_ for _ in ()).throw(AssertionError('Flask app context used')),
    )
    response = _run(runtime, '/api/admin/library_platforms', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json() == {
        'platforms': [
            {'key': 'PC', 'label': 'Windows PC'},
            {'key': 'NES', 'label': 'Nintendo Entertainment System'},
        ],
        'ok': True,
        'error': None,
        'error_code': None,
        'success': True,
    }
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_lazy_asgi_dispatches_arr_status_without_connector_requests_or_flask(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch, admin=True)
    monkeypatch.setattr(
        flask_app,
        'app_context',
        lambda: (_ for _ in ()).throw(AssertionError('Flask app context used')),
    )
    response = _run(runtime, '/api/arr/status', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json() == {
        'enabled': True,
        'module': 'arr',
        'status': 'ready',
        'connectors': [{'id': 'native_indexers', 'configured': True}],
        'hardlink_pipeline_enabled': True,
        'hardlink_helpers_enabled': True,
        'hardlink_apply_allowed': False,
        'indexer_warnings': [],
        'ok': True,
        'error': None,
        'error_code': None,
        'success': True,
    }
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_lazy_asgi_dispatches_member_discover_sections_and_rows_without_flask(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    sections = _run(runtime, '/api/discover/sections', cookie=_signed_session())
    row = _run(
        runtime,
        '/api/discover/rows/recent?offset=5&feed_token=feed-123',
        cookie=_signed_session(),
    )

    assert sections.status_code == 200
    assert sections.json() == {'sections': [{'id': 'recent', 'games': []}], 'feed_token': 'feed-123'}
    assert row.status_code == 200
    assert row.json() == {
        'identifier': 'recent', 'offset': 5, 'games': [],
        'ok': True, 'error': None, 'error_code': None, 'success': True,
    }
    assert sections.headers['x-content-type-options'] == 'nosniff'
    assert row.headers['x-content-type-options'] == 'nosniff'


def test_lazy_asgi_dispatches_member_discover_zone_and_genre_hub_without_flask(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    zone = _run(runtime, '/api/discover/zones/by-era', cookie=_signed_session())
    genre = _run(
        runtime,
        '/api/discover/hubs/genre/Action/Adventure',
        cookie=_signed_session(),
    )

    assert zone.status_code == genre.status_code == 200
    assert zone.json() == {
        'slug': 'by-era', 'sections': [],
        'ok': True, 'error': None, 'error_code': None, 'success': True,
    }
    assert genre.json() == {
        'genre': 'Action/Adventure', 'sections': [],
        'ok': True, 'error': None, 'error_code': None, 'success': True,
    }
    assert zone.headers['x-content-type-options'] == 'nosniff'
    assert genre.headers['x-content-type-options'] == 'nosniff'


def test_lazy_asgi_dispatches_discover_surprise_and_pins_get_without_flask(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    surprise = _run(
        runtime,
        '/api/discover/surprise?genre=5&exclude=game-a%2Cgame-b',
        cookie=_signed_session(),
    )
    pins = _run(runtime, '/api/discover/pins', cookie=_signed_session())

    assert surprise.status_code == pins.status_code == 200
    assert surprise.json() == {
        'game': None, 'reason': 'no_games', 'genre': {'id': 5, 'name': 'Arcade'}, 'genres': [],
        'ok': True, 'error': None, 'error_code': None, 'success': True,
    }
    assert pins.json() == {
        'pins': ['recent'], 'hidden': [], 'max_pins': 3, 'available': ['recent'],
        'ok': True, 'error': None, 'error_code': None, 'success': True,
    }
    assert surprise.headers['x-content-type-options'] == 'nosniff'
    assert pins.headers['x-content-type-options'] == 'nosniff'


def test_discover_pins_put_uses_native_csrf_and_adapter(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    cookie, csrf = _signed_session_with_csrf()

    async def perform_put(with_csrf):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            headers = {'X-CSRFToken': csrf} if with_csrf else {}
            return await client.put(
                '/api/discover/pins', json={'pins': ['recent']}, headers=headers,
            )

    rejected = asyncio.run(perform_put(False))
    accepted = asyncio.run(perform_put(True))
    assert rejected.status_code == 400
    assert accepted.status_code == 200
    assert accepted.json()['pins'] == ['recent']
    assert runtime._fake_discover_reads.saved == [(7, {'pins': ['recent']})]


def test_discover_pins_put_requires_write_scope_for_bearer(monkeypatch):
    runtime, read_only = _bearer_runtime(monkeypatch, ['read:library'])
    denied = _run(
        runtime, '/api/discover/pins', method='PUT',
        json_body={'pins': ['recent']}, headers={'Authorization': read_only},
    )
    assert denied.status_code == 403
    assert runtime._fake_discover_reads.saved == []

    runtime, writable = _bearer_runtime(
        monkeypatch, ['read:library', 'write:library'],
    )
    allowed = _run(
        runtime, '/api/discover/pins', method='PUT',
        json_body={'pins': ['recent']}, headers={'Authorization': writable},
    )
    assert allowed.status_code == 200
    assert runtime._fake_discover_reads.saved == [(7, {'pins': ['recent']})]


def test_discover_pins_get_allows_read_only_bearer(monkeypatch):
    runtime, read_only = _bearer_runtime(monkeypatch, ['read:library'])
    response = _run(
        runtime, '/api/discover/pins', headers={'Authorization': read_only},
    )
    assert response.status_code == 200
    assert response.json()['pins'] == ['recent']
    assert runtime._fake_discover_reads.saved == []


def test_lazy_asgi_dispatches_browser_account_summary_without_flask_or_extra_fields(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    response = _run(runtime, '/api/account/summary', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json() == {
        'username': 'member-seven',
        'email': 'member7@example.test',
        'role': 'user',
        'avatar_path': '/static/avatars/member.png',
        'avatar_url': '/static/avatars/member.png',
        'stock_avatars': [],
        'invite_quota': 3,
        'invites_used': 1,
        'invites_remaining': 2,
        'invites_unlimited': False,
        'smtp_enabled': False,
        'ok': True,
        'error': None,
        'error_code': None,
        'success': True,
    }
    assert response.content.endswith(b'\n')
    assert response.content.startswith(b'{"avatar_path":')
    head = _run(runtime, '/api/account/summary', cookie=_signed_session(), method='HEAD')
    assert head.status_code == 200
    assert head.content == b''
    assert head.headers['content-length'] == str(len(response.content))


def test_lazy_asgi_dispatches_rom_translate_capabilities_to_native_admin_route(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch, admin=True)
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('native ROM translate route pushed a Flask app context')
    )

    response = _run(
        runtime, '/api/rom-translate/capabilities', cookie=_signed_session(),
    )

    assert response.status_code == 200
    assert response.json()['offline_enabled'] is False
    assert response.json()['platforms']
    assert 'ok' not in response.json()
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_lazy_asgi_dispatches_loading_icon_admin_read_and_put(monkeypatch):
    payload = {
        'loading_icon_mode': 'rotate', 'loading_icon_id': None, 'resolved_id': None,
        'catalogue': [{'id': 'dpad'}], 'defaults': {'loading_icon_mode': 'rotate'},
        'modes': ['lock', 'rotate'], 'stored_mode': 'rotate', 'stored_id': None,
    }
    fake = SimpleNamespace(
        public=lambda: {
            'loading_icon_mode': 'rotate', 'loading_icon_id': None,
            'resolved_id': None, 'catalogue': [{'id': 'dpad'}],
        },
        get=lambda: payload,
        save=lambda body: {**payload, 'loading_icon_mode': body['loading_icon_mode']},
    )
    monkeypatch.setattr(loading_icon_admin, 'LoadingIconAdminData', lambda: fake)
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    public = _run(runtime, '/api/loading-icon')
    assert public.status_code == 200
    assert public.json()['catalogue'] == [{'id': 'dpad'}]
    response = _run(runtime, '/api/admin/loading-icon/config', cookie=_signed_session())
    assert response.status_code == 200
    assert response.json() == payload

    cookie, csrf = _signed_session_with_csrf()

    async def perform_put():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.put(
                '/api/admin/loading-icon/config',
                json={'loading_icon_mode': 'lock'},
                headers={'X-CSRFToken': csrf},
            )

    saved = asyncio.run(perform_put())
    assert saved.status_code == 200
    assert saved.json()['status'] == 'saved'
    assert saved.headers['x-content-type-options'] == 'nosniff'


def test_lazy_asgi_dispatches_browser_account_invites_without_flask(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    response = _run(runtime, '/api/account/invites', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json() == {
        'invites': [{
            'token': 'opaque-invite-token',
            'email': 'friend@example.test',
            'url': 'https://games.example.test/invite/opaque-invite-token',
            'created_at': None,
            'expires_at': None,
            'expired': False,
        }],
        'quota': 3,
        'remaining': 2,
        'unlimited': False,
        'smtp_enabled': False,
        'ttl_hours': 48,
        'site_url_configured': True,
        'ok': True,
        'error': None,
        'error_code': None,
        'success': True,
    }
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert response.content.endswith(b'\n')
    assert response.content.startswith(b'{"error":')
    head = _run(runtime, '/api/account/invites', cookie=_signed_session(), method='HEAD')
    assert head.status_code == 200
    assert head.content == b''
    assert head.headers['content-length'] == str(len(response.content))


def test_account_invite_post_rejects_missing_csrf_before_flask_compatibility(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    flask_app.before_request_funcs[None] = []

    async def perform_post():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', _signed_session())
            return await client.post('/api/account/invites', json={'email': 'friend@example.test'})

    response = asyncio.run(perform_post())
    assert response.status_code == 400
    assert response.json()['error'] == 'The CSRF token is missing.'


def test_lazy_asgi_dispatches_invite_creation_with_csrf_without_flask(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    cookie, csrf = _signed_session_with_csrf()

    async def perform_post():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.post(
                '/api/account/invites',
                json={'email': 'friend@example.test'},
                headers={'X-CSRFToken': csrf},
            )

    response = asyncio.run(perform_post())
    assert response.status_code == 201
    assert response.json()['invite'] == {
        'token': 'created-invite', 'email': 'friend@example.test'
    }
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_lazy_asgi_dispatches_invite_delete_with_csrf_without_flask(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    cookie, csrf = _signed_session_with_csrf()

    async def perform_delete():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.delete(
                '/api/account/invites/opaque-token', headers={'X-CSRFToken': csrf}
            )

    response = asyncio.run(perform_delete())
    assert response.status_code == 200
    assert response.json()['revoked'] == 'opaque-token'
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_lazy_asgi_dispatches_account_preferences_read_without_flask(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    asyncio.run(runtime._ensure_flask())
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('Flask app context used')
    )

    response = _run(runtime, '/api/account/preferences', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json()['preferences'] == {'theme': 'default', 'tile_size': '50'}
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_lazy_asgi_dispatches_account_preferences_write_with_csrf_without_flask(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    cookie, csrf = _signed_session_with_csrf()

    async def perform_put():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.put(
                '/api/account/preferences',
                json={'tile_size': '72'},
                headers={'X-CSRFToken': csrf},
            )

    response = asyncio.run(perform_put())
    assert response.status_code == 200
    assert response.json()['preferences']['tile_size'] == '72'
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_lazy_asgi_dispatches_stock_avatar_write_with_csrf_without_flask(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    asyncio.run(runtime._ensure_flask())
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('Flask app context used')
    )
    cookie, csrf = _signed_session_with_csrf()

    async def perform_post():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.post(
                '/api/account/avatar/stock',
                json={'id': 'oneirodex'},
                headers={'X-CSRFToken': csrf},
            )

    response = asyncio.run(perform_post())
    assert response.status_code == 200
    assert response.json()['avatar_path'] == '/static/avatars/oneirodex.svg'
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_lazy_asgi_dispatches_calendar_read_without_flask_or_provider_call(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    monkeypatch.setattr(
        flask_app,
        'app_context',
        lambda: (_ for _ in ()).throw(AssertionError('Flask app context used')),
    )

    response = _run(runtime, '/api/calendar?days_ahead=30', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json()['releases'] == [{'name': 'Fixture release'}]
    assert response.json()['days_ahead'] == 30
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_lazy_asgi_dispatches_personal_tokens_read_without_flask(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    monkeypatch.setattr(
        flask_app,
        'app_context',
        lambda: (_ for _ in ()).throw(AssertionError('Flask app context used')),
    )

    response = _run(runtime, '/api/tokens', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json()['tokens'] == []
    assert response.json()['valid_scopes']
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_lazy_asgi_dispatches_personal_token_writes_without_flask(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    monkeypatch.setattr(
        flask_app,
        'app_context',
        lambda: (_ for _ in ()).throw(AssertionError('Flask app context used')),
    )
    cookie, csrf = _signed_session_with_csrf()

    async def perform_writes():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            invalid_create = await client.post(
                '/api/tokens', json={}, headers={'X-CSRFToken': csrf}
            )
            deleted = await client.delete(
                '/api/tokens/19', headers={'X-CSRFToken': csrf}
            )
            return invalid_create, deleted

    invalid_create, deleted = asyncio.run(perform_writes())
    assert invalid_create.status_code == 422
    assert deleted.status_code == 200
    assert deleted.json()['ok'] is True


def test_lazy_asgi_dispatches_avatar_upload_without_flask(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    asyncio.run(runtime._ensure_flask())
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('Flask app context used')
    )
    cookie, csrf = _signed_session_with_csrf()

    async def perform_upload():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.post(
                '/api/account/avatar',
                files={'avatar': ('member.png', b'fake-image', 'image/png')},
                headers={'X-CSRFToken': csrf},
            )

    response = asyncio.run(perform_upload())
    assert response.status_code == 200
    assert response.json()['avatar_path'] == 'library/images/avatars_users/member.png'
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_lazy_asgi_dispatches_password_change_without_flask(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    cookie, csrf = _signed_session_with_csrf()

    async def perform_change():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.post(
                '/api/account/password',
                json={
                    'current_password': 'OldPassword1!',
                    'new_password': 'NewPassword2!',
                    'confirm_password': 'NewPassword2!',
                },
                headers={'X-CSRFToken': csrf},
            )

    response = asyncio.run(perform_change())
    assert response.status_code == 200
    assert response.json()['changed'] is True
    assert response.cookies.get('remember_token')
    assert response.headers['x-content-type-options'] == 'nosniff'


@pytest.mark.parametrize(
    ('path', 'expected'),
    [
        ('/api/client/capabilities?device_kind=browser', {'device_kind': 'browser'}),
        ('/api/client/lifecycle', {'records': [{'game_uuid': 'game-7', 'state': 'installed'}]}),
    ],
)
def test_lazy_asgi_dispatches_client_reads_without_flask(monkeypatch, path, expected):
    flask_app, runtime = _runtime(monkeypatch)
    asyncio.run(runtime._ensure_flask())
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('Flask app context used')
    )

    response = _run(runtime, path, cookie=_signed_session())

    assert response.status_code == 200
    payload = response.json()
    assert all(payload[key] == value for key, value in expected.items())
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_lazy_asgi_dispatches_lifecycle_write_without_flask(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)

    async def perform():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', _signed_session())
            return await client.post('/api/client/lifecycle', json={'records': []})

    response = asyncio.run(perform())
    assert response.status_code == 403
    assert response.json()['error'] == 'Companion API token required'
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_lazy_asgi_dispatches_heartbeat_write_without_flask(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    cookie, csrf = _signed_session_with_csrf()

    async def perform():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.post(
                '/api/client/heartbeat',
                json={'device_id': 'fixture-device'},
                headers={'X-CSRFToken': csrf},
            )

    response = asyncio.run(perform())
    assert response.status_code == 200
    assert response.json() == {'device_id': 'fixture-device', 'commands': []}
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_lazy_asgi_dispatches_client_command_post_without_flask(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    cookie, csrf = _signed_session_with_csrf()

    async def perform():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.post(
                '/api/client/commands',
                json={'action': 'open_path', 'path': 'fixture.rom'},
                headers={'X-CSRFToken': csrf},
            )

    response = asyncio.run(perform())
    assert response.status_code == 403
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_lazy_asgi_admin_can_dispatch_unmatched_open_path(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()

    async def perform():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.post(
                '/api/client/commands',
                json={'action': 'open_path', 'path': r'C:\library\unmatched'},
                headers={'X-CSRFToken': csrf},
            )

    response = asyncio.run(perform())
    assert response.status_code == 201
    assert response.json()['command']['id'] == 'command-outer'


@pytest.mark.parametrize('action', ['ack', 'nack'])
def test_lazy_asgi_dispatches_client_command_ack_routes_without_flask(monkeypatch, action):
    _flask_app, runtime = _runtime(monkeypatch)

    async def post():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', _signed_session())
            return await client.post(f'/api/client/commands/{action}', json={'ids': []})

    response = asyncio.run(post())
    assert response.status_code == 403
    assert response.json()['error'] == 'Companion API token required'


def test_lazy_asgi_dispatches_announcements_read_without_flask(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    monkeypatch.setattr(
        flask_app,
        'app_context',
        lambda: (_ for _ in ()).throw(AssertionError('Flask app context used')),
    )
    response = _run(runtime, '/api/announcements', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json() == {
        'announcements': [{'id': 3, 'title': 'Fixture announcement'}],
        'empty': False,
    }


def test_lazy_asgi_admin_can_request_announcement_drafts(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    response = _run(
        runtime, '/api/announcements?include_drafts=1', cookie=_signed_session()
    )

    assert response.status_code == 200
    assert response.json()['announcements']


def test_lazy_asgi_dispatches_announcement_create_without_flask(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch, admin=True)
    monkeypatch.setattr(
        flask_app,
        'app_context',
        lambda: (_ for _ in ()).throw(AssertionError('Flask app context used')),
    )
    cookie, csrf = _signed_session_with_csrf()

    async def perform_create():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.post(
                '/api/announcements',
                json={'title': 'Maintenance', 'body': 'Tonight'},
                headers={'X-CSRFToken': csrf},
            )

    response = asyncio.run(perform_create())
    assert response.status_code == 201
    assert response.json() == {
        'id': 4, 'title': 'Maintenance', 'body': 'Tonight', 'published': True,
    }


def test_announcement_validation_and_csrf_errors_need_no_flask_context(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch, admin=True)
    monkeypatch.setattr(
        flask_app,
        'app_context',
        lambda: (_ for _ in ()).throw(AssertionError('Flask app context used')),
    )
    cookie, csrf = _signed_session_with_csrf()

    async def send(payload, *, with_csrf=True):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            headers = {'X-CSRFToken': csrf} if with_csrf else {}
            return await client.post('/api/announcements', json=payload, headers=headers)

    invalid = asyncio.run(send({'title': ''}))
    assert invalid.status_code == 422
    assert invalid.json()['error'] == 'Invalid request.'

    no_csrf = asyncio.run(send({'title': 'Maintenance', 'body': 'Tonight'}, with_csrf=False))
    assert no_csrf.status_code == 400
    assert no_csrf.json()['error']


@pytest.mark.parametrize(
    ('path', 'expected'),
    [
        ('/api/news/gaming?limit=999&limit=2', {'items': [{'title': 'Fixture headline'}]}),
        ('/api/news/free-games?store=epic&store=steam&limit=999', {'items': [{'id': 'offer-1'}]}),
    ],
)
def test_lazy_asgi_dispatches_news_feeds_without_provider_network(monkeypatch, path, expected):
    _flask_app, runtime = _runtime(monkeypatch)
    response = _run(runtime, path, cookie=_signed_session())

    assert response.status_code == 200
    payload = response.json()
    assert all(payload[key] == value for key, value in expected.items())
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_news_feed_routes_do_not_push_flask_app_context(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    asyncio.run(runtime._ensure_flask())
    monkeypatch.setattr(
        flask_app, 'app_context',
        lambda: (_ for _ in ()).throw(AssertionError('Flask app context used')),
    )

    response = _run(runtime, '/api/news/gaming', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json()['items'] == [{'title': 'Fixture headline'}]


def test_lazy_asgi_dispatches_free_game_claim_assist_with_csrf_and_feature_gate(monkeypatch):
    fake = FakeNewsFeedData()
    flask_app, runtime = _runtime(monkeypatch)
    monkeypatch.setattr(news_feeds, 'NewsFeedData', lambda: fake)
    cookie, csrf = _signed_session_with_csrf()
    headers = {'X-CSRFToken': csrf}
    claimed = _run(
        runtime, '/api/news/free-games/12/claim-assist', cookie=cookie,
        method='POST', headers=headers,
    )
    missing = _run(
        runtime, '/api/news/free-games/404/claim-assist', cookie=cookie,
        method='POST', headers=headers,
    )
    failed = _run(
        runtime, '/api/news/free-games/409/claim-assist', cookie=cookie,
        method='POST', headers=headers,
    )
    no_csrf = _run(
        runtime, '/api/news/free-games/13/claim-assist', cookie=cookie,
        method='POST',
    )

    assert claimed.status_code == 200
    assert claimed.json() == {
        'ok': True, 'success': True, 'error': None,
        'error_code': None, 'claimed': True, 'offer_id': 12,
    }
    assert missing.status_code == 404
    assert failed.status_code == 400 and failed.json()['error'] == 'Store is not connected'
    assert no_csrf.status_code == 400
    assert fake.calls == [('claim', 12, 7), ('claim', 404, 7), ('claim', 409, 7)]

    flask_app.config['ENABLE_FREE_GAMES'] = False
    disabled = _run(
        runtime, '/api/news/free-games/14/claim-assist', cookie=cookie,
        method='POST', headers=headers,
    )
    assert disabled.status_code == 403
    assert len(fake.calls) == 3


def test_free_game_claim_assist_requires_write_scope_for_bearer(monkeypatch):
    runtime, read_only = _bearer_runtime(monkeypatch, ['read:library'])
    denied = _run(
        runtime, '/api/news/free-games/12/claim-assist', method='POST',
        headers={'Authorization': read_only},
    )
    assert denied.status_code == 403
    assert runtime._fake_news.calls == []

    runtime, writable = _bearer_runtime(
        monkeypatch, ['read:library', 'write:library'],
    )
    allowed = _run(
        runtime, '/api/news/free-games/12/claim-assist', method='POST',
        headers={'Authorization': writable},
    )
    assert allowed.status_code == 200
    assert runtime._fake_news.calls == [('claim', 12, 7)]


def test_native_api_unmatched_route_keeps_shared_json_error_envelope(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)

    response = _run(
        runtime, '/api/account/invites/one/extra', cookie=_signed_session()
    )

    assert response.status_code == 404
    assert response.headers['content-type'].startswith('application/json')
    assert response.json()['ok'] is False
    assert response.json()['error_code'] == 'not_found'
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_native_api_unhandled_failure_is_sanitized_and_enveloped(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    asyncio.run(runtime._ensure_flask())

    def fail():
        raise RuntimeError('private database path')

    runtime._native_read_api_app.add_api_route(
        '/api/account/invites/raise', fail, methods=['GET']
    )
    async def perform():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=runtime, raise_app_exceptions=False
            ),
            base_url='http://testserver',
        ) as client:
            client.cookies.set('session', _signed_session())
            return await client.get('/api/account/invites/raise')

    response = asyncio.run(perform())

    assert response.status_code == 500
    assert response.json()['error_code'] == 'internal'
    assert response.json()['error'] == 'Something went wrong on our end. The error has been logged.'
    assert 'private database path' not in response.text
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_lazy_asgi_dispatches_collection_reads_without_flask(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    listing = _run(runtime, '/api/collections', cookie=_signed_session())
    detail = _run(runtime, '/api/collections/collection-1', cookie=_signed_session())

    assert listing.status_code == 200
    assert listing.json()['collections'][0]['name'] == 'Fixture shelf'
    assert detail.status_code == 200
    assert detail.json()['items'] == [{'game_uuid': 'game-1'}]
    assert detail.headers['x-content-type-options'] == 'nosniff'


def test_collection_missing_detail_uses_not_found_envelope_without_flask(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    asyncio.run(runtime._ensure_flask())
    monkeypatch.setattr(
        flask_app, 'app_context',
        lambda: (_ for _ in ()).throw(AssertionError('Flask app context used')),
    )
    response = _run(runtime, '/api/collections/missing', cookie=_signed_session())

    assert response.status_code == 404
    assert response.json()['error_code'] == 'not_found'
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_lazy_asgi_dispatches_ownership_provider_capabilities_natively(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)

    response = _run(
        runtime, '/api/ownership/providers', cookie=_signed_session()
    )
    head = _run(
        runtime, '/api/ownership/providers', cookie=_signed_session(), method='HEAD'
    )
    anonymous = _run(runtime, '/api/ownership/providers')
    connections = _run(
        runtime, '/api/ownership/connections', cookie=_signed_session()
    )
    summary = _run(runtime, '/api/ownership', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json()['ok'] is True
    assert response.json()['schema_version'] == 1
    assert response.json()['providers'][0]['id'] == 'steam'
    assert 'x-content-type-options' in response.headers
    assert head.status_code == 200 and head.content == b''
    assert anonymous.status_code == 302
    assert connections.status_code == 200
    assert connections.json()['connections'][0]['store'] == 'steam'
    assert summary.status_code == 200
    assert summary.json()['connected'] == ['steam']


def test_native_ownership_review_reads_validate_cursor_and_preserve_visibility(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)

    titles = _run(
        runtime,
        '/api/ownership/titles?after_id=4&status=needs_review',
        cookie=_signed_session(),
    )
    candidates = _run(
        runtime,
        '/api/ownership/titles/5/candidates',
        cookie=_signed_session(),
    )
    bad_cursor = _run(
        runtime, '/api/ownership/titles?after_id=-1', cookie=_signed_session()
    )
    bad_status = _run(
        runtime, '/api/ownership/titles?status=unknown', cookie=_signed_session()
    )

    assert titles.status_code == 200
    assert titles.json()['titles'][0]['name'] == 'Fixture title'
    assert candidates.status_code == 200
    assert candidates.json()['candidates'][0]['game_uuid'] == 'visible-game'
    assert bad_cursor.status_code == 400
    assert bad_cursor.json()['error_code'] == 'bad_request'
    assert bad_status.status_code == 400
    assert bad_status.json()['error_code'] == 'bad_request'


def test_native_ownership_match_decisions_keep_csrf_revision_and_undo(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    cookie, csrf_token = _signed_session_with_csrf()
    headers = {'X-CSRFToken': csrf_token}

    no_csrf = _run(
        runtime, '/api/ownership/titles/5/match', method='POST',
        cookie=cookie, json_body={'expected_revision': 2, 'game_uuid': 'game-1'},
    )
    matched = _run(
        runtime, '/api/ownership/titles/5/match', method='POST', cookie=cookie,
        headers=headers, json_body={'expected_revision': 2, 'game_uuid': 'game-1'},
    )
    undone = _run(
        runtime, '/api/ownership/titles/5/match/undo', method='POST', cookie=cookie,
        headers=headers, json_body={'expected_revision': 2},
    )
    conflict = _run(
        runtime, '/api/ownership/titles/5/match', method='POST', cookie=cookie,
        headers=headers, json_body={'expected_revision': 1, 'game_uuid': None},
    )

    assert no_csrf.status_code == 400
    assert matched.status_code == 200 and matched.json()['match_revision'] == 3
    assert undone.status_code == 200 and undone.json()['match_revision'] == 3
    assert conflict.status_code == 409
    assert runtime._fake_ownership.decisions.count(('rollback',)) == 1


@pytest.mark.parametrize(
    ('path', 'body'),
    [
        ('/api/ownership/titles/5/match', {'expected_revision': 2, 'game_uuid': 'game-1'}),
        ('/api/ownership/gog/sync/cancel', {}),
    ],
)
def test_native_read_only_bearer_cannot_mutate_ownership_review_or_sync(monkeypatch, path, body):
    runtime, authorization = _bearer_runtime(monkeypatch, ['read:library'])
    response = _run(
        runtime, path, method='POST', json_body=body,
        headers={'Authorization': authorization},
    )

    assert response.status_code == 403
    assert response.json()['error'] == 'Bearer token requires write:library scope'
    assert runtime._fake_ownership.decisions == []


def test_native_ownership_sync_cancel_requires_csrf_and_returns_accepted_job(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    cookie, csrf_token = _signed_session_with_csrf()

    no_csrf = _run(
        runtime, '/api/ownership/gog/sync/cancel', method='POST', cookie=cookie,
    )
    response = _run(
        runtime, '/api/ownership/gog/sync/cancel', method='POST', cookie=cookie,
        headers={'X-CSRFToken': csrf_token},
    )

    assert no_csrf.status_code == 400
    assert response.status_code == 202
    assert response.json()['job']['cancel_requested'] is True


def test_native_emulator_reads_preserve_supported_and_unsupported_platform_contracts(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)

    all_emulators = _run(runtime, '/api/emulators', cookie=_signed_session())
    platform = _run(runtime, '/api/emulators/NES', cookie=_signed_session())
    unsupported = _run(runtime, '/api/emulators/UNKNOWN', cookie=_signed_session())
    anonymous = _run(runtime, '/api/emulators', method='GET')

    assert all_emulators.status_code == 200
    assert all_emulators.json()['emulators'] == ['retroarch']
    assert platform.status_code == 200
    assert platform.json()['preferred'] == 'nestopia'
    assert unsupported.status_code == 404
    assert unsupported.json()['error_code'] == 'not_found'
    assert anonymous.status_code == 302


def test_native_path_availability_keeps_auth_boundary_and_allowed_root_policy(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)

    anonymous = _run(runtime, '/api/check_path_availability?full_disk_path=/allowed/existing.bin')
    missing = _run(runtime, '/api/check_path_availability', cookie=_signed_session())
    outside = _run(
        runtime, '/api/check_path_availability?full_disk_path=/etc/passwd',
        cookie=_signed_session(),
    )
    existing = _run(
        runtime,
        '/api/check_path_availability?full_disk_path=%2Fallowed%2Fexisting.bin',
        cookie=_signed_session(),
    )
    absent = _run(
        runtime,
        '/api/check_path_availability?full_disk_path=%2Fallowed%2Fmissing.bin',
        cookie=_signed_session(),
    )

    assert anonymous.status_code == 302
    assert missing.status_code == 400
    assert missing.json()['available'] is False
    assert outside.status_code == 403
    assert outside.json()['available'] is False
    assert existing.status_code == 200
    assert existing.json() == {'available': True}
    assert absent.status_code == 200
    assert absent.json() == {'available': False}
    assert runtime._fake_path_check.calls == [
        ('validate', '/etc/passwd', ['/allowed']),
        ('validate', '/allowed/existing.bin', ['/allowed']),
        ('exists', '/allowed/existing.bin'),
        ('validate', '/allowed/missing.bin', ['/allowed']),
        ('exists', '/allowed/missing.bin'),
    ]


def test_path_validator_uses_explicit_logger_without_flask_context(monkeypatch):
    from flask import has_app_context
    from oneirodex.utils import security

    class FakePath:
        def __init__(self, value):
            self.value = value

        def resolve(self, strict=False):
            if self.value == '/invalid-base':
                raise ValueError('invalid base')
            return self

        def relative_to(self, _base):
            raise ValueError('outside')

    monkeypatch.setattr(security, 'Path', FakePath)

    messages = []
    logger = SimpleNamespace(warning=messages.append)
    safe, message = security.is_safe_path(
        '/allowed/file.bin', ['/invalid-base'], logger=logger,
    )

    assert not has_app_context()
    assert safe is False
    assert message == 'Access denied - path outside allowed directories'
    assert len(messages) == 1


def test_native_file_type_crud_preserves_admin_csrf_and_validation(monkeypatch):
    _flask_app, member_runtime = _runtime(monkeypatch)
    denied = _run(
        member_runtime, '/api/file_types/allowed', cookie=_signed_session(),
    )

    _flask_app, admin_runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf_token = _signed_session_with_csrf()
    headers = {'X-CSRFToken': csrf_token}
    listed = _run(admin_runtime, '/api/file_types/allowed', cookie=cookie)
    no_csrf = _run(
        admin_runtime, '/api/file_types/allowed', method='POST', cookie=cookie,
        json_body={'value': 'msi'},
    )
    created = _run(
        admin_runtime, '/api/file_types/allowed', method='POST', cookie=cookie,
        headers=headers, json_body={'value': '.MSI'},
    )
    invalid = _run(
        admin_runtime, '/api/file_types/allowed', method='POST', cookie=cookie,
        headers=headers, json_body={'value': '../bad'},
    )
    updated = _run(
        admin_runtime, '/api/file_types/allowed', method='PUT', cookie=cookie,
        headers=headers, json_body={'id': 1, 'value': 'tar.gz'},
    )
    deleted = _run(
        admin_runtime, '/api/file_types/allowed', method='DELETE', cookie=cookie,
        headers=headers, json_body={'id': 1},
    )

    assert denied.status_code == 302
    assert listed.status_code == 200
    assert listed.json() == [{'id': 1, 'value': 'exe'}]
    assert no_csrf.status_code == 400
    assert created.status_code == 201
    assert created.json() == {'id': 2, 'value': 'msi'}
    assert invalid.status_code == 400
    assert invalid.json()['error'] == 'Invalid file type format'
    assert updated.status_code == 200
    assert updated.json() == {'id': 1, 'value': 'tar.gz'}
    assert deleted.status_code == 200
    assert deleted.json()['success'] is True
    assert admin_runtime._fake_file_types.calls == [
        ('create', 'allowed', 'msi'),
        ('update', 'allowed', 1, 'tar.gz'),
        ('delete', 'allowed', 1),
    ]


def test_native_emulator_profile_admin_read_and_save_require_admin_and_csrf(monkeypatch):
    _flask_app, member_runtime = _runtime(monkeypatch)
    denied = _run(
        member_runtime, '/api/emulator-profiles', cookie=_signed_session()
    )

    _flask_app, admin_runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf_token = _signed_session_with_csrf()
    headers = {'X-CSRFToken': csrf_token}
    profiles = _run(
        admin_runtime, '/api/emulator-profiles', cookie=cookie
    )
    no_csrf = _run(
        admin_runtime, '/api/emulator-profiles', method='PUT', cookie=cookie,
        json_body={'NES': 'nestopia'},
    )
    saved = _run(
        admin_runtime, '/api/emulator-profiles', method='PUT', cookie=cookie,
        headers=headers, json_body={'NES': 'nestopia'},
    )

    assert denied.status_code == 302
    assert profiles.status_code == 200
    assert profiles.json()['profiles']['NES'] == 'nestopia'
    assert no_csrf.status_code == 400
    assert saved.status_code == 200
    assert saved.json()['profiles']['NES'] == 'nestopia'
    assert admin_runtime._fake_emulator.saved == [{'NES': 'nestopia'}]


def test_native_browser_player_settings_preserve_admin_csrf_and_validation(monkeypatch):
    _flask_app, member_runtime = _runtime(monkeypatch)
    denied = _run(
        member_runtime, '/api/browser-player-settings', cookie=_signed_session()
    )

    _flask_app, admin_runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf_token = _signed_session_with_csrf()
    headers = {'X-CSRFToken': csrf_token}
    settings = _run(
        admin_runtime, '/api/browser-player-settings', cookie=cookie
    )
    settings_head = _run(
        admin_runtime, '/api/browser-player-settings', method='HEAD', cookie=cookie
    )
    invalid = _run(
        admin_runtime, '/api/browser-player-settings', method='POST', cookie=cookie,
        headers=headers, json_body=['not', 'an', 'object'],
    )
    saved = _run(
        admin_runtime, '/api/browser-player-settings', method='PUT', cookie=cookie,
        headers=headers, json_body={'engine': 'webretro'},
    )

    assert denied.status_code == 302
    assert settings.status_code == 200 and settings.json()['engine'] == 'webretro'
    assert settings_head.status_code == 200 and settings_head.content == b''
    assert invalid.status_code == 400 and invalid.json()['error'] == 'JSON object required'
    assert saved.status_code == 200 and saved.json()['engine'] == 'webretro'


def test_lazy_asgi_dispatches_wishlist_list_without_flask(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    asyncio.run(runtime._ensure_flask())
    monkeypatch.setattr(
        flask_app, 'app_context',
        lambda: (_ for _ in ()).throw(AssertionError('Flask app context used')),
    )
    response = _run(runtime, '/api/requests?all=1', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json()['requests'] == [{'id': 23, 'title': 'Fixture request', 'all': False}]
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_collection_list_does_not_push_flask_app_context(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    asyncio.run(runtime._ensure_flask())
    monkeypatch.setattr(
        flask_app, 'app_context',
        lambda: (_ for _ in ()).throw(AssertionError('Flask app context used')),
    )

    response = _run(runtime, '/api/collections', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json()['collections'][0]['uuid'] == 'collection-1'


def test_librarian_wishlist_list_uses_first_all_query_value(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    response = _run(
        runtime, '/api/requests?all=1&all=0', cookie=_signed_session()
    )

    assert response.status_code == 200
    assert response.json()['requests'][0]['all'] is True


def test_native_notifications_read_keeps_first_query_values(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    monkeypatch.setattr(
        flask_app,
        'app_context',
        lambda: (_ for _ in ()).throw(AssertionError('Flask app context used')),
    )
    response = _run(
        runtime,
        '/api/notifications?unread=1&unread=0&limit=7&limit=99',
        cookie=_signed_session(),
    )

    assert response.status_code == 200
    assert response.json() == {'notifications': [], 'unread_count': 0, 'empty': True}
    assert runtime._fake_notifications.calls == [('list', 7, 7, True)]
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_native_notification_preferences_read_and_write(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    monkeypatch.setattr(
        flask_app,
        'app_context',
        lambda: (_ for _ in ()).throw(AssertionError('Flask app context used')),
    )
    read = _run(runtime, '/api/notifications/preferences', cookie=_signed_session())
    head = _run(runtime, '/api/notifications/preferences', cookie=_signed_session(), method='HEAD')
    cookie, csrf = _signed_session_with_csrf()

    async def save():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.post(
                '/api/notifications/preferences',
                json={'notify_chat': False}, headers={'X-CSRFToken': csrf},
            )

    written = asyncio.run(save())
    assert read.status_code == 200
    assert read.json()['email_digest_daily'] is False
    assert head.status_code == 200
    assert head.content == b''
    expected_head_body = flask_app.json.response({
        'ok': True, 'error': None, 'error_code': None, 'success': True,
    }).get_data()
    assert head.headers['content-length'] == str(len(expected_head_body))
    assert written.status_code == 200
    assert written.json()['ok'] is True
    assert runtime._fake_notifications.calls == [('preferences', {'notify_chat': False})]


def test_native_notification_preferences_match_legacy_internal_error_for_truthy_scalar_json(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    cookie, csrf = _signed_session_with_csrf()

    response = _run(
        runtime, '/api/notifications/preferences', cookie=cookie, method='POST',
        json_body=1, headers={'X-CSRFToken': csrf},
    )

    assert response.status_code == 500
    assert response.json()['error_code'] == 'internal'
    assert runtime._fake_notifications.calls == []


@pytest.mark.parametrize('json_body', [['notify_chat'], 'notify_chat'])
def test_native_notification_preferences_matches_legacy_membership_type_error(
    monkeypatch, json_body,
):
    _flask_app, runtime = _runtime(monkeypatch)
    cookie, csrf = _signed_session_with_csrf()

    response = _run(
        runtime, '/api/notifications/preferences', cookie=cookie, method='POST',
        json_body=json_body, headers={'X-CSRFToken': csrf},
    )

    assert response.status_code == 500
    assert response.json()['error_code'] == 'internal'
    assert runtime._fake_notifications.calls == []


@pytest.mark.parametrize('json_body', [[1], 'irrelevant'])
def test_native_notification_preferences_ignores_truthy_nonmatching_list_or_string(
    monkeypatch, json_body,
):
    _flask_app, runtime = _runtime(monkeypatch)
    cookie, csrf = _signed_session_with_csrf()

    response = _run(
        runtime, '/api/notifications/preferences', cookie=cookie, method='POST',
        json_body=json_body, headers={'X-CSRFToken': csrf},
    )

    assert response.status_code == 200
    assert response.json()['ok'] is True
    assert runtime._fake_notifications.calls == [('preferences', {})]


def test_native_notification_read_matches_legacy_internal_error_for_truthy_non_object_json(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    cookie, csrf = _signed_session_with_csrf()

    response = _run(
        runtime, '/api/notifications/read', cookie=cookie, method='POST',
        json_body=1, headers={'X-CSRFToken': csrf},
    )

    assert response.status_code == 500
    assert response.json()['error_code'] == 'internal'
    assert runtime._fake_notifications.calls == []


def test_native_admin_notification_bus_test_requires_csrf_and_uses_fake_adapter(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch, admin=True)
    monkeypatch.setattr(
        flask_app, 'app_context',
        lambda: (_ for _ in ()).throw(AssertionError('Flask app context used')),
    )
    cookie, csrf = _signed_session_with_csrf()

    async def calls():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver',
        ) as client:
            client.cookies.set('session', cookie)
            rejected = await client.post('/api/admin/notify-bus/test')
            accepted = await client.post(
                '/api/admin/notify-bus/test', headers={'X-CSRFToken': csrf},
            )
            return rejected, accepted

    rejected, accepted = asyncio.run(calls())
    assert rejected.status_code == 400
    assert accepted.status_code == 200
    assert accepted.json()['sent'] is True
    assert accepted.json()['configured'] is True
    assert runtime._fake_notifications.bus_calls == ['status', 'emit']


def test_native_member_chat_emoji_read_keeps_bare_payload_and_session_auth(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    monkeypatch.setattr(
        chat_emoji_read.ChatEmojiData, 'member_read',
        lambda _self: {'fixed': ['heart'], 'custom': [], 'max_custom': 24},
    )
    asyncio.run(runtime._ensure_flask())
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('Flask app context used')
    )

    response = _run(runtime, '/api/chat/emoji', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json() == {'fixed': ['heart'], 'custom': [], 'max_custom': 24}


def test_native_member_chat_channels_read_keeps_bare_payload_and_rooms_alias(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    calls = []

    def channels(_self, user):
        calls.append(user.id)
        return [{'id': 'general', 'name': 'General'}]

    monkeypatch.setattr(chat_reads.ChatReadData, 'channels', channels)
    asyncio.run(runtime._ensure_flask())
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('Flask app context used')
    )

    response = _run(runtime, '/api/chat/channels', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json() == {
        'channels': [{'id': 'general', 'name': 'General'}],
        'rooms': [{'id': 'general', 'name': 'General'}],
    }
    assert calls == [7]


def test_native_chat_channel_create_requires_csrf_and_keeps_room_alias(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    calls = []

    def create_channel(_self, user, payload):
        calls.append((user.id, payload))
        return {'id': 9, 'name': payload['name'], 'muted': False, 'unread': 0}

    monkeypatch.setattr(chat_reads.ChatReadData, 'create_channel', create_channel)
    cookie, csrf = _signed_session_with_csrf()

    async def send(with_csrf):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver',
        ) as client:
            client.cookies.set('session', cookie)
            headers = {'X-CSRFToken': csrf} if with_csrf else {}
            return await client.post('/api/chat/channels', json={'name': 'Family'}, headers=headers)

    rejected = asyncio.run(send(False))
    accepted = asyncio.run(send(True))

    assert rejected.status_code == 400
    assert calls == [(7, {'name': 'Family'})]
    assert accepted.status_code == 201
    assert accepted.json()['channel'] == accepted.json()['room'] == {
        'id': 9, 'name': 'Family', 'muted': False, 'unread': 0,
    }


def test_native_chat_mute_requires_present_typed_value_and_csrf(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    calls = []

    def mute_channel(_self, user, channel_id, muted):
        calls.append((user.id, channel_id, muted))
        return muted

    monkeypatch.setattr(chat_reads.ChatReadData, 'mute_channel', mute_channel)
    cookie, csrf = _signed_session_with_csrf()

    async def send(payload, *, with_csrf=True):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver',
        ) as client:
            client.cookies.set('session', cookie)
            headers = {'X-CSRFToken': csrf} if with_csrf else {}
            return await client.post(
                '/api/chat/channels/15/mute', json=payload, headers=headers,
            )

    csrf_rejected = asyncio.run(send({'muted': False}, with_csrf=False))
    invalid = asyncio.run(send({'extra': True}))
    accepted = asyncio.run(send({'muted': False}))

    assert csrf_rejected.status_code == 400
    assert invalid.status_code == 422
    assert 'muted' in invalid.json()['detail']
    assert accepted.status_code == 200
    assert accepted.json()['muted'] is False
    assert calls == [(7, 15, False)]


def test_native_chat_archive_and_leave_use_scoped_csrf_routes(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    calls = []

    def channel_action(_self, user, channel_id, action):
        calls.append((user.id, channel_id, action))
        return {'channel_id': channel_id, 'archived': True} if action == 'archive' else {
            'channel_id': channel_id, 'left': True,
        }

    monkeypatch.setattr(chat_reads.ChatReadData, 'channel_action', channel_action)
    cookie, csrf = _signed_session_with_csrf()

    async def send(path, *, with_csrf=True):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver',
        ) as client:
            client.cookies.set('session', cookie)
            headers = {'X-CSRFToken': csrf} if with_csrf else {}
            return await client.post(path, headers=headers)

    rejected = asyncio.run(send('/api/chat/channels/18/archive', with_csrf=False))
    archived = asyncio.run(send('/api/chat/channels/18/archive'))
    left = asyncio.run(send('/api/chat/channels/21/leave'))

    assert rejected.status_code == 400
    assert archived.status_code == left.status_code == 200
    assert archived.json()['archived'] is True
    assert left.json()['left'] is True
    assert calls == [(7, 18, 'archive'), (7, 21, 'leave')]


def test_native_chat_dm_open_requires_csrf_and_keeps_not_found(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    calls = []

    def open_dm(_self, user, payload):
        calls.append((user.id, payload))
        if payload.get('username') == 'missing':
            return None
        return {'id': 38, 'kind': 'dm', 'name': 'Alex / Sam'}

    monkeypatch.setattr(chat_reads.ChatReadData, 'open_dm', open_dm)
    cookie, csrf = _signed_session_with_csrf()

    async def send(payload, *, with_csrf=True):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver',
        ) as client:
            client.cookies.set('session', cookie)
            headers = {'X-CSRFToken': csrf} if with_csrf else {}
            return await client.post('/api/chat/dm', json=payload, headers=headers)

    rejected = asyncio.run(send({'username': 'Sam'}, with_csrf=False))
    accepted = asyncio.run(send({'username': 'Sam'}))
    missing = asyncio.run(send({'username': 'missing'}))

    assert rejected.status_code == 400
    assert accepted.status_code == 200
    assert accepted.json()['channel'] == {'id': 38, 'kind': 'dm', 'name': 'Alex / Sam'}
    assert missing.status_code == 404
    assert missing.json()['error'] == 'User not found'
    assert calls == [(7, {'username': 'Sam'}), (7, {'username': 'missing'})]


def test_native_chat_message_post_requires_csrf_and_preserves_envelope(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    calls = []

    def post_message(_self, user, channel_id, payload):
        calls.append((user.id, channel_id, payload))
        return {'id': 48, 'body': payload.get('body'), 'user_id': user.id}

    monkeypatch.setattr(chat_reads.ChatReadData, 'post_message', post_message)
    cookie, csrf = _signed_session_with_csrf()

    async def send(*, with_csrf=True):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver',
        ) as client:
            client.cookies.set('session', cookie)
            headers = {'X-CSRFToken': csrf} if with_csrf else {}
            return await client.post(
                '/api/chat/channels/29/messages', json={'body': 'hello'}, headers=headers,
            )

    rejected = asyncio.run(send(with_csrf=False))
    accepted = asyncio.run(send())

    assert rejected.status_code == 400
    assert accepted.status_code == 201
    assert accepted.json()['message'] == {'id': 48, 'body': 'hello', 'user_id': 7}
    assert calls == [(7, 29, {'body': 'hello'})]


def test_native_chat_reaction_toggle_requires_csrf_and_maps_not_found(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    calls = []

    def toggle(_self, user, message_id, emoji):
        calls.append((user.id, message_id, emoji))
        return None if message_id == 999 else {'message_id': message_id, 'emoji': emoji}

    monkeypatch.setattr(chat_reads.ChatReadData, 'toggle_reaction', toggle)
    cookie, csrf = _signed_session_with_csrf()

    async def send(message_id, *, with_csrf=True):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver',
        ) as client:
            client.cookies.set('session', cookie)
            headers = {'X-CSRFToken': csrf} if with_csrf else {}
            return await client.post(
                f'/api/chat/messages/{message_id}/reactions',
                json={'emoji': 'heart'}, headers=headers,
            )

    rejected = asyncio.run(send(1, with_csrf=False))
    accepted = asyncio.run(send(1))
    missing = asyncio.run(send(999))

    assert rejected.status_code == 400
    assert accepted.status_code == 200
    assert accepted.json()['emoji'] == 'heart'
    assert missing.status_code == 404
    assert calls == [(7, 1, 'heart'), (7, 999, 'heart')]


def test_native_chat_attachment_download_preserves_private_cache_and_inline_rules(monkeypatch, tmp_path):
    _flask_app, runtime = _runtime(monkeypatch)
    image = tmp_path / 'cover.png'
    image.write_bytes(b'png-fixture')
    download = tmp_path / 'notes.txt'
    download.write_bytes(b'text-fixture')

    def attachment(_self, _user, file_name):
        if file_name == 'image.png':
            return image, 'image/png', 'Cover.png', False
        if file_name == 'notes.txt':
            return download, 'text/plain', 'Notes.txt', True
        return None

    monkeypatch.setattr(chat_reads.ChatReadData, 'attachment', attachment)
    cookie = _signed_session()

    image_response = _run(runtime, '/api/chat/attachments/image.png', cookie=cookie)
    file_response = _run(runtime, '/api/chat/attachments/notes.txt', cookie=cookie)
    missing = _run(runtime, '/api/chat/attachments/missing.txt', cookie=cookie)

    assert image_response.status_code == file_response.status_code == 200
    assert image_response.content == b'png-fixture'
    assert file_response.content == b'text-fixture'
    assert image_response.headers['cache-control'] == 'private, max-age=3600'
    assert 'inline' in image_response.headers.get('content-disposition', '')
    assert 'attachment' in file_response.headers.get('content-disposition', '')
    assert missing.status_code == 404
    assert missing.json()['error'] == 'Not found'


def test_native_chat_space_members_read_uses_member_acl_adapter(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    calls = []

    def space_members(_self, user, space_id):
        calls.append((user.id, space_id))
        return None if space_id == 99 else [{'user_id': 7, 'role': 'owner'}]

    monkeypatch.setattr(chat_reads.ChatReadData, 'space_members', space_members)
    asyncio.run(runtime._ensure_flask())
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('Flask app context used')
    )

    members = _run(runtime, '/api/chat/spaces/4/members', cookie=_signed_session())
    missing = _run(runtime, '/api/chat/spaces/99/members', cookie=_signed_session())

    assert members.status_code == 200
    assert members.json()['ok'] is True
    assert members.json()['members'] == [{'user_id': 7, 'role': 'owner'}]
    assert missing.status_code == 404
    assert calls == [(7, 4), (7, 99)]


def test_native_chat_space_invites_read_requires_admin(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch, admin=True)
    calls = []

    def space_invites(_self, space_id):
        calls.append(space_id)
        return [{'id': 3, 'space_id': space_id, 'revoked': False}]

    monkeypatch.setattr(chat_reads.ChatReadData, 'space_invites', space_invites)
    asyncio.run(runtime._ensure_flask())
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('Flask app context used')
    )
    response = _run(runtime, '/api/chat/spaces/4/invites', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json()['ok'] is True
    assert response.json()['invites'] == [{'id': 3, 'space_id': 4, 'revoked': False}]
    assert calls == [4]

    _member_app, member_runtime = _runtime(monkeypatch)
    denied = _run(
        member_runtime, '/api/chat/spaces/4/invites', cookie=_signed_session(),
    )
    assert denied.status_code == 302
    assert calls == [4]


def test_native_chat_space_member_writes_require_admin_csrf_and_validation(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    calls = []

    def add_space_member(_self, space_id, user_id, role):
        calls.append(('add', space_id, user_id, role))
        return None if space_id == 99 else {'user_id': user_id, 'role': role or 'member'}

    def remove_space_member(_self, space_id, user_id):
        calls.append(('remove', space_id, user_id))
        return None if space_id == 99 else True

    monkeypatch.setattr(chat_reads.ChatReadData, 'add_space_member', add_space_member)
    monkeypatch.setattr(chat_reads.ChatReadData, 'remove_space_member', remove_space_member)
    cookie, csrf = _signed_session_with_csrf()

    async def post(path, payload, *, with_csrf=True):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver',
        ) as client:
            client.cookies.set('session', cookie)
            headers = {'X-CSRFToken': csrf} if with_csrf else {}
            return await client.post(path, json=payload, headers=headers)

    async def delete(path, *, with_csrf=True):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver',
        ) as client:
            client.cookies.set('session', cookie)
            headers = {'X-CSRFToken': csrf} if with_csrf else {}
            return await client.delete(path, headers=headers)

    rejected = asyncio.run(post('/api/chat/spaces/4/members', {'user_id': 7}, with_csrf=False))
    invalid = asyncio.run(post('/api/chat/spaces/4/members', {'role': 'owner'}))
    added = asyncio.run(post('/api/chat/spaces/4/members', {'user_id': 7}))
    removed = asyncio.run(delete('/api/chat/spaces/4/members/7'))

    assert rejected.status_code == 400
    assert invalid.status_code == 422
    assert added.status_code == removed.status_code == 200
    assert added.json()['user_id'] == 7 and added.json()['role'] == 'member'
    assert removed.json()['removed'] is True
    assert calls == [
        ('add', 4, 7, None), ('remove', 4, 7),
    ]


def test_native_chat_space_create_requires_admin_csrf_and_valid_visibility(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    calls = []

    def create_space(_self, user, payload):
        calls.append((user.id, payload))
        return {'id': 5, 'name': payload['name'], 'visibility': payload['visibility']}

    monkeypatch.setattr(chat_reads.ChatReadData, 'create_space', create_space)
    cookie, csrf = _signed_session_with_csrf()

    async def send(payload, *, with_csrf=True):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver',
        ) as client:
            client.cookies.set('session', cookie)
            headers = {'X-CSRFToken': csrf} if with_csrf else {}
            return await client.post('/api/chat/spaces', json=payload, headers=headers)

    rejected = asyncio.run(send({'name': 'Circle'}, with_csrf=False))
    invalid = asyncio.run(send({'name': 'Circle', 'visibility': 'public'}))
    created = asyncio.run(send({'name': 'Circle', 'visibility': 'INVITE'}))

    assert rejected.status_code == 400
    assert invalid.status_code == 400
    assert created.status_code == 201
    assert created.json()['space'] == {
        'id': 5, 'name': 'Circle', 'visibility': 'invite',
    }
    assert calls == [(7, {'name': 'Circle', 'visibility': 'invite'})]


def test_native_chat_space_channel_create_requires_admin_and_keeps_voice_room(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    calls = []

    def create_space_channel(_self, user, space_id, payload):
        calls.append((user.id, space_id, payload))
        return {'id': 17, 'name': payload['name'], 'kind': 'voice', 'room': 'od-voice-17'}

    monkeypatch.setattr(chat_reads.ChatReadData, 'create_space_channel', create_space_channel)
    cookie, csrf = _signed_session_with_csrf()

    async def send(*, with_csrf=True):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver',
        ) as client:
            client.cookies.set('session', cookie)
            headers = {'X-CSRFToken': csrf} if with_csrf else {}
            return await client.post(
                '/api/chat/spaces/8/channels',
                json={'name': 'Voice', 'kind': 'voice'}, headers=headers,
            )

    rejected = asyncio.run(send(with_csrf=False))
    created = asyncio.run(send())

    assert rejected.status_code == 400
    assert created.status_code == 201
    assert created.json()['channel']['room'] == 'od-voice-17'
    assert calls == [(7, 8, {'name': 'Voice', 'kind': 'voice'})]


def test_native_chat_voice_room_read_uses_member_acl_adapter(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    calls = []

    def voice_room(_self, user, space_id, channel_id):
        calls.append((user.id, space_id, channel_id))
        return None if channel_id == 99 else {
            'room': 'od-voice-17', 'channel': {'id': channel_id, 'kind': 'voice'},
        }

    monkeypatch.setattr(chat_reads.ChatReadData, 'voice_room', voice_room)
    asyncio.run(runtime._ensure_flask())
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('Flask app context used')
    )

    response = _run(
        runtime, '/api/chat/spaces/8/voice/17/room', cookie=_signed_session(),
    )
    missing = _run(
        runtime, '/api/chat/spaces/8/voice/99/room', cookie=_signed_session(),
    )

    assert response.status_code == 200
    assert response.json()['room'] == 'od-voice-17'
    assert missing.status_code == 404
    assert calls == [(7, 8, 17), (7, 8, 99)]


def test_native_chat_space_invite_create_revoke_and_join_keep_contracts(monkeypatch):
    _admin_app, admin_runtime = _runtime(monkeypatch, admin=True)
    create_calls = []
    revoke_calls = []

    def create_invite(_self, space_id, user_id, expires_at, max_uses):
        create_calls.append((space_id, user_id, expires_at, max_uses))
        return {'id': 45, 'token': 'one-time-token'}

    def revoke_invite(_self, invite_id):
        revoke_calls.append(invite_id)
        return invite_id == 45

    monkeypatch.setattr(chat_reads.ChatReadData, 'create_space_invite', create_invite)
    monkeypatch.setattr(chat_reads.ChatReadData, 'revoke_space_invite', revoke_invite)
    cookie, csrf = _signed_session_with_csrf()

    async def admin_post(path, payload=None, *, with_csrf=True):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=admin_runtime), base_url='http://testserver',
        ) as client:
            client.cookies.set('session', cookie)
            headers = {'X-CSRFToken': csrf} if with_csrf else {}
            return await client.post(path, json=payload, headers=headers)

    rejected = asyncio.run(admin_post('/api/chat/spaces/8/invites', {}, with_csrf=False))
    created = asyncio.run(admin_post(
        '/api/chat/spaces/8/invites', {'expires_in_hours': 3, 'max_uses': 2},
    ))
    revoked = asyncio.run(admin_post('/api/chat/spaces/invites/45/revoke'))

    assert rejected.status_code == 400
    assert created.status_code == 201
    assert created.json()['invite']['token'] == 'one-time-token'
    assert create_calls[0][0:2] == (8, 7)
    assert create_calls[0][2] is not None and create_calls[0][3] == 2
    assert revoked.status_code == 200
    assert revoke_calls == [45]

    _member_app, member_runtime = _runtime(monkeypatch)
    join_calls = []

    def join_space(_self, user, token):
        join_calls.append((user.id, token))
        return ({'id': 8, 'name': 'Household'}, None) if token == 'valid' else (None, 'Invalid invite')

    monkeypatch.setattr(chat_reads.ChatReadData, 'join_space', join_space)
    member_cookie, member_csrf = _signed_session_with_csrf()
    async def join(token):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=member_runtime), base_url='http://testserver',
        ) as client:
            client.cookies.set('session', member_cookie)
            return await client.post(
                '/api/chat/spaces/join', json={'token': token},
                headers={'X-CSRFToken': member_csrf},
            )

    joined = asyncio.run(join('valid'))
    invalid = asyncio.run(join('bad'))
    assert joined.status_code == 200 and joined.json()['space']['id'] == 8
    assert invalid.status_code == 400 and invalid.json()['error'] == 'Invalid invite'
    assert join_calls == [(7, 'valid'), (7, 'bad')]


def test_native_chat_custom_emoji_upload_and_delete_use_native_csrf(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch, admin=True)
    upload_calls = []
    delete_calls = []

    def upload_emoji(_self, user, *, slug, label, file, upload_folder):
        upload_calls.append((user.id, slug, label, file.filename, file.read(), upload_folder))
        return {'slug': slug, 'label': label, 'file_name': 'fixture.webp'}

    def delete_emoji(_self, slug, *, upload_folder):
        delete_calls.append((slug, upload_folder))
        return slug == 'happy'

    monkeypatch.setattr(chat_reads.ChatReadData, 'upload_emoji', upload_emoji)
    monkeypatch.setattr(chat_reads.ChatReadData, 'delete_emoji', delete_emoji)
    cookie, csrf = _signed_session_with_csrf()

    async def upload(with_csrf, file_bytes=b'fixture image'):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver',
        ) as client:
            client.cookies.set('session', cookie)
            headers = {'X-CSRFToken': csrf} if with_csrf else {}
            return await client.post(
                '/api/chat/emoji', data={'slug': 'happy', 'label': 'Happy'},
                files={'file': ('happy.png', file_bytes, 'image/png')}, headers=headers,
            )

    async def delete(slug, with_csrf=True):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver',
        ) as client:
            client.cookies.set('session', cookie)
            headers = {'X-CSRFToken': csrf} if with_csrf else {}
            return await client.delete(f'/api/chat/emoji/{slug}', headers=headers)

    rejected = asyncio.run(upload(False))
    accepted = asyncio.run(upload(True))
    oversized = asyncio.run(upload(True, b'x' * (256 * 1024 + 64 * 1024 + 1)))
    deleted = asyncio.run(delete('happy'))
    missing = asyncio.run(delete('missing'))

    assert rejected.status_code == 400
    assert accepted.status_code == 201
    assert oversized.status_code == 413
    assert accepted.json()['emoji']['file_name'] == 'fixture.webp'
    assert deleted.status_code == 200
    assert missing.status_code == 404
    assert upload_calls == [(7, 'happy', 'Happy', 'happy.png', b'fixture image', None)]
    assert delete_calls == [('happy', None), ('missing', None)]


def test_native_admin_chat_emoji_upload_keeps_admin_payload_and_limits(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    calls = []

    class Row:
        def to_dict(self):
            return {'slug': 'party', 'file_name': 'party.webp'}

    def upload(_self, *, slug, label, file, uploader, upload_folder):
        calls.append((slug, label, file.filename, file.read(), uploader.id, upload_folder))
        return Row()

    monkeypatch.setattr(chat_emoji_read.ChatEmojiData, 'upload', upload)
    cookie, csrf = _signed_session_with_csrf()

    async def send(with_csrf):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver',
        ) as client:
            client.cookies.set('session', cookie)
            headers = {'X-CSRFToken': csrf} if with_csrf else {}
            return await client.post(
                '/api/admin/chat-emoji', data={'slug': 'party', 'label': 'Party'},
                files={'file': ('party.png', b'fixture', 'image/png')}, headers=headers,
            )

    rejected = asyncio.run(send(False))
    accepted = asyncio.run(send(True))

    assert rejected.status_code == 400
    assert accepted.status_code == 201
    assert accepted.json()['emoji'] == {'slug': 'party', 'file_name': 'party.webp'}
    assert accepted.json()['message'] == 'Custom emoji uploaded.'
    assert calls == [('party', 'Party', 'party.png', b'fixture', 7, None)]


def test_chat_storage_directories_accept_explicit_root_without_flask_context(tmp_path):
    from flask import has_app_context

    from oneirodex.utils.chat_attachments import attachments_dir
    from oneirodex.utils.custom_emoji import emoji_dir

    assert not has_app_context()
    assert emoji_dir(str(tmp_path)) == str(tmp_path / 'chat-emoji')
    assert attachments_dir(str(tmp_path)) == str(tmp_path / 'chat-attachments')


def test_native_chat_attachment_upload_preserves_limits_and_csrf(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    calls = []

    def upload_attachment(_self, user, channel_id, *, file, config):
        calls.append((user.id, channel_id, file.filename, file.read(), config.get('UPLOAD_FOLDER')))
        return {
            'attachment': {'id': 55, 'file_name': 'asset.webp'},
            'limits': {'max_bytes': 5242880, 'max_per_message': 5,
                       'max_total_bytes': None, 'max_total_files': None},
        }

    monkeypatch.setattr(chat_reads.ChatReadData, 'upload_attachment', upload_attachment)
    cookie, csrf = _signed_session_with_csrf()

    async def send(with_csrf):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver',
        ) as client:
            client.cookies.set('session', cookie)
            headers = {'X-CSRFToken': csrf} if with_csrf else {}
            return await client.post(
                '/api/chat/channels/29/attachments',
                files={'attachment': ('asset.webp', b'fixture bytes', 'image/webp')},
                headers=headers,
            )

    rejected = asyncio.run(send(False))
    accepted = asyncio.run(send(True))

    assert rejected.status_code == 400
    assert accepted.status_code == 201
    assert accepted.json()['attachment']['id'] == 55
    assert accepted.json()['limits']['max_per_message'] == 5
    assert calls == [(7, 29, 'asset.webp', b'fixture bytes', None)]


def test_native_chat_attachment_options_probe_matches_legacy_contract(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)

    async def options():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver',
        ) as client:
            return await client.options('/api/chat/channels/29/attachments')

    response = asyncio.run(options())

    assert response.status_code == 200
    assert response.headers['allow'] == 'OPTIONS, POST'


def test_native_layout_apis_preserve_member_and_admin_contracts(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch, admin=True)
    calls = []

    monkeypatch.setattr(layouts.LayoutData, 'get_admin', lambda _self: {'sections': ['hero']})
    monkeypatch.setattr(
        layouts.LayoutData, 'get_mine',
        lambda _self, user_id: {'layout': {'sections': ['summary']}, 'is_override': True},
    )

    def save_mine(_self, user_id, payload):
        calls.append(('save', user_id, payload))
        return {'layout': payload, 'is_override': True}

    def create_preset(_self, user_id, name, layout):
        calls.append(('preset', user_id, name, layout))
        return {'id': 3, 'name': name, 'layout': layout}

    monkeypatch.setattr(layouts.LayoutData, 'save_mine', save_mine)
    monkeypatch.setattr(layouts.LayoutData, 'create_preset', create_preset)
    asyncio.run(runtime._ensure_flask())
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('Flask app context used')
    )
    cookie, csrf = _signed_session_with_csrf()

    async def calls_api():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver',
        ) as client:
            client.cookies.set('session', cookie)
            admin = await client.get('/api/layouts/detail')
            mine = await client.get('/api/layouts/detail/mine')
            rejected = await client.put('/api/layouts/detail/mine', json={'sections': []})
            saved = await client.put(
                '/api/layouts/detail/mine', json={'sections': ['videos']},
                headers={'X-CSRFToken': csrf},
            )
            preset = await client.post(
                '/api/layouts/detail/presets',
                json={'name': 'Compact', 'layout': {'sections': ['hero']}},
                headers={'X-CSRFToken': csrf},
            )
            return admin, mine, rejected, saved, preset

    admin, mine, rejected, saved, preset = asyncio.run(calls_api())
    assert admin.status_code == mine.status_code == 200
    assert admin.json() == {'sections': ['hero']}
    assert mine.json() == {'layout': {'sections': ['summary']}, 'is_override': True}
    assert rejected.status_code == 400
    assert saved.status_code == 200 and saved.json()['is_override'] is True
    assert preset.status_code == 201 and preset.json()['id'] == 3
    assert calls == [
        ('save', 7, {'sections': ['videos']}),
        ('preset', 7, 'Compact', {'sections': ['hero']}),
    ]


def test_native_member_layout_write_requires_library_write_scope(monkeypatch):
    monkeypatch.setattr(
        layouts.LayoutData, 'save_mine',
        lambda _self, user_id, payload: {
            'layout': payload, 'is_override': user_id == 7,
        },
    )
    runtime, read_only = _bearer_runtime(monkeypatch, ['read:library'])
    denied = _run(
        runtime, '/api/layouts/detail/mine', method='PUT',
        json_body={'sections': ['videos']}, headers={'Authorization': read_only},
    )
    assert denied.status_code == 403

    runtime, writable = _bearer_runtime(
        monkeypatch, ['read:library', 'write:library'],
    )
    allowed = _run(
        runtime, '/api/layouts/detail/mine', method='PUT',
        json_body={'sections': ['videos']}, headers={'Authorization': writable},
    )
    assert allowed.status_code == 200, allowed.text


def test_native_member_chat_spaces_read_uses_native_adapter(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    calls = []

    def spaces(_self, user):
        calls.append(user.id)
        return [{'id': 12, 'name': 'Household', 'channels': [], 'voice_channels': []}]

    monkeypatch.setattr(chat_reads.ChatReadData, 'spaces', spaces)
    asyncio.run(runtime._ensure_flask())
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('Flask app context used')
    )

    response = _run(runtime, '/api/chat/spaces', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json()['ok'] is True
    assert response.json()['spaces'] == [
        {'id': 12, 'name': 'Household', 'channels': [], 'voice_channels': []},
    ]
    assert calls == [7]


def test_native_member_chat_messages_read_preserves_query_and_opaque_not_found(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    calls = []

    def messages(_self, user, channel_id, *, limit, before_id, since_id):
        calls.append((user.id, channel_id, limit, before_id, since_id))
        if channel_id != 44:
            return None
        return {'messages': [{'id': 12, 'text': 'hello'}], 'channel': {'id': 44}}

    monkeypatch.setattr(chat_reads.ChatReadData, 'messages', messages)
    asyncio.run(runtime._ensure_flask())
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('Flask app context used')
    )

    response = _run(
        runtime, '/api/chat/channels/44/messages?limit=150&before=19&since=bad',
        cookie=_signed_session(),
    )
    missing = _run(
        runtime, '/api/chat/channels/45/messages', cookie=_signed_session(),
    )
    invalid_limit = _run(
        runtime, '/api/chat/channels/44/messages?limit=many', cookie=_signed_session(),
    )

    assert response.status_code == 200
    assert response.json() == {
        'messages': [{'id': 12, 'text': 'hello'}], 'channel': {'id': 44},
    }
    assert missing.status_code == 404
    assert missing.json()['error'] == 'Not found'
    assert invalid_limit.status_code == 400
    assert invalid_limit.json()['error'] == 'limit must be an integer'
    assert calls == [(7, 44, 100, 19, None), (7, 45, 50, None, None)]


def test_native_member_chat_search_read_keeps_query_and_limit_contract(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    calls = []

    def search(_self, user, query, *, limit):
        calls.append((user.id, query, limit))
        return [{'channel_id': 3, 'message': 'found'}]

    monkeypatch.setattr(chat_reads.ChatReadData, 'search', search)
    asyncio.run(runtime._ensure_flask())
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('Flask app context used')
    )

    response = _run(
        runtime, '/api/chat/search?q=%20needle%20&limit=99', cookie=_signed_session(),
    )

    assert response.status_code == 200
    assert response.json() == {
        'results': [{'channel_id': 3, 'message': 'found'}], 'q': 'needle',
    }
    assert calls == [(7, 'needle', 50)]


def test_native_event_bus_test_requires_admin_csrf_and_returns_published_event(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch, admin=True)
    flask_app._fake_user.name = 'Fixture Admin'
    monkeypatch.setattr(
        flask_app, 'app_context',
        lambda: (_ for _ in ()).throw(AssertionError('Flask app context used')),
    )
    cookie, csrf = _signed_session_with_csrf()

    async def publish(with_csrf):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver',
        ) as client:
            client.cookies.set('session', cookie)
            headers = {'X-CSRFToken': csrf} if with_csrf else {}
            return await client.post('/api/events/publish_test', headers=headers)

    rejected = asyncio.run(publish(False))
    accepted = asyncio.run(publish(True))

    assert rejected.status_code == 400
    assert accepted.status_code == 200
    assert accepted.json() == {
        'type': 'test', 'message': 'ping', 'user': 'Fixture Admin',
    }
    assert runtime._fake_notifications.bus_calls == [('publish_event', 'Fixture Admin')]


def test_native_notifications_mark_read_normalizes_ids_and_uses_csrf(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    monkeypatch.setattr(
        flask_app,
        'app_context',
        lambda: (_ for _ in ()).throw(AssertionError('Flask app context used')),
    )
    cookie, csrf = _signed_session_with_csrf()

    async def mark():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.post(
                '/api/notifications/read',
                json={'ids': ['2', 'invalid', 4.0, None]},
                headers={'X-CSRFToken': csrf},
            )

    response = asyncio.run(mark())
    assert response.status_code == 200
    assert response.json()['marked'] == 2
    assert runtime._fake_notifications.calls == [('mark', 7, [2, 4], False)]


def test_native_notifications_enforce_bearer_social_scope(monkeypatch):
    runtime, authorization = _bearer_runtime(monkeypatch, ['read:library'])

    async def request_feed():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            return await client.get(
                '/api/notifications',
                headers={'Authorization': authorization},
            )

    response = asyncio.run(request_feed())
    assert response.status_code == 403
    assert response.json()['error'] == 'Missing scope: read:social'


def test_native_notification_bearer_write_uses_scope_instead_of_csrf(monkeypatch):
    runtime, authorization = _bearer_runtime(
        monkeypatch, ['read:social', 'write:social']
    )

    async def mark():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            return await client.post(
                '/api/notifications/read', json={'all': True},
                headers={'Authorization': authorization},
            )

    response = asyncio.run(mark())
    assert response.status_code == 200
    assert response.json()['ok'] is True
    assert response.json()['marked'] == 4


def test_native_notification_preferences_write_token_also_requires_read_scope(monkeypatch):
    runtime, authorization = _bearer_runtime(monkeypatch, ['write:social'])

    async def update_preferences():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            return await client.post(
                '/api/notifications/preferences',
                json={'share_activity': False},
                headers={'Authorization': authorization},
            )

    response = asyncio.run(update_preferences())

    assert response.status_code == 403
    assert response.json()['error'] == 'Missing scope: read:social'
    assert response.json()['detail'] == {'required_scope': 'read:social'}
    assert runtime._fake_notifications.calls == []


def test_native_wanted_update_list_without_flask(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    asyncio.run(runtime._ensure_flask())
    monkeypatch.setattr(
        flask_app, 'app_context',
        lambda: (_ for _ in ()).throw(AssertionError('Flask app context used')),
    )
    response = _run(runtime, '/api/updates/wanted', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json()['items'][0]['game_uuid'] == 'game-1'
    assert response.headers['x-content-type-options'] == 'nosniff'


@pytest.mark.parametrize(
    ('path', 'body', 'expected_key', 'expected_value'),
    [
        ('/api/updates/wanted', {'game_uuid': 'game-1', 'kind': 'dlc'}, 'item', 'wanted-new'),
        ('/api/updates/wanted/fulfill', {'game_uuid': 'game-1', 'kind': 'update'}, 'updated', 2),
    ],
)
def test_native_wanted_update_mutations_use_csrf_and_asgi_dispatch(
    monkeypatch, path, body, expected_key, expected_value,
):
    _flask_app, runtime = _runtime(monkeypatch)
    cookie, csrf = _signed_session_with_csrf()

    async def perform():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.post(path, json=body, headers={'X-CSRFToken': csrf})

    response = asyncio.run(perform())
    assert response.status_code == (201 if expected_key == 'item' else 200)
    if expected_key == 'item':
        assert response.json()['item']['id'] == expected_value
    else:
        assert response.json()[expected_key] == expected_value
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert runtime._fake_wanted.calls


def test_native_updates_inbox_preserves_first_query_values(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    response = _run(
        runtime,
        '/api/updates/inbox?limit=2&limit=999&library_uuid=library-a&library_uuid=library-b',
        cookie=_signed_session(),
    )

    assert response.status_code == 200
    assert response.json()['limit'] == 2
    assert runtime._fake_update_reads.calls == [('inbox', 7, 2, 'library-a')]


def test_native_update_reads_do_not_push_flask_context(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('native update read pushed a Flask app context')
    )

    inbox = _run(runtime, '/api/updates/inbox', cookie=_signed_session())
    search = _run(
        runtime, '/api/updates/store_search?q=local&source=steam',
        cookie=_signed_session(),
    )

    assert inbox.status_code == search.status_code == 200
    assert runtime._fake_update_reads.calls == [
        ('inbox', 7, 50, None), ('search', 7, 'local', 'steam', 8),
    ]


def test_native_store_search_keeps_provider_calls_behind_adapter(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    response = _run(
        runtime,
        '/api/updates/store_search?q=First&q=Second&source=steam&source=gog&limit=3&limit=9',
        cookie=_signed_session(),
    )

    assert response.status_code == 200
    assert response.json()['q'] == 'First'
    assert response.json()['source'] == 'steam'
    assert runtime._fake_update_reads.calls == [('search', 7, 'First', 'steam', 3)]


def test_native_store_search_validates_before_provider_adapter(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    response = _run(runtime, '/api/updates/store_search?source=vendor', cookie=_signed_session())

    assert response.status_code == 400
    assert response.json()['error'] == 'q required'
    assert runtime._fake_update_reads.calls == []


def test_native_update_scan_keeps_batch_bounds_and_session_csrf(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('native freshness scan pushed a Flask app context')
    )
    cookie, csrf = _signed_session_with_csrf()

    async def scan():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.post(
                '/api/updates/scan',
                json={'limit': 5000, 'library_uuid': 'library-a', 'only_stale': False},
                headers={'X-CSRFToken': csrf},
            )

    response = asyncio.run(scan())
    assert response.status_code == 200
    assert response.json()['ok'] is True
    assert response.json()['behind_count'] == 1
    assert runtime._fake_update_scan.calls == [(7, 50, 'library-a', False)]
    assert response.headers['x-content-type-options'] == 'nosniff'


@pytest.mark.parametrize(
    ('scopes', 'expected_status'),
    [(['read:library'], 403), (['read:library', 'write:library'], 200)],
)
def test_native_update_scan_enforces_bearer_write_scope(monkeypatch, scopes, expected_status):
    runtime, authorization = _bearer_runtime(monkeypatch, scopes)
    response = _run(
        runtime, '/api/updates/scan', method='POST', json_body={'limit': 5},
        headers={'Authorization': authorization},
    )

    assert response.status_code == expected_status
    if expected_status == 403:
        assert response.json()['error'] == 'Bearer token requires write:library scope'
        assert runtime._fake_update_scan.calls == []
    else:
        assert response.json()['ok'] is True
        assert runtime._fake_update_scan.calls == [(7, 5, None, True)]


@pytest.mark.parametrize(
    ('method', 'path', 'body', 'expected_status', 'expected_key'),
    [
        ('POST', '/api/requests', {'title': 'New request', 'notes': 'Please add it'}, 201, 'title'),
        ('DELETE', '/api/requests/23', None, 200, 'ok'),
        ('PATCH', '/api/requests/23', {'status': 'fulfilled'}, 200, 'status'),
    ],
)
def test_lazy_asgi_dispatches_wishlist_mutations_with_csrf(
    monkeypatch, method, path, body, expected_status, expected_key,
):
    flask_app, runtime = _runtime(monkeypatch, admin=method == 'PATCH')
    asyncio.run(runtime._ensure_flask())
    monkeypatch.setattr(
        flask_app, 'app_context',
        lambda: (_ for _ in ()).throw(AssertionError('Flask app context used')),
    )
    cookie, csrf = _signed_session_with_csrf()

    async def perform():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.request(method, path, json=body, headers={'X-CSRFToken': csrf})

    response = asyncio.run(perform())
    assert response.status_code == expected_status
    assert expected_key in response.json()
    assert response.headers['x-content-type-options'] == 'nosniff'


@pytest.mark.parametrize(
    ('method', 'path', 'body', 'expected_status', 'expected_field'),
    [
        ('POST', '/api/collections', {'name': 'Shelf', 'description': 'About'}, 201, 'uuid'),
        ('PATCH', '/api/collections/collection-1', {'name': 'Renamed'}, 200, 'name'),
        ('DELETE', '/api/collections/collection-1', None, 200, 'ok'),
        ('POST', '/api/collections/collection-1/items', {'game_uuid': 'game-1'}, 201, 'game_uuid'),
        ('DELETE', '/api/collections/collection-1/items/game-1', None, 200, 'ok'),
        ('PUT', '/api/collections/collection-1/items/order', {'game_uuids': ['game-1']}, 200, 'uuid'),
    ],
)
def test_lazy_asgi_dispatches_collection_mutations_with_csrf(
    monkeypatch, method, path, body, expected_status, expected_field,
):
    flask_app, runtime = _runtime(monkeypatch)
    asyncio.run(runtime._ensure_flask())
    monkeypatch.setattr(
        flask_app, 'app_context',
        lambda: (_ for _ in ()).throw(AssertionError('Flask app context used')),
    )
    cookie, csrf = _signed_session_with_csrf()

    async def perform():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver'
        ) as client:
            client.cookies.set('session', cookie)
            return await client.request(
                method, path, json=body,
                headers={'X-CSRFToken': csrf},
            )

    response = asyncio.run(perform())
    assert response.status_code == expected_status
    assert response.headers['x-content-type-options'] == 'nosniff'
    if expected_field == 'ok':
        assert response.json()['ok'] is True
    else:
        assert expected_field in response.json()


def test_lazy_asgi_dispatches_member_remote_play_status_without_flask_request(monkeypatch):
    flask_app, runtime = _runtime(monkeypatch)
    monkeypatch.setattr(
        flask_app,
        'app_context',
        lambda: (_ for _ in ()).throw(AssertionError('Flask app context used')),
    )
    response = _run(runtime, '/api/remote-play/status', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json() == {'enabled': False, 'configured': False}
    assert response.headers['x-content-type-options'] == 'nosniff'


def test_lazy_asgi_dispatches_ownership_sync_all_to_native_adapter(monkeypatch):
    calls = []
    data = SimpleNamespace(
        enabled=lambda: True,
        sync_all=lambda user_id: calls.append(('sync_all', user_id)) or [
            {'store': 'steam', 'status': 'skipped', 'reason': 'not_connected'},
        ],
        summary=lambda user_id: {'stores': []},
    )
    monkeypatch.setattr(ownership_actions, 'OwnershipActionsData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch)
    cookie, csrf = _signed_session_with_csrf()

    async def perform():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver',
        ) as client:
            client.cookies.set('session', cookie)
            return await client.post('/api/ownership/sync-all', json={},
                                     headers={'X-CSRFToken': csrf})

    response = asyncio.run(perform())

    assert response.status_code == 200
    assert response.json()['results'][0]['reason'] == 'not_connected'
    assert calls == [('sync_all', 7)]


def test_lazy_asgi_dispatches_game_server_acl_and_reads_natively(monkeypatch):
    calls = []
    row = SimpleNamespace(
        uuid='server-1', display_name='Fixture server', connect_string='host:1',
        game_uuid=None, health_url='http://unused.invalid', compose_project=None,
        container_id=None, invite_note='join',
        to_dict=lambda *, admin=False: {
            'uuid': 'server-1', 'display_name': 'Fixture server',
            **({'health_url': 'http://unused.invalid'} if admin else {}),
        },
    )
    data = SimpleNamespace(
        list_servers=lambda: calls.append(('list',)) or [row],
        get_server=lambda server_uuid: calls.append(('get', server_uuid) and row),
        game_exists=lambda _game_uuid: False,
        probe=lambda *_args: (_ for _ in ()).throw(AssertionError('probe should not run')),
        rollback=lambda: None,
    )
    monkeypatch.setattr(game_server_routes, 'GameServersData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch)
    cookie = _signed_session()

    acl = _run(runtime, '/api/game-servers/acl-check', cookie=cookie)
    listing = _run(runtime, '/api/game-servers', cookie=cookie)

    assert acl.status_code == 200
    assert acl.json()['can_read'] is True
    assert listing.status_code == 200
    assert listing.json()['servers'][0]['display_name'] == 'Fixture server'
    assert 'health_url' not in listing.json()['servers'][0]
    assert calls == [('list',)]


def test_lazy_asgi_dispatches_emulator_saves_reads_natively(monkeypatch):
    calls = []
    data = SimpleNamespace(
        game=lambda game_uuid: SimpleNamespace(uuid=game_uuid),
        can_access=lambda _user, _game: True,
        list_saves=lambda user_id, game_uuid: calls.append(('list_saves', user_id, game_uuid)) or [],
        save_sync_enabled=lambda: True,
        is_state_slot=lambda _row: False,
    )
    monkeypatch.setattr(emulator_mutation_routes, 'EmulatorMutationData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch)

    response = _run(runtime, '/api/games/game-1/saves', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json()['game_uuid'] == 'game-1'
    assert response.json()['saves'] == []
    assert calls == [('list_saves', 7, 'game-1')]


def test_lazy_asgi_dispatches_game_mods_reads_natively(monkeypatch):
    calls = []
    game = SimpleNamespace(uuid='game-1', name='Fixture game')
    data = SimpleNamespace(
        enabled=lambda _app: True,
        game=lambda _app, game_uuid: calls.append(('game', game_uuid)) or game,
        can_access_game=lambda _app, user, row: user.id == 7 and row is game,
        load_mods=lambda _app, game_uuid: calls.append(('mods', game_uuid)) or {
            'mods': [], 'default_loader': 'native',
        },
        loader_conflicts=lambda _app, pack: [],
    )
    monkeypatch.setattr(game_mod_routes, 'GameModsData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch)

    response = _run(runtime, '/api/games/game-1/mods', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json() == {
        'enabled': True, 'mods': [], 'default_loader': 'native', 'loader_conflicts': [],
    }
    assert calls == [('game', 'game-1'), ('mods', 'game-1')]


def test_lazy_asgi_dispatches_unmatched_folder_reads_natively(monkeypatch):
    calls = []
    data = SimpleNamespace(
        query_unmatched=lambda filters, *, paginate=None: calls.append(('query', filters, paginate)) or [],
        list_payloads=lambda _app, _rows, include: calls.append(('project', include)) or [],
        count_unmatched=lambda _filters: 0,
    )
    monkeypatch.setattr(unmatched_reads, 'ScanUnmatchedReadsData', lambda: data)
    flask_app, runtime = _runtime(monkeypatch, admin=True)
    asyncio.run(runtime._ensure_flask())
    monkeypatch.setattr(
        flask_app, 'app_context',
        lambda: (_ for _ in ()).throw(AssertionError('Flask app context used')),
    )

    response = _run(
        runtime, '/api/unmatched_folders?status=Unmatched&paginate=true',
        cookie=_signed_session(),
    )

    assert response.status_code == 200
    assert response.json() == {'items': [], 'total': 0, 'limit': 150, 'offset': 0, 'count': 0}
    assert calls[0][0] == 'query' and calls[0][1]['status'] == 'Unmatched'
    assert calls[1] == ('project', True)


def test_lazy_asgi_dispatches_unmatched_folder_batch_mutation_natively(monkeypatch):
    calls = []
    data = SimpleNamespace(
        clear_one=lambda folder_id: calls.append(('clear', folder_id)) or {
            'id': folder_id, 'ok': True, 'result': 'cleared',
        },
    )
    monkeypatch.setattr(unmatched_mutations, 'ScanUnmatchedMutationData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()

    response = _run(
        runtime, '/api/unmatched_folders/batch/clear', cookie=cookie, method='POST',
        json_body={'ids': ['folder-1']}, headers={'X-CSRFToken': csrf},
    )

    assert response.status_code == 200
    assert response.json()['cleared'] == 1
    assert response.json()['disk_io'] is False
    assert calls == [('clear', 'folder-1')]


def test_lazy_asgi_dispatches_unmatched_feedback_reads_and_writes_natively(monkeypatch):
    calls = []
    row = SimpleNamespace(
        folder_path='/library/Fixture', bad_match_reason=None, bad_match_note=None,
        bad_match_at=None, bad_match_by_user_id=None,
    )
    data = SimpleNamespace(
        reclassify_duplicates=lambda: {'changed_count': 2, 'kept_count': 1},
        backfill_suggested_kind=lambda **kwargs: {'ok': True, 'dry_run': kwargs['dry_run']},
        unmatched_folder=lambda folder_id: row if folder_id == 'folder-1' else None,
        commit=lambda: calls.append(('commit',)),
        log_bad_match=lambda path, reason, actor: calls.append(('log', path, reason, actor)),
        rollback=lambda: calls.append(('rollback',)),
    )
    monkeypatch.setattr(unmatched_feedback, 'ScanUnmatchedFeedbackData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()

    reclassify = _run(
        runtime, '/api/unmatched_folders/reclassify_duplicates',
        cookie=cookie, method='POST', headers={'X-CSRFToken': csrf}, json_body={},
    )
    reasons = _run(runtime, '/api/unmatched/bad_match_reasons', cookie=_signed_session())
    reasons_head = _run(runtime, '/api/unmatched/bad_match_reasons', cookie=_signed_session(), method='HEAD')
    feedback = _run(
        runtime, '/api/unmatched/folder-1/bad_match', cookie=cookie, method='POST',
        headers={'X-CSRFToken': csrf}, json_body={'reason': 'wrong_game', 'note': 'wrong title'},
    )

    assert reclassify.status_code == 200
    assert reclassify.json() == {'changed_count': 2, 'kept_count': 1}
    assert reasons.status_code == 200 and reasons.json()['reasons'][0]['id'] == 'wrong_game'
    assert reasons_head.status_code == 200 and reasons_head.content == b''
    assert feedback.status_code == 200
    assert feedback.json()['reason'] == 'wrong_game'
    assert row.bad_match_note == 'wrong title'
    assert calls == [('commit',), ('log', '/library/Fixture', 'wrong_game', 7)]


def test_lazy_asgi_dispatches_library_tool_preview_natively(monkeypatch):
    calls = []
    data = SimpleNamespace(
        safe_path=lambda _app, path: (calls.append(('safe', path)) or True, None),
        readable_directory=lambda path: calls.append(('directory', path)) or True,
        propose_leaf_libraries=lambda root: calls.append(('propose', root)) or [{'path': root}],
    )
    monkeypatch.setattr(native_library_tools, 'LibraryToolsData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch, admin=True)

    response = _run(
        runtime, '/api/library_tools/propose_leaf_libraries?root=%2Flibrary%2Froot',
        cookie=_signed_session(),
    )

    assert response.status_code == 200
    assert response.json()['count'] == 1
    assert calls == [
        ('safe', '/library/root'), ('directory', '/library/root'),
        ('propose', '/library/root'),
    ]


def test_lazy_asgi_dispatches_library_tool_rename_preview_natively(monkeypatch):
    calls = []
    game = SimpleNamespace(uuid='game-1', name='Fixture', full_disk_path='/library/Fixture')
    data = SimpleNamespace(
        game=lambda _app, game_uuid: calls.append(('game', game_uuid)) or game,
        safe_path=lambda _app, path: calls.append(('safe', path)) or (True, None),
        build_rename_preview=lambda root, **kwargs: calls.append(('preview', root, kwargs)) or [],
    )
    monkeypatch.setattr(native_library_tools_mutations, 'LibraryToolsMutationData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()

    response = _run(
        runtime, '/api/library_tools/rename/preview', cookie=cookie, method='POST',
        headers={'X-CSRFToken': csrf}, json_body={'game_uuid': 'game-1'},
    )

    assert response.status_code == 200
    assert response.json()['plan'] == []
    assert calls[0:2] == [('game', 'game-1'), ('safe', '/library/Fixture')]


def test_lazy_asgi_dispatches_library_tool_freshness_natively(monkeypatch):
    calls = []
    data = SimpleNamespace(
        library=lambda _app, library_uuid: SimpleNamespace(uuid=library_uuid),
        check_freshness=lambda _app, library_uuid, *, limit, only_missing: (
            calls.append((library_uuid, limit, only_missing)) or {'checked': 3}
        ),
    )
    monkeypatch.setattr(native_library_tools_mutations, 'LibraryToolsMutationData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()

    response = _run(
        runtime, '/api/library_tools/check_freshness', cookie=cookie, method='POST',
        headers={'X-CSRFToken': csrf},
        json_body={'library_uuid': 'library-1', 'limit': 3, 'only_missing': True},
    )

    assert response.status_code == 200
    assert response.json()['checked'] == 3
    assert calls == [('library-1', 3, True)]


def test_lazy_asgi_dispatches_library_admin_delete_natively(monkeypatch):
    calls = []
    library = SimpleNamespace(uuid='lib-1', name='Fixture library')
    data = SimpleNamespace(
        library=lambda uuid: library if uuid == 'lib-1' else None,
        start_delete=lambda row, app, **kwargs: calls.append(('delete', row.uuid, callable(kwargs.get('database_scope')))) or 'delete-job',
        log_event=lambda message, *, level, user: calls.append(('event', level, user.id)),
    )
    monkeypatch.setattr(native_library_admin_mutations, 'LibraryAdminMutationData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()

    response = _run(
        runtime, '/api/admin/libraries/batch/delete', cookie=cookie, method='POST',
        headers={'X-CSRFToken': csrf},
        json_body={'uuids': ['lib-1'], 'confirm_name': 'Fixture library'},
    )

    assert response.status_code == 200
    assert response.json()['results'][0]['job_id'] == 'delete-job'
    assert calls == [('delete', 'lib-1', True), ('event', 'information', 7)]


def test_lazy_asgi_dispatches_single_library_delete_form_natively(monkeypatch):
    calls = []
    library = SimpleNamespace(uuid='lib-1', name='Fixture library')
    data = SimpleNamespace(
        library=lambda uuid: library if uuid == 'lib-1' else None,
        start_delete=lambda row, app, **kwargs: calls.append((row.uuid, callable(kwargs.get('database_scope')))) or 'delete-job',
    )
    monkeypatch.setattr(native_library_admin_mutations, 'LibraryAdminMutationData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()

    response = _run(
        runtime, '/delete_full_library/lib-1', cookie=cookie, method='POST',
        headers={'X-CSRFToken': csrf}, form_body={'confirm_name': 'Fixture library'},
    )

    assert response.status_code == 200
    assert response.json()['job_id'] == 'delete-job'
    assert calls == [('lib-1', True)]


def test_lazy_asgi_dispatches_game_library_removal_natively(monkeypatch):
    calls = []

    class FakeGameDeleteData:
        def scan_running(self):
            return False

        def delete_game(self, game_uuid, *, config):
            calls.append((game_uuid, config is not None))

    monkeypatch.setattr(
        native_game_delete_mutations, 'GameDeleteMutationData', FakeGameDeleteData,
    )
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()
    response = _run(
        runtime, '/delete_game/game-1', cookie=cookie, method='POST',
        headers={'X-CSRFToken': csrf}, json_body={},
    )

    assert response.status_code == 200
    assert response.json()['message'] == 'Game removed from library successfully.'
    assert calls == [('game-1', True)]


def test_lazy_asgi_dispatches_unmatched_folder_delete_natively(monkeypatch):
    calls = []

    class FakeFolderDeleteData:
        exists = True

        def scan_running(self):
            return False

        def allowed_bases(self, _app):
            return ['/safe']

        def safe_path(self, path, bases):
            calls.append(('safe', path, bases))
            return True, None

        def folder_entry(self, path):
            return SimpleNamespace(folder_path=path)

        def remove_folder_entry(self, entry):
            calls.append(('entry', entry.folder_path))

        def path_exists(self, _path):
            return self.exists

        def remove_path(self, path):
            calls.append(('remove', path))
            self.exists = False

    monkeypatch.setattr(
        native_game_delete_mutations, 'GameDeleteMutationData', FakeFolderDeleteData,
    )
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()
    response = _run(
        runtime, '/delete_folder', cookie=cookie, method='POST',
        headers={'X-CSRFToken': csrf}, json_body={'folder_path': '/safe/library/item'},
    )

    assert response.status_code == 200
    assert response.json()['status'] == 'success'
    assert [call[0] for call in calls] == ['safe', 'remove', 'entry']


def test_lazy_asgi_dispatches_full_game_disk_delete_natively(monkeypatch):
    calls = []

    class FakeFullGameDeleteData:
        exists = True

        def scan_running(self):
            return False

        def game(self, game_uuid):
            calls.append(('game', game_uuid))
            return SimpleNamespace(full_disk_path='/safe/game')

        def path_exists(self, _path):
            return self.exists

        def path_is_directory(self, _path):
            return True

        def allowed_bases(self, _app):
            return ['/safe']

        def safe_path(self, path, bases):
            calls.append(('safe', path, bases))
            return True, None

        def remove_path(self, path):
            calls.append(('remove', path))
            self.exists = False

        def delete_game(self, game_uuid, *, config):
            calls.append(('db', game_uuid, config is not None))

    monkeypatch.setattr(
        native_game_delete_mutations, 'GameDeleteMutationData', FakeFullGameDeleteData,
    )
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()
    response = _run(
        runtime, '/delete_full_game', cookie=cookie, method='POST',
        headers={'X-CSRFToken': csrf}, json_body={'game_uuid': 'game-1'},
    )

    assert response.status_code == 200
    assert response.json()['message'] == 'Game and its folder have been deleted successfully.'
    assert [call[0] for call in calls] == ['game', 'safe', 'remove', 'db']


def test_lazy_asgi_dispatches_legacy_unmatched_status_form_natively(monkeypatch):
    calls = []

    class FakeUnmatchedMutationData:
        def toggle_status_compat(self, folder_id):
            calls.append(folder_id)
            return 'Ignore'

    monkeypatch.setattr(
        unmatched_mutations, 'ScanUnmatchedMutationData', FakeUnmatchedMutationData,
    )
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()
    response = _run(
        runtime, '/toggle_ignore_status/folder-9', cookie=cookie, method='POST',
        form_body={'csrf_token': csrf},
    )

    assert response.status_code == 303
    assert response.headers['location'] == '/scan_management'
    assert calls == ['folder-9']


def test_lazy_asgi_dispatches_game_image_delete_natively(monkeypatch):
    calls = []

    class FakeGameImageDeleteData:
        def scan_running(self):
            return False

        def delete_image_record_and_file(self, image_id, *, config):
            calls.append((image_id, config is not None))
            return SimpleNamespace(id=image_id)

    monkeypatch.setattr(
        native_game_delete_mutations, 'GameDeleteMutationData', FakeGameImageDeleteData,
    )
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()
    response = _run(
        runtime, '/delete_image', cookie=cookie, method='POST',
        headers={'X-CSRFToken': csrf}, json_body={'image_id': 5},
    )

    assert response.status_code == 200
    assert response.json()['message'] == 'Image deleted successfully'
    assert calls == [(5, True)]


def test_lazy_asgi_dispatches_single_library_update_natively(monkeypatch):
    calls = []
    library = SimpleNamespace(uuid='lib-1', name='Original')
    data = SimpleNamespace(
        library=lambda uuid: library if uuid == 'lib-1' else None,
        update=lambda row, **values: calls.append((row.uuid, values)) or {
            'uuid': row.uuid, 'name': values['name'], 'platform': values['platform'].name,
            'scan_depth': values['scan_depth'],
        },
    )
    monkeypatch.setattr(native_library_admin_mutations, 'LibraryAdminMutationData', lambda: data)
    cookie, csrf = _signed_session_with_csrf()
    _flask_app, runtime = _runtime(monkeypatch, admin=True)

    response = _run(
        runtime, '/api/admin/libraries/lib-1', cookie=cookie, method='PUT',
        headers={'X-CSRFToken': csrf}, json_body={
            'name': 'Renamed', 'platform': 'PCWIN', 'scan_depth': 2,
            'watch_enabled': 'off',
        },
    )

    assert response.status_code == 200
    assert response.json()['name'] == 'Renamed'
    assert calls[0][0] == 'lib-1'
    assert calls[0][1]['watch_enabled'] is False


def test_lazy_asgi_dispatches_single_library_scan_natively(monkeypatch):
    calls = []
    library = SimpleNamespace(uuid='lib-1', name='Fixture library', last_scan_folder='/safe/root/one')
    data = SimpleNamespace(
        library=lambda uuid: library if uuid == 'lib-1' else None,
        resolve_scan_path=lambda _app, folder, _root: (folder, None),
        allowed_bases=lambda _app: ['/safe/root'],
        safe_path=lambda path, _bases: (path == '/safe/root/one', None),
        scan_mode_for_path=lambda _path, _mode: 'folders',
        start_scan=lambda *, library, folder, options, app, database_scope=None: calls.append((library.uuid, folder, options, database_scope)) or {
            'status': 'queued', 'job_id': 'scan-17', 'position': 1, 'message': 'queued',
        },
    )
    monkeypatch.setattr(native_library_admin_mutations, 'LibraryAdminMutationData', lambda: data)
    cookie, csrf = _signed_session_with_csrf()
    _flask_app, runtime = _runtime(monkeypatch, admin=True)

    response = _run(
        runtime, '/api/admin/libraries/scan', cookie=cookie, method='POST',
        headers={'X-CSRFToken': csrf}, json_body={
            'library_uuid': 'lib-1', 'folder': '/safe/root/one',
            'scan_mode': 'folders', 'remove_missing': True,
        },
    )

    assert response.status_code == 200
    assert response.json()['job_id'] == 'scan-17'
    assert calls[0][0:2] == ('lib-1', '/safe/root/one')
    assert calls[0][2]['scan_mode'] == 'folders'
    assert calls[0][2]['remove_missing'] is True
    assert calls[0][2]['queue_policy'] == 'queue'
    assert calls[0][2]['schedule_fields']['schedule_kind'] == 'once'


def test_lazy_asgi_dispatches_library_refresh_all_natively(monkeypatch):
    calls = []
    data = SimpleNamespace(
        refresh_queue=lambda: [{'uuid': 'lib-1', 'name': 'Fixture', 'folder': '/safe/root/one'}],
        refresh_busy=lambda: False,
        enqueue_refresh=lambda queue: calls.append(('enqueue', queue)) or {
            'status': 'queued', 'jobs': [{'job_id': 'refresh-job', 'position': 1}],
        },
        promote_refresh=lambda _app: SimpleNamespace(id='refresh-job'),
    )
    monkeypatch.setattr(native_library_admin_mutations, 'LibraryAdminMutationData', lambda: data)
    cookie, csrf = _signed_session_with_csrf()
    _flask_app, runtime = _runtime(monkeypatch, admin=True)

    response = _run(
        runtime, '/api/admin/libraries/refresh_all', cookie=cookie, method='POST',
        headers={'X-CSRFToken': csrf}, json_body={},
    )

    assert response.status_code == 200
    assert response.json()['job_id'] == 'refresh-job'
    assert response.json()['jobs'][0]['status'] == 'started'
    assert calls[0][0] == 'enqueue'


def test_lazy_asgi_dispatches_scan_job_status_with_filters_and_timing(monkeypatch):
    from datetime import datetime, timezone

    calls = []
    job = SimpleNamespace(
        id='scan-1', library=SimpleNamespace(name='Shelf A'), library_uuid='lib-1',
        folders=['A', 'B'], status='Queued', total_folders=2, folders_success=1,
        folders_failed=0, removed_count=0, scan_folder='/safe/root',
        setting_remove=False, setting_filefolder=True,
        setting_download_missing_images=True, current_processing=None,
        error_message=None, last_run=datetime(2026, 10, 14, tzinfo=timezone.utc),
        last_progress_update=None, next_run=None,
    )
    data = SimpleNamespace(
        drain_if_idle=lambda _app, *, database_scope=None: calls.append(
            ('drain', database_scope is not None),
        ),
        list_jobs=lambda filters: calls.append(('list', filters)) or [job],
        queue_position=lambda job_id: calls.append(('position', job_id)) or 3,
    )
    monkeypatch.setattr(native_scan_job_reads, 'ScanJobReadData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch, admin=True)

    response = _run(
        runtime, '/api/scan_jobs_status?status=queued&library_uuid=lib-1&name=Shelf',
        cookie=_signed_session(),
    )
    head = _run(
        runtime, '/api/scan_jobs_status?status=queued&library_uuid=lib-1&name=Shelf',
        cookie=_signed_session(), method='HEAD',
    )

    assert response.status_code == 200
    row = response.json()[0]
    assert row['id'] == 'scan-1'
    assert row['queue_position'] == 3
    assert row['folders_processed'] == 1
    assert row['progress_percentage'] == 50.0
    assert row['created_at'] is None
    assert head.status_code == 200 and head.content == b''
    assert calls == [
        ('drain', True),
        ('list', {'statuses': ['Queued'], 'library_uuid': 'lib-1', 'q': 'Shelf'}),
        ('position', 'scan-1'),
    ] * 2


def test_lazy_asgi_dispatches_admin_path_info_without_opening_path(monkeypatch):
    calls = []
    data = SimpleNamespace(path_info=lambda value: calls.append(value) or {
        'path': value, 'exists': True, 'is_dir': True, 'basename': 'library',
        'open_via': 'desktop',
        'note': 'Server returns path string only; Desktop companion opens host explorer.',
    })
    monkeypatch.setattr(native_scan_job_reads, 'ScanJobReadData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch, admin=True)

    response = _run(runtime, '/api/path/open?full_disk_path=%2Fstorage%2Flibrary',
                    cookie=_signed_session())
    head = _run(runtime, '/api/path/open?full_disk_path=%2Fstorage%2Flibrary',
                cookie=_signed_session(), method='HEAD')

    assert response.status_code == 200
    assert response.json()['open_via'] == 'desktop'
    assert response.json()['path'] == '/storage/library'
    assert head.status_code == 200 and head.content == b''
    assert calls == ['/storage/library', '/storage/library']


def test_lazy_asgi_dispatches_newsletter_reads_and_fake_send(monkeypatch):
    calls = []
    data = SimpleNamespace(
        list_state=lambda: {'can_send': True, 'recipients': [{'id': 1, 'email': 'a@example.test'}],
                            'newsletters': [{'id': 7, 'subject': 'Update'}]},
        detail=lambda newsletter_id: {'id': newsletter_id, 'subject': 'Update', 'content': 'Body'},
        send=lambda subject, content, recipients, user: calls.append(
            (subject, content, recipients, user.id)
        ) or ({'newsletter': {'id': 8, 'subject': subject}, 'failed_count': 0}, None, None),
        rollback=lambda: calls.append(('rollback',)),
    )
    monkeypatch.setattr(native_admin_newsletters, 'AdminNewsletterData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()

    listing = _run(runtime, '/api/admin/newsletters', cookie=_signed_session())
    detail = _run(runtime, '/api/admin/newsletters/7', cookie=_signed_session())
    head = _run(runtime, '/api/admin/newsletters', cookie=_signed_session(), method='HEAD')
    no_csrf = _run(
        runtime, '/api/admin/newsletters', cookie=_signed_session(), method='POST',
        json_body={
            'subject': 'Launch update', 'content': 'Hello members',
            'recipients': ['a@example.test'],
        },
    )
    sent = _run(
        runtime, '/api/admin/newsletters', cookie=cookie, method='POST',
        headers={'X-CSRFToken': csrf}, json_body={
            'subject': 'Launch update', 'content': 'Hello members',
            'recipients': ['a@example.test'],
        },
    )

    assert listing.status_code == detail.status_code == 200
    assert listing.json()['newsletters'][0]['id'] == 7
    assert detail.json()['newsletter']['content'] == 'Body'
    assert head.status_code == 200 and head.content == b''
    assert no_csrf.status_code == 400
    assert sent.status_code == 200 and sent.json()['failed_count'] == 0
    assert calls == [('Launch update', 'Hello members', ['a@example.test'], 7)]


def test_lazy_asgi_dispatches_igdb_availability_check_natively(monkeypatch):
    calls = []
    data = SimpleNamespace(
        exists=lambda value: calls.append(('exists', value)) or value == 42,
        cover_url=lambda value: calls.append(('cover', value)) or 'https://covers.test/42.jpg',
    )
    monkeypatch.setattr(native_igdb_availability, 'IgdbAvailabilityData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch)

    response = _run(runtime, '/api/check_igdb_id?igdb_id=42', cookie=_signed_session())
    invalid = _run(runtime, '/api/check_igdb_id?igdb_id=invalid', cookie=_signed_session())
    head = _run(runtime, '/api/check_igdb_id?igdb_id=42', cookie=_signed_session(), method='HEAD')
    cover = _run(runtime, '/api/get_cover_thumbnail?igdb_id=42', cookie=_signed_session())

    assert response.status_code == 200 and response.json() == {'available': False}
    assert invalid.status_code == 400 and invalid.json()['available'] is False
    assert head.status_code == 200 and head.content == b''
    assert cover.status_code == 200 and cover.json()['cover_url'] == 'https://covers.test/42.jpg'
    assert calls == [('exists', 42), ('exists', 42), ('cover', 42)]


def test_lazy_asgi_dispatches_igdb_name_search_with_legacy_contract(monkeypatch):
    calls = []

    class FakeIGDBData:
        def search_games_by_name(self, name, platform_id):
            calls.append((name, platform_id))
            if name == 'provider-error':
                return {'error': 'Search failed'}
            return [{'id': 42, 'name': name}]

    monkeypatch.setattr(
        native_igdb_company_role, 'IGDBCompanyRoleData', FakeIGDBData,
    )
    _flask_app, runtime = _runtime(monkeypatch)

    success = _run(
        runtime,
        '/api/search_igdb_by_name?name=First&name=Second&platform_id=invalid&platform_id=6',
        cookie=_signed_session(),
    )
    missing = _run(runtime, '/api/search_igdb_by_name', cookie=_signed_session())
    provider_error = _run(
        runtime, '/api/search_igdb_by_name?name=provider-error',
        cookie=_signed_session(),
    )
    head = _run(
        runtime, '/api/search_igdb_by_name?name=Head',
        cookie=_signed_session(), method='HEAD',
    )

    assert success.status_code == 200
    assert success.json() == {'results': [{'id': 42, 'name': 'First'}]}
    assert missing.status_code == 400 and missing.json()['error_code'] == 'bad_request'
    assert provider_error.status_code == 502
    assert provider_error.json()['error_code'] == 'bad_gateway'
    assert head.status_code == 200 and head.content == b''
    assert calls == [
        ('First', 'invalid'), ('provider-error', None), ('Head', None),
    ]


def test_lazy_asgi_dispatches_storage_hardlinks_with_admin_csrf_and_safe_adapter(monkeypatch):
    class FakeHardlinksData:
        def __init__(self):
            self.calls = []

        def paths_allowed(self, source, dest, *, app):
            self.calls.append(('paths', source, dest))
            return (source != 'outside', 'Access denied - path outside allowed directories')

        def preview(self, source, dest):
            self.calls.append(('preview', source, dest))
            return {'ok': False, 'would_succeed': False, 'reasons': ['destination exists']}

        def apply(self, source, dest):
            self.calls.append(('apply', source, dest))
            return {'ok': True, 'applied': True, 'source': source, 'dest': dest}

        def audit(self, source, dest, *, audit_user=None):
            self.calls.append(('audit', source, dest, audit_user))

    fake = FakeHardlinksData()
    monkeypatch.setattr(native_storage_hardlinks, 'StorageHardlinksData', lambda: fake)
    flask_app, runtime = _runtime(monkeypatch, admin=True)
    flask_app.config.update(ENABLE_HARDLINK_HELPERS=True, ALLOW_HARDLINK_APPLY=True)
    cookie, csrf = _signed_session_with_csrf()
    headers = {'X-CSRFToken': csrf}

    preview = _run(
        runtime, '/api/storage/hardlink/preview', cookie=cookie,
        method='POST', headers=headers,
        json_body={'source': '/games/source.rom', 'dest': '/games/dest.rom'},
    )
    unsafe = _run(
        runtime, '/api/storage/hardlink/preview', cookie=cookie,
        method='POST', headers=headers,
        json_body={'source': 'outside', 'dest': '/games/dest.rom'},
    )
    no_csrf = _run(
        runtime, '/api/storage/hardlink/apply', cookie=cookie,
        method='POST', json_body={'source': '/games/a', 'dest': '/games/b'},
    )
    applied = _run(
        runtime, '/api/storage/hardlink/apply', cookie=cookie,
        method='POST', headers=headers,
        json_body={'source': '/games/source.rom', 'dest': '/games/dest.rom'},
    )

    assert preview.status_code == 200
    assert preview.json() == {
        'ok': False, 'would_succeed': False, 'reasons': ['destination exists'],
    }
    assert unsafe.status_code == 403 and unsafe.json()['error_code'] == 'forbidden'
    assert no_csrf.status_code == 400 and no_csrf.json()['error_code'] == 'bad_request'
    assert applied.status_code == 201 and applied.json()['applied'] is True
    assert ('apply', '/games/source.rom', '/games/dest.rom') in fake.calls
    assert ('audit', '/games/source.rom', '/games/dest.rom', 7) in fake.calls


def test_lazy_asgi_storage_hardlinks_respect_feature_flags_after_validation(monkeypatch):
    class FakeHardlinksData:
        def paths_allowed(self, *_args, **_kwargs):
            raise AssertionError('path checks should not run while feature disabled')

    monkeypatch.setattr(native_storage_hardlinks, 'StorageHardlinksData', FakeHardlinksData)
    flask_app, runtime = _runtime(monkeypatch, admin=True)
    flask_app.config.update(ENABLE_HARDLINK_HELPERS=False, ALLOW_HARDLINK_APPLY=False)
    cookie, csrf = _signed_session_with_csrf()
    headers = {'X-CSRFToken': csrf}
    invalid = _run(
        runtime, '/api/storage/hardlink/preview', cookie=cookie,
        method='POST', headers=headers, json_body={'source': '', 'dest': ''},
    )
    disabled = _run(
        runtime, '/api/storage/hardlink/preview', cookie=cookie,
        method='POST', headers=headers,
        json_body={'source': '/games/a', 'dest': '/games/b'},
    )
    apply_disabled = _run(
        runtime, '/api/storage/hardlink/apply', cookie=cookie,
        method='POST', headers=headers,
        json_body={'source': '/games/a', 'dest': '/games/b'},
    )

    assert invalid.status_code == 422
    assert disabled.status_code == 403 and disabled.json()['error'] == 'Hardlink helpers are disabled'
    assert apply_disabled.status_code == 403


def test_lazy_asgi_dispatches_malware_scan_with_admin_csrf_and_root_gate(monkeypatch, tmp_path):
    class FakeMalwareScanData:
        def __init__(self):
            self.scanned = []

        def allowed_roots(self, _config):
            return [str(tmp_path)]

        def scan(self, path, *, config):
            self.scanned.append(path)
            assert config['DATA_FOLDER_GAMES'] == str(tmp_path)
            return {'clean': False, 'blocked': True, 'engine': 'fake'}, False

    fake = FakeMalwareScanData()
    monkeypatch.setattr(native_malware_scan_mutation, 'MalwareScanData', lambda: fake)
    flask_app, runtime = _runtime(monkeypatch, admin=True)
    flask_app.config['DATA_FOLDER_GAMES'] = str(tmp_path)
    flask_app._fake_user.name = 'Administrator'
    cookie, csrf = _signed_session_with_csrf()
    headers = {'X-CSRFToken': csrf}
    allowed_path = tmp_path / 'sample.bin'

    scanned = _run(
        runtime, '/api/admin/malware-scan', cookie=cookie,
        method='POST', headers=headers, json_body={'path': str(allowed_path)},
    )
    denied = _run(
        runtime, '/api/admin/malware-scan', cookie=cookie,
        method='POST', headers=headers, json_body={'path': str(tmp_path.parent / 'outside.bin')},
    )
    missing_csrf = _run(
        runtime, '/api/admin/malware-scan', cookie=cookie,
        method='POST', json_body={'path': str(allowed_path)},
    )

    assert scanned.status_code == 409
    assert scanned.json() == {
        'clean': False, 'blocked': True, 'engine': 'fake', 'scanned_by': 'Administrator',
    }
    assert denied.status_code == 403
    assert missing_csrf.status_code == 400
    assert fake.scanned == [str(allowed_path)]


def test_lazy_asgi_dispatches_cropped_library_image_preview_with_admin_csrf(monkeypatch):
    class FakeLibraryImageData:
        def __init__(self):
            self.images = []

        def preview_image(self, image_data):
            self.images.append(image_data)
            return 'data:image/png;base64,processed'

    fake = FakeLibraryImageData()
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    monkeypatch.setattr(
        native_library_admin_mutations, 'LibraryAdminMutationData', lambda: fake,
    )
    cookie, csrf = _signed_session_with_csrf()
    headers = {'X-CSRFToken': csrf}
    preview = _run(
        runtime, '/api/library/preview-cropped-image', cookie=cookie,
        method='POST', headers=headers,
        json_body={'image_data': 'data:image/jpeg;base64,original'},
    )
    invalid = _run(
        runtime, '/api/library/preview-cropped-image', cookie=cookie,
        method='POST', headers=headers, json_body={},
    )
    no_csrf = _run(
        runtime, '/api/library/preview-cropped-image', cookie=cookie,
        method='POST', json_body={'image_data': 'x'},
    )

    assert preview.status_code == 200
    assert preview.json()['preview_url'] == 'data:image/png;base64,processed'
    assert invalid.status_code == 422
    assert no_csrf.status_code == 400
    assert fake.images == ['data:image/jpeg;base64,original']


def test_lazy_asgi_dispatches_rtc_token_with_acl_child_rules_and_csrf(monkeypatch):
    class FakeRtcData:
        def __init__(self):
            self.calls = []

        def token_config(self):
            return {'url': 'wss://rtc.example.test', 'api_key': 'key', 'api_secret': 'secret'}

        def normalize_room(self, room):
            self.calls.append(('normalize', room))
            return room

        def may_join(self, user, room):
            self.calls.append(('authorize', user.id, room))
            return room == 'household:lobby'

        def mint(self, **kwargs):
            self.calls.append(('mint', kwargs))
            return 'fake-token'

    fake = FakeRtcData()
    _flask_app, runtime = _runtime(monkeypatch)
    monkeypatch.setattr(status_reads, 'RtcStatusData', lambda: fake)
    cookie, csrf = _signed_session_with_csrf()
    headers = {'X-CSRFToken': csrf}
    minted = _run(
        runtime, '/api/rtc/token', cookie=cookie, method='POST',
        headers=headers, json_body={'spectator': True},
    )
    denied = _run(
        runtime, '/api/rtc/token', cookie=cookie, method='POST',
        headers=headers, json_body={'room': 'unrecognized-room'},
    )
    no_csrf = _run(
        runtime, '/api/rtc/token', cookie=cookie, method='POST',
        json_body={},
    )

    assert minted.status_code == 200
    assert minted.json() == {
        'token': 'fake-token', 'url': 'wss://rtc.example.test',
        'room': 'household:lobby', 'identity': 'user-7',
        'spectator': True, 'can_publish': False,
    }
    assert denied.status_code == 403
    assert no_csrf.status_code == 400
    assert len([call for call in fake.calls if call[0] == 'mint']) == 1

    _flask_app._fake_user.role = 'child'
    child_denied = _run(
        runtime, '/api/rtc/token', cookie=cookie, method='POST',
        headers=headers, json_body={'video': True},
    )
    assert child_denied.status_code == 403
    assert len([call for call in fake.calls if call[0] == 'mint']) == 1


def test_lazy_asgi_dispatches_email_confirmation_without_flask_api_route(monkeypatch):
    calls = []
    data = SimpleNamespace(confirm=lambda token, secret: calls.append(
        (token, bool(secret))
    ) or 'confirmed')
    monkeypatch.setattr(native_auth_confirmation, 'AuthConfirmationData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch)

    response = _run(runtime, '/api/auth/confirm/signed-token')
    head = _run(runtime, '/api/auth/confirm/signed-token', method='HEAD')

    assert response.status_code == 200
    assert response.json()['confirmed'] is True
    assert response.json()['already_confirmed'] is False
    assert head.status_code == 200 and head.content == b''
    assert calls == [('signed-token', True), ('signed-token', True)]


def test_lazy_asgi_dispatches_login_with_csrf_safe_next_and_remember_compat(monkeypatch):
    calls = []
    user = SimpleNamespace(get_id=lambda: '7:fp')
    def authenticate(username, password, ip):
        calls.append((username, password, ip))
        if username == 'limited':
            return None, ('rate_limited', 'Too many login attempts.')
        if password == 'incorrect':
            return None, ('unauthorized', 'Invalid username or password.')
        return user, None

    data = SimpleNamespace(authenticate=authenticate)
    monkeypatch.setattr(native_auth_login, 'AuthLoginData', lambda: data)
    flask_app, runtime = _runtime(monkeypatch)
    flask_app.config['TRUSTED_PROXIES'] = 1
    flask_app.config['TRUSTED_PROXY_CIDRS'] = '10.20.0.0/24'
    session = {}
    csrf = generate_csrf_token(session, 'native-asgi-browse-secret')
    cookie = dump_session_cookie(session, 'native-asgi-browse-secret')
    headers = {'X-CSRFToken': csrf, 'X-Forwarded-For': '198.51.100.42'}
    body = {'username': 'alice', 'password': 'correct horse battery'}

    missing_csrf = _run(
        runtime, '/api/auth/login', method='POST', cookie=cookie, json_body=body,
    )
    success = _run(
        runtime, '/api/auth/login?next=%2Flibrary%3Fq%3Dzelda', method='POST',
        cookie=cookie, headers=headers, json_body=body,
    )
    unsafe_next = _run(
        runtime, '/api/auth/login?next=https%3A%2F%2Fevil.example', method='POST',
        cookie=cookie, headers=headers, json_body=body,
    )
    bad_password = _run(
        runtime, '/api/auth/login', method='POST', cookie=cookie,
        headers=headers, json_body={'username': 'alice', 'password': 'incorrect'},
    )
    limited = _run(
        runtime, '/api/auth/login', method='POST', cookie=cookie,
        headers=headers, json_body={'username': 'limited', 'password': 'correct horse battery'},
    )

    assert missing_csrf.status_code == 400
    assert success.status_code == 200
    assert success.json()['next_url'] == '/library?q=zelda'
    assert unsafe_next.json()['next_url'] == '/discover'
    assert bad_password.status_code == 401
    assert limited.status_code == 429
    set_cookies = success.headers.get_list('set-cookie')
    assert any(value.startswith('session=') for value in set_cookies)
    assert any(value.startswith('remember_token=') for value in set_cookies)
    assert calls == [
        ('alice', 'correct horse battery', '127.0.0.1'),
        ('alice', 'correct horse battery', '127.0.0.1'),
        ('alice', 'incorrect', '127.0.0.1'),
        ('limited', 'correct horse battery', '127.0.0.1'),
    ]


def test_lazy_asgi_logout_clears_flask_login_and_remember_cookies(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    cookie = dump_session_cookie({
        '_user_id': '7:fp', '_fresh': True, '_id': 'session-id', '_remember_seconds': 3600,
    }, 'native-asgi-browse-secret')

    remember = {'remember_token': 'remember-cookie'}
    response = _run(runtime, '/logout', cookie=cookie, extra_cookies=remember)
    head = _run(runtime, '/logout', cookie=cookie, extra_cookies=remember, method='HEAD')
    guest = _run(runtime, '/logout')

    assert response.status_code == 302 and response.headers['location'] == '/login'
    assert response.headers['content-type'] == 'text/html; charset=utf-8'
    assert response.text == (
        '<!doctype html>\n'
        '<html lang=en>\n'
        '<title>Redirecting...</title>\n'
        '<h1>Redirecting...</h1>\n'
        '<p>You should be redirected automatically to the target URL: '
        '<a href="/login">/login</a>. If not, click the link.\n'
    )
    assert head.status_code == 302 and head.content == b''
    cookies = response.headers.get_list('set-cookie')
    assert any(
        value.startswith('remember_token=') and 'max-age=0' in value.lower()
        for value in cookies
    )
    from http.cookies import SimpleCookie
    jar = SimpleCookie()
    for value in cookies:
        jar.load(value)
    assert jar['session'].value == ''
    assert jar['session']['max-age'] == '0'
    assert guest.status_code == 302 and guest.headers['location'] == '/login'
    assert guest.headers.get_list('set-cookie') == []


@pytest.mark.parametrize('has_remember_cookie', [True, False])
@pytest.mark.parametrize('cookie_overrides', [
    {},
    {
        'SESSION_COOKIE_NAME': 'oneirodex_session',
        'SESSION_COOKIE_PATH': '/',
        'SESSION_COOKIE_DOMAIN': 'example.test',
        'SESSION_COOKIE_SECURE': True,
        'SESSION_COOKIE_HTTPONLY': False,
        'SESSION_COOKIE_SAMESITE': 'Lax',
        'REMEMBER_COOKIE_NAME': 'oneirodex_remember',
        'REMEMBER_COOKIE_PATH': '/admin',
        'REMEMBER_COOKIE_DOMAIN': 'example.test',
        'REMEMBER_COOKIE_SECURE': True,
        'REMEMBER_COOKIE_HTTPONLY': True,
        'REMEMBER_COOKIE_SAMESITE': 'Strict',
    },
    {
        'SESSION_COOKIE_SECURE': True,
        'SESSION_COOKIE_PARTITIONED': True,
    },
])
def test_lazy_asgi_logout_matches_flask_login_remember_session_cleanup(
    monkeypatch, has_remember_cookie, cookie_overrides,
):
    from flask import redirect
    from flask_login import logout_user
    from http.cookies import SimpleCookie
    from oneirodex.runtime_native.session_compat import load_session_cookie

    _flask_app, runtime = _runtime(monkeypatch)
    _flask_app.config.update(cookie_overrides)
    session_cookie_name = _flask_app.config['SESSION_COOKIE_NAME']
    remember_cookie_name = _flask_app.config.get('REMEMBER_COOKIE_NAME', 'remember_token')
    base_url = (
        'https://example.test'
        if _flask_app.config.get('SESSION_COOKIE_DOMAIN') == 'example.test'
        else 'http://localhost'
    )
    legacy_app = Flask(__name__)
    legacy_config = {
        'SECRET_KEY': 'native-asgi-browse-secret',
        'SESSION_COOKIE_NAME': 'session',
        'REMEMBER_COOKIE_NAME': 'remember_token',
        **cookie_overrides,
    }
    legacy_app.config.update(legacy_config)
    manager = LoginManager(legacy_app)
    manager.login_view = 'login'
    manager.user_loader(lambda _user_id: None)
    legacy_app.add_url_rule('/login', endpoint='login', view_func=lambda: 'login')

    @legacy_app.get('/logout')
    def legacy_logout():
        logout_user()
        return redirect('/login')

    with legacy_app.test_client() as client:
        with client.session_transaction() as session:
            session.update({'_user_id': '7:fp', '_fresh': True, '_id': 'session-id'})
            if has_remember_cookie:
                session['_remember_seconds'] = 3600
            else:
                session['_remember'] = 'set'
        if has_remember_cookie:
            client.set_cookie(
                remember_cookie_name, 'remember-cookie',
                domain=legacy_app.config.get('REMEMBER_COOKIE_DOMAIN') or 'localhost',
            )
        incoming_session = client.get_cookie(
            session_cookie_name,
            domain=legacy_app.config.get('SESSION_COOKIE_DOMAIN') or 'localhost',
            path='/',
        ).value
        legacy = client.get('/logout', follow_redirects=False, base_url=base_url)

    current = _run(
        runtime, '/logout', cookie=incoming_session,
        session_cookie_name=session_cookie_name,
        extra_cookies={remember_cookie_name: 'remember-cookie'} if has_remember_cookie else None,
        base_url=base_url,
    )
    assert (current.status_code, current.headers['location'], current.content) == (
        legacy.status_code, legacy.headers['Location'], legacy.get_data(),
    )

    def cookies(response):
        jar = SimpleCookie()
        values = (
            response.headers.get_list('set-cookie')
            if hasattr(response.headers, 'get_list')
            else response.headers.getlist('set-cookie')
        )
        for value in values:
            jar.load(value)
        result = {}
        for name, morsel in jar.items():
            payload = morsel.value
            if name == session_cookie_name:
                payload = load_session_cookie(
                    payload, 'native-asgi-browse-secret', max_age=31_536_000,
                )
            result[name] = (
                payload, morsel['path'], morsel['domain'], morsel['secure'],
                morsel['httponly'], morsel['samesite'], morsel['max-age'],
                morsel['partitioned'],
            )
        return result

    current_cookies = cookies(current)
    legacy_cookies = cookies(legacy)
    assert current_cookies == legacy_cookies, (
        f'current={current_cookies!r} legacy={legacy_cookies!r}'
    )


def test_lazy_asgi_auth_pages_serve_react_shell_and_preserve_flash_and_redirects(monkeypatch, tmp_path):
    calls = []
    data = SimpleNamespace(
        invite_active=lambda token: calls.append(('invite', token)) or False,
        reset_token_active=lambda token: calls.append(('reset', token)) or False,
    )
    monkeypatch.setattr(native_auth_pages, 'AuthPageData', lambda: data)
    flask_app, runtime = _runtime(monkeypatch)
    flask_app.static_folder = str(tmp_path)
    shell_path = tmp_path / 'dist' / 'member-auth' / 'auth.html'
    shell_path.parent.mkdir(parents=True)
    shell_path.write_text('<html><body><div id="member-auth-root"></div></body></html>', encoding='utf-8')
    session = {'_flashes': [['warning', '<script>alert(1)</script>']]}
    cookie = dump_session_cookie(session, 'native-asgi-browse-secret')

    login_page = _run(runtime, '/login', cookie=cookie)
    head = _run(runtime, '/login', cookie=cookie, method='HEAD')
    signed_in = _run(runtime, '/login', cookie=_signed_session())
    bad_invite = _run(runtime, '/register?token=expired', cookie=cookie)
    confirmation = _run(runtime, '/confirm/confirm-token')
    bad_reset = _run(runtime, '/reset_password/expired')

    assert login_page.status_code == 200 and 'id="member-auth-root"' in login_page.text
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in login_page.text
    assert '<script>alert(1)</script>' not in login_page.text
    assert login_page.headers['cache-control'] == 'no-store'
    assert head.status_code == 200 and head.content == b''
    assert signed_in.status_code == 302 and signed_in.headers['location'] == '/discover'
    assert bad_invite.status_code == 302 and bad_invite.headers['location'] == '/register'
    assert confirmation.status_code == 200
    assert bad_reset.status_code == 302 and bad_reset.headers['location'] == '/login'
    assert calls == [('invite', 'expired'), ('reset', 'expired')]


def test_lazy_asgi_setup_pages_keep_step_redirects_and_admin_gate(monkeypatch, tmp_path):
    calls = []
    data = SimpleNamespace(
        step=2,
        required=lambda: True,
        in_progress=lambda: False,
        current_step=lambda: data.step,
        start=lambda: calls.append('start') or setattr(data, 'step', 1),
        redirect_url=lambda: '/setup/smtp',
    )
    monkeypatch.setattr(native_setup_pages, 'SetupPagesData', lambda: data)
    flask_app, runtime = _runtime(monkeypatch)
    flask_app.static_folder = str(tmp_path)
    shell_path = tmp_path / 'dist' / 'member-auth' / 'auth.html'
    shell_path.parent.mkdir(parents=True)
    shell_path.write_text('<html><body><div id="member-auth-root"></div></body></html>', encoding='utf-8')

    setup = _run(runtime, '/setup')
    data.step = 2
    unauthorized = _run(runtime, '/setup/smtp', cookie=_signed_session())
    wrong_step = _run(runtime, '/setup/igdb', cookie=_signed_session())

    assert setup.status_code == 200 and calls == ['start']
    assert unauthorized.status_code == 302
    assert unauthorized.headers['location'] == '/login?next=%2Fsetup%2Fsmtp'
    assert wrong_step.status_code == 302 and wrong_step.headers['location'] == '/setup'


def test_lazy_asgi_setup_transition_enforces_csrf_step_order_and_admin_session(monkeypatch):
    calls = []
    admin = SimpleNamespace(get_id=lambda: '81:setup-fingerprint')
    data = SimpleNamespace(
        current_step=lambda: 1,
        transition=lambda body, app, *, database_scope=None: calls.append((body['step'], app)) or (
            {'step': 2, 'next_url': '/setup/smtp'}, None, admin,
        ),
    )
    monkeypatch.setattr(native_setup_transition, 'SetupTransitionData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch)

    session = {}
    csrf = generate_csrf_token(session, 'native-asgi-browse-secret')
    cookie = dump_session_cookie(session, 'native-asgi-browse-secret')
    body = {'step': 1, 'username': 'first.admin', 'email': 'admin@example.com',
            'password': 'safe-password', 'confirm_password': 'safe-password'}

    missing_csrf = _run(runtime, '/api/setup/step', method='POST', cookie=cookie, json_body=body)
    wrong_step = _run(
        runtime, '/api/setup/step', method='POST', cookie=cookie,
        headers={'X-CSRFToken': csrf}, json_body={**body, 'step': 2},
    )
    created = _run(
        runtime, '/api/setup/step', method='POST', cookie=cookie,
        headers={'X-CSRFToken': csrf}, json_body=body,
    )

    assert missing_csrf.status_code == 400
    assert wrong_step.status_code == 409
    assert created.status_code == 200
    assert created.json()['step'] == 2
    assert any('session=' in value and 'Path=/' in value for value in created.headers.get_list('set-cookie'))
    assert len(calls) == 1 and calls[0][0] == 1


def test_lazy_asgi_setup_transition_requires_admin_after_account_creation(monkeypatch):
    calls = []
    data = SimpleNamespace(
        current_step=lambda: 2,
        transition=lambda *args: calls.append(args) or ({'step': 3}, None, None),
    )
    monkeypatch.setattr(native_setup_transition, 'SetupTransitionData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch)
    cookie, csrf = _signed_session_with_csrf()

    response = _run(
        runtime, '/api/setup/step', method='POST', cookie=cookie,
        headers={'X-CSRFToken': csrf}, json_body={'step': 2, 'skip': True},
    )

    assert response.status_code == 401
    assert calls == []


def test_lazy_asgi_setup_form_posts_translate_fields_and_keep_csrf_session(monkeypatch):
    calls = []
    admin = SimpleNamespace(get_id=lambda: '81:setup-fingerprint')

    class FakeSetupTransitionData:
        def current_step(self):
            return 1

        def transition(self, body, _app, *, database_scope=None):
            calls.append(body)
            return {'step': 2, 'next_url': '/setup/smtp'}, None, admin

    monkeypatch.setattr(
        native_setup_transition, 'SetupTransitionData', FakeSetupTransitionData,
    )
    _flask_app, runtime = _runtime(monkeypatch)
    session = {}
    csrf = generate_csrf_token(session, 'native-asgi-browse-secret')
    cookie = dump_session_cookie(session, 'native-asgi-browse-secret')

    response = _run(
        runtime, '/setup/submit', method='POST', cookie=cookie,
        form_body={
            'csrf_token': csrf, 'username': 'first.admin',
            'email': 'admin@example.com', 'password': 'safe-password',
            'confirm_password': 'safe-password',
        },
    )

    assert response.status_code == 302
    assert response.headers['location'] == '/setup/smtp'
    assert calls[0]['step'] == 1 and calls[0]['username'] == 'first.admin'
    assert any('session=' in value for value in response.headers.get_list('set-cookie'))
    saved_session = load_session_cookie(
        response.cookies['session'], 'native-asgi-browse-secret', max_age=31_536_000,
    )
    assert saved_session['_user_id'] == '81:setup-fingerprint'
    assert saved_session['_flashes'][-1] == (
        'success', 'Admin account created successfully! Please configure your SMTP settings.',
    )


def test_lazy_asgi_setup_feature_form_requires_valid_csrf_and_maps_checkboxes(monkeypatch):
    calls = []
    data = SimpleNamespace(
        current_step=lambda: 3,
        transition=lambda body, _app, *, database_scope=None: calls.append(body) or (
            {'step': 4, 'next_url': '/setup/igdb'}, None, None,
        ),
    )
    monkeypatch.setattr(native_setup_transition, 'SetupTransitionData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()

    rejected = _run(
        runtime, '/setup/features', method='POST', cookie=cookie,
        form_body={'csrf_token': 'wrong', 'enable_game_updates': 'on'},
    )
    missing = _run(
        runtime, '/setup/features', method='POST', cookie=cookie, form_body={},
    )
    accepted = _run(
        runtime, '/setup/features', method='POST', cookie=cookie,
        form_body={
            'csrf_token': csrf, 'enable_game_updates': 'on',
            'enable_ai_assist': 'on',
        },
    )

    assert rejected.status_code == 400
    assert rejected.headers['content-type'] == 'text/html; charset=utf-8'
    assert b'<p>The CSRF token is invalid.</p>' in rejected.content
    assert missing.status_code == 400
    assert missing.headers['content-type'] == 'text/html; charset=utf-8'
    assert b'<p>The CSRF token is missing.</p>' in missing.content
    assert {
        key: calls[0][key]
        for key in (
            'step', 'skip', 'enable_game_updates', 'enable_game_extras',
            'attract_mode_enabled', 'enable_arr_module', 'enable_ai_assist',
            'enable_malware_scan',
        )
    } == {
        'step': 3, 'skip': False, 'enable_game_updates': True,
        'enable_game_extras': False, 'attract_mode_enabled': False,
        'enable_arr_module': False, 'enable_ai_assist': True,
        'enable_malware_scan': False,
    }
    assert accepted.status_code == 302
    assert accepted.headers['location'] == '/setup/igdb'


def test_native_setup_form_adapter_maps_remaining_step_fields():
    from oneirodex.runtime_native.setup_transition import _setup_form_payload

    smtp, target, error = _setup_form_payload('/setup/smtp', {
        'smtp_server': 'mail.example.test', 'smtp_port': '2525',
        'smtp_username': 'sender', 'smtp_password': 'smtp-secret',
        'smtp_use_tls': 'true', 'smtp_enabled': 'true',
    })
    assert error is None and target == '/setup/smtp'
    assert (smtp['step'], smtp['smtp_port'], smtp['smtp_use_tls'], smtp['smtp_enabled']) == (
        2, 2525, True, True,
    )
    assert smtp['smtp_password'] == 'smtp-secret'

    igdb, target, error = _setup_form_payload('/setup/igdb', {'skip_igdb': '1'})
    assert error is None and target == '/setup/igdb'
    assert igdb['step'] == 4 and igdb['skip'] is True

    integrations, target, error = _setup_form_payload('/setup/integrations', {
        'configure_steam_web_api_key': 'on', 'steam_web_api_key': 'steam-key',
        'mobygames_api_key': 'must-be-ignored', 'configure_oidc': 'on',
        'oidc_issuer_url': 'https://identity.example.test',
        'oidc_client_id': 'oneirodex', 'oidc_scopes': 'openid email',
        'enable_hltb_integration': 'on',
    })
    assert error is None and target == '/setup/integrations'
    assert integrations['step'] == 5 and integrations['configure_oidc'] is True
    assert integrations['steam_web_api_key'] == 'steam-key'
    assert integrations['mobygames_api_key'] == ''
    assert integrations['enable_hltb_integration'] is True

    library, target, error = _setup_form_payload('/setup/library', {
        'name': 'Retro', 'platform': 'NES', 'folder_path': 'C:/Games/NES',
        'scan_mode': 'files', 'scan_depth': '2',
    })
    assert error is None and target == '/setup/library'
    assert (library['step'], library['library_name'], library['scan_mode'], library['scan_depth']) == (
        6, 'Retro', 'files', 2,
    )


def test_lazy_asgi_login_form_uses_native_auth_and_remember_cookie(monkeypatch):
    user = SimpleNamespace(get_id=lambda: '7:fp')
    calls = []

    class FakeLoginData:
        def authenticate(self, username, password, ip):
            calls.append((username, password, ip))
            return user, None

    monkeypatch.setattr(native_auth_login, 'AuthLoginData', FakeLoginData)
    _flask_app, runtime = _runtime(monkeypatch)
    session = {}
    csrf = generate_csrf_token(session, 'native-asgi-browse-secret')
    cookie = dump_session_cookie(session, 'native-asgi-browse-secret')

    response = _run(
        runtime, '/login?next=%2Flibrary', method='POST', cookie=cookie,
        form_body={'csrf_token': csrf, 'username': 'player', 'password': 'secret'},
    )

    assert response.status_code == 302 and response.headers['location'] == '/library'
    assert calls and calls[0][:2] == ('player', 'secret')
    saved_session = load_session_cookie(
        response.cookies['session'], 'native-asgi-browse-secret', max_age=31_536_000,
    )
    assert saved_session['_user_id'] == '7:fp'
    assert any('remember_token=' in value for value in response.headers.get_list('set-cookie'))


def test_native_login_partitioned_session_cookie_matches_flask(monkeypatch):
    from flask import Flask, session as flask_session
    from http.cookies import SimpleCookie

    user = SimpleNamespace(get_id=lambda: '7:fp')
    monkeypatch.setattr(
        native_auth_login, 'AuthLoginData',
        lambda: SimpleNamespace(authenticate=lambda *_args: (user, None)),
    )
    flask_app, runtime = _runtime(monkeypatch)
    cookie_config = {
        'SESSION_COOKIE_NAME': 'session',
        'SESSION_COOKIE_DOMAIN': 'example.test',
        'SESSION_COOKIE_PATH': '/',
        'SESSION_COOKIE_SECURE': True,
        'SESSION_COOKIE_HTTPONLY': True,
        'SESSION_COOKIE_SAMESITE': 'Lax',
        'SESSION_COOKIE_PARTITIONED': True,
    }
    flask_app.config.update(cookie_config)
    session_data = {}
    csrf = generate_csrf_token(session_data, flask_app.config['SECRET_KEY'])
    current = _run(
        runtime, '/login', method='POST',
        cookie=dump_session_cookie(session_data, flask_app.config['SECRET_KEY']),
        form_body={'csrf_token': csrf, 'username': 'player', 'password': 'secret'},
        base_url='https://example.test',
    )

    legacy_app = Flask(__name__)
    legacy_app.config.update(SECRET_KEY=flask_app.config['SECRET_KEY'], **cookie_config)

    @legacy_app.get('/set-session')
    def legacy_set_session():
        flask_session['_user_id'] = '7:fp'
        flask_session['_fresh'] = True
        return 'ok'

    legacy = legacy_app.test_client().get('/set-session')

    def cookie_attributes(values):
        jar = SimpleCookie()
        for value in values:
            jar.load(value)
        cookie = jar['session']
        return (
            cookie['path'], cookie['domain'], cookie['secure'],
            cookie['httponly'], cookie['samesite'].lower(), cookie['partitioned'],
        )

    assert current.status_code == 302
    assert cookie_attributes(current.headers.get_list('set-cookie')) == cookie_attributes(
        [legacy.headers['Set-Cookie']],
    )
    assert cookie_attributes(current.headers.get_list('set-cookie'))[-1] is True


def test_lazy_asgi_invite_registration_form_clears_inviter_session(monkeypatch):
    calls = []

    class FakeRegistrationData:
        def register(self, payload, invite, request, config):
            calls.append((payload, invite))
            return {'registered': True, 'confirmation_sent': True}, None

    monkeypatch.setattr(native_auth_registration, 'AuthRegistrationData', FakeRegistrationData)
    _flask_app, runtime = _runtime(monkeypatch)
    session = {'_user_id': '7:fp', '_fresh': True}
    csrf = generate_csrf_token(session, 'native-asgi-browse-secret')
    cookie = dump_session_cookie(session, 'native-asgi-browse-secret')

    response = _run(
        runtime, '/register?token=invite-123', method='POST', cookie=cookie,
        form_body={
            'csrf_token': csrf, 'username': 'new.player',
            'email': 'new@example.com', 'password': 'secure-password',
        },
    )

    assert response.status_code == 302 and response.headers['location'] == '/'
    assert calls[0][1] == 'invite-123'
    saved_session = load_session_cookie(
        response.cookies['session'], 'native-asgi-browse-secret', max_age=31_536_000,
    )
    assert '_user_id' not in saved_session
    assert any('remember_token=' in value for value in response.headers.get_list('set-cookie'))


def test_lazy_asgi_password_reset_forms_use_native_adapters(monkeypatch):
    calls = []

    class FakeResetData:
        def request_reset(self, email, ip, request, config):
            calls.append(('request', email, ip))
            return 'requested'

        def valid_reset_token(self, token):
            calls.append(('valid', token))
            return True

        def reset(self, token, password):
            calls.append(('reset', token, password))
            return True

    monkeypatch.setattr(native_password_reset_confirm, 'PasswordResetConfirmData', FakeResetData)
    _flask_app, runtime = _runtime(monkeypatch)
    session = {}
    csrf = generate_csrf_token(session, 'native-asgi-browse-secret')
    cookie = dump_session_cookie(session, 'native-asgi-browse-secret')

    requested = _run(
        runtime, '/reset_password_request', method='POST', cookie=cookie,
        form_body={'csrf_token': csrf, 'email': 'player@example.com'},
    )
    reset = _run(
        runtime, '/reset_password/token-123', method='POST', cookie=cookie,
        form_body={
            'csrf_token': csrf, 'password': 'new-password',
            'confirm_password': 'new-password',
        },
    )

    assert requested.status_code == 302 and requested.headers['location'] == '/login'
    assert reset.status_code == 302 and reset.headers['location'] == '/login'
    assert ('request', 'player@example.com', '127.0.0.1') in calls
    assert ('valid', 'token-123') in calls
    assert ('reset', 'token-123', 'new-password') in calls


def test_lazy_asgi_invite_management_forms_use_browser_session_and_native_data(monkeypatch):
    calls = []
    origins = []

    class FakeInviteData:
        def create(self, user, email, *, origin=None):
            calls.append(('create', user.id, email))
            origins.append(origin)
            return {'invite': {'token': 'invite-456'}, 'emailed': False}

        def delete(self, user, token):
            calls.append(('delete', user.id, token))
            return {'error': 'Invite not found.', 'code': 'not_found'}

    _flask_app, runtime = _runtime(monkeypatch)
    monkeypatch.setattr(account_summary, 'AccountInvitesData', lambda: FakeInviteData())
    cookie, csrf = _signed_session_with_csrf()

    page = _run(runtime, '/user/invites', cookie=cookie)
    created = _run(
        runtime, '/user/invites', method='POST', cookie=cookie,
        form_body={'csrf_token': csrf, 'email': 'friend@example.com'},
    )
    deleted = _run(
        runtime, '/delete_invite/missing-token', method='POST', cookie=cookie,
        form_body={'csrf_token': csrf},
    )

    assert page.status_code == 302 and page.headers['location'] == '/library?account=invites'
    assert created.status_code == 302 and created.headers['location'] == '/library?account=invites'
    assert deleted.status_code == 200 and deleted.json()['error_code'] == 'not_found'
    assert calls == [
        ('create', 7, 'friend@example.com'), ('delete', 7, 'missing-token'),
    ]
    assert origins == ['http://testserver']


def test_lazy_asgi_public_demo_uses_native_lookup_and_compatible_session(monkeypatch):
    monkeypatch.setenv('ONEIRODEX_PUBLIC_DEMO', 'true')
    _flask_app, runtime = _runtime(monkeypatch)
    user = SimpleNamespace(id=7, get_id=lambda: '7:fp')
    calls = []
    monkeypatch.setattr(
        auth_demo, 'PublicDemoData',
        lambda: SimpleNamespace(demo_user=lambda: calls.append('lookup') or user),
    )

    response = _run(runtime, '/demo')
    assert response.status_code == 302 and response.headers['location'] == '/discover'
    assert response.headers['cache-control'] == 'no-store'
    cookie = response.cookies.get('session')
    assert cookie
    session = load_session_cookie(
        cookie, 'native-asgi-browse-secret', max_age=31_536_000,
    )
    assert session['_user_id'] == '7:fp' and session['_fresh'] is True
    assert session['_id'] and '_remember' not in session
    assert calls == ['lookup']

    head = _run(runtime, '/demo', method='HEAD')
    assert head.status_code == 302 and head.content == b''


def test_lazy_asgi_public_demo_keeps_disabled_and_missing_user_responses(monkeypatch):
    _flask_app, disabled_runtime = _runtime(monkeypatch)
    disabled = _run(disabled_runtime, '/demo')
    assert disabled.status_code == 404
    assert disabled.headers['cache-control'] == 'no-store'

    monkeypatch.setenv('ONEIRODEX_PUBLIC_DEMO', 'yes')
    _flask_app, missing_runtime = _runtime(monkeypatch)
    monkeypatch.setattr(
        auth_demo, 'PublicDemoData', lambda: SimpleNamespace(demo_user=lambda: None),
    )
    missing = _run(missing_runtime, '/demo')
    assert missing.status_code == 503
    assert missing.headers['cache-control'] == 'no-store'


def test_lazy_asgi_dispatches_registration_with_validation_invite_logout_and_csrf(monkeypatch):
    calls = []
    data = SimpleNamespace(register=lambda payload, invite, *_args: calls.append(
        (payload, invite)
    ) or ({
        'requested': True,
        'message': 'If the details can be used to create an account, check your email for next steps.',
        'next_url': '/login',
    }, None))
    monkeypatch.setattr(native_auth_registration, 'AuthRegistrationData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch)
    session = {}
    csrf = generate_csrf_token(session, 'native-asgi-browse-secret')
    cookie = dump_session_cookie(session, 'native-asgi-browse-secret')
    headers = {'X-CSRFToken': csrf}
    body = {
        'username': 'player.one', 'email': 'player@example.com', 'password': 'secure-password',
    }

    missing_csrf = _run(
        runtime, '/api/auth/register', method='POST', cookie=cookie, json_body=body,
    )
    invalid = _run(
        runtime, '/api/auth/register', method='POST', cookie=cookie,
        headers=headers, json_body={**body, 'username': 'system'},
    )
    registered = _run(
        runtime, '/api/auth/register?token=invite-123', method='POST', cookie=cookie,
        headers=headers, json_body=body,
    )
    signed_cookie, signed_csrf = _signed_session_with_csrf()
    conflict = _run(
        runtime, '/api/auth/register', method='POST', cookie=signed_cookie,
        headers={'X-CSRFToken': signed_csrf}, json_body=body,
    )
    invited_signed_in = _run(
        runtime, '/api/auth/register?token=invite-456', method='POST', cookie=signed_cookie,
        headers={'X-CSRFToken': signed_csrf}, json_body=body,
    )

    assert missing_csrf.status_code == 400
    assert invalid.status_code == 422
    assert registered.status_code == invited_signed_in.status_code == 202
    assert registered.json()['requested'] is True
    assert conflict.status_code == 409
    assert any(
        value.startswith('remember_token=') and 'max-age=0' in value.lower()
        for value in invited_signed_in.headers.get_list('set-cookie')
    )
    assert calls == [
        (body, 'invite-123'),
        (body, 'invite-456'),
    ]


def test_lazy_asgi_dispatches_password_reset_confirmation_with_csrf_and_session_rules(monkeypatch):
    calls = []
    data = SimpleNamespace(reset=lambda token, password: calls.append(
        (token, password)
    ) or token != 'expired-token')
    monkeypatch.setattr(native_password_reset_confirm, 'PasswordResetConfirmData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch)
    session = {}
    csrf = generate_csrf_token(session, 'native-asgi-browse-secret')
    cookie = dump_session_cookie(session, 'native-asgi-browse-secret')
    payload = {'password': 'long-password', 'confirm_password': 'long-password'}

    no_csrf = _run(
        runtime, '/api/auth/password-reset/signed-token', method='POST',
        cookie=_signed_session(), json_body=payload,
    )
    reset = _run(
        runtime, '/api/auth/password-reset/signed-token', method='POST', cookie=cookie,
        headers={'X-CSRFToken': csrf}, json_body=payload,
    )
    mismatch = _run(
        runtime, '/api/auth/password-reset/signed-token', method='POST', cookie=cookie,
        headers={'X-CSRFToken': csrf},
        json_body={'password': 'long-password', 'confirm_password': 'different-password'},
    )
    invalid_token = _run(
        runtime, '/api/auth/password-reset/expired-token', method='POST', cookie=cookie,
        headers={'X-CSRFToken': csrf}, json_body=payload,
    )
    signed_cookie, signed_csrf = _signed_session_with_csrf()
    signed_in = _run(
        runtime, '/api/auth/password-reset/signed-token', method='POST', cookie=signed_cookie,
        headers={'X-CSRFToken': signed_csrf}, json_body=payload,
    )

    assert no_csrf.status_code == 400
    assert reset.status_code == 200 and reset.json()['reset'] is True
    assert mismatch.status_code == 422
    assert invalid_token.status_code == 400
    assert signed_in.status_code == 409
    assert calls == [('signed-token', 'long-password'), ('expired-token', 'long-password')]


def test_lazy_asgi_dispatches_password_reset_request_without_disclosing_account_or_sending_mail(monkeypatch):
    calls = []
    data = SimpleNamespace(
        request_reset=lambda email, ip, *_args: calls.append((email, ip)) or (
            'rate_limited' if email == 'limited@example.com' else 'requested'
        ),
        reset=lambda _token, _password: False,
    )
    monkeypatch.setattr(native_password_reset_confirm, 'PasswordResetConfirmData', lambda: data)
    flask_app, runtime = _runtime(monkeypatch)
    flask_app.config['TRUSTED_PROXIES'] = 1
    flask_app.config['TRUSTED_PROXY_CIDRS'] = '127.0.0.1/32'
    session = {'_flashes': [['info', 'prior message']]}
    csrf = generate_csrf_token(session, 'native-asgi-browse-secret')
    cookie = dump_session_cookie(session, 'native-asgi-browse-secret')
    headers = {'X-CSRFToken': csrf, 'X-Forwarded-For': '203.0.113.4, 198.51.100.8'}

    missing_csrf = _run(
        runtime, '/api/auth/password-reset/request', method='POST', cookie=cookie,
        json_body={'email': 'member@example.com'},
    )
    invalid = _run(
        runtime, '/api/auth/password-reset/request', method='POST', cookie=cookie,
        headers=headers, json_body={'email': 'not-an-email'},
    )
    known = _run(
        runtime, '/api/auth/password-reset/request', method='POST', cookie=cookie,
        headers=headers, json_body={'email': 'member@example.com'},
    )
    unknown = _run(
        runtime, '/api/auth/password-reset/request', method='POST', cookie=cookie,
        headers=headers, json_body={'email': 'missing@example.com'},
    )
    limited = _run(
        runtime, '/api/auth/password-reset/request', method='POST', cookie=cookie,
        headers=headers, json_body={'email': 'limited@example.com'},
    )
    signed_cookie, signed_csrf = _signed_session_with_csrf()
    signed_in = _run(
        runtime, '/api/auth/password-reset/request', method='POST', cookie=signed_cookie,
        headers={'X-CSRFToken': signed_csrf}, json_body={'email': 'member@example.com'},
    )

    assert missing_csrf.status_code == 400
    assert invalid.status_code == 422
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()
    assert known.headers['cache-control'] == 'no-store'
    assert limited.status_code == 429
    assert signed_in.status_code == 409
    assert calls == [
        ('member@example.com', '198.51.100.8'),
        ('missing@example.com', '198.51.100.8'),
        ('limited@example.com', '198.51.100.8'),
    ]


def test_lazy_asgi_dispatches_server_settings_with_admin_csrf_and_safe_projection(monkeypatch):
    calls = []
    state = {
        'settings': {'showHelpButton': True, 'siteUrl': 'https://oneirodex.test'},
        'bounds': {'scanThreadCount': {'min': 1, 'max': 4, 'step': 1}},
        'text_limits': {'siteUrl': 255},
    }
    data = SimpleNamespace(
        state=lambda: state,
        save=lambda payload: calls.append(payload) or (state, None, None),
    )
    monkeypatch.setattr(native_admin_server_settings, 'AdminServerSettingsData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()

    response = _run(runtime, '/api/admin/server-settings', cookie=_signed_session())
    head = _run(runtime, '/api/admin/server-settings', cookie=_signed_session(), method='HEAD')
    no_csrf = _run(
        runtime, '/api/admin/server-settings', method='PUT', cookie=_signed_session(),
        json_body={'showHelpButton': False},
    )
    saved = _run(
        runtime, '/api/admin/server-settings', method='PUT', cookie=cookie,
        headers={'X-CSRFToken': csrf}, json_body={'showHelpButton': False},
    )

    assert response.status_code == saved.status_code == 200
    assert response.json()['settings'] == state['settings']
    assert 'text_limits' in response.json() and 'bounds' in response.json()
    assert head.status_code == 200 and head.content == b''
    assert no_csrf.status_code == 400
    assert calls == [{'showHelpButton': False}]


def test_lazy_asgi_dispatches_admin_ops_reads_with_bounds_and_head(monkeypatch):
    calls = []
    data = SimpleNamespace(
        logs=lambda limit: calls.append(('logs', limit)) or {'events': []},
        system=lambda app: calls.append(('system', app.name)) or {
            'system': {}, 'database': {}, 'active_users': 0, 'logs': {'count': 0, 'latest': None},
            'config': {}, 'theme_assets': {},
        },
        summary=lambda app: calls.append(('summary', app.name)) or {'health': 'ok'},
        devices=lambda limit, app: calls.append(('devices', limit, app.name)) or {'devices': []},
        library_health=lambda app: calls.append(('library_health', app.name)) or {'score': 100},
        image_refresh_progress=lambda game_uuid: {'status': 'error', 'game_uuid': game_uuid},
        library_delete_progress=lambda job_id: {'status': 'error', 'job_id': job_id},
        library_deletion_progress=lambda: {'sse-job': {'status': 'completed'}},
    )
    scan_calls = []

    class FakeScanJobMutations:
        def cancel(self, job_id):
            scan_calls.append(('cancel', job_id))
            return ('Scan job is stopping.', 'message')

        def delete(self, job_id):
            scan_calls.append(('delete', job_id))
            return True

        def clear(self, status=None):
            scan_calls.append(('clear', status))
            return (2, 'scan jobs')

        def restart(self, job_id, *, queue_policy, app, database_scope):
            scan_calls.append(('restart', job_id, queue_policy))
            return {'status': 'started', 'message': 'Scan restarted.'}

    monkeypatch.setattr(native_admin_ops_reads, 'AdminOpsReadData', lambda: data)
    monkeypatch.setattr(
        native_scan_job_mutations, 'ScanJobMutationData', FakeScanJobMutations,
    )
    flask_app, runtime = _runtime(monkeypatch, admin=True)
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('Native Ops route pushed a Flask app context')
    )
    cookie = _signed_session()

    logs = _run(runtime, '/admin/api/ops/logs?limit=900', cookie=cookie)
    system = _run(runtime, '/admin/api/ops/system', cookie=cookie)
    summary = _run(runtime, '/admin/api/ops/summary', cookie=cookie)
    devices = _run(runtime, '/admin/api/ops/devices?limit=9999', cookie=cookie)
    health = _run(runtime, '/admin/api/library/health', cookie=cookie, method='HEAD')
    image_progress = _run(runtime, '/check_image_refresh_progress/game-1', cookie=cookie)
    deletion_progress = _run(runtime, '/check_deletion_progress/job-1', cookie=cookie)
    deletion_stream = _run(runtime, '/delete_library_progress/sse-job', cookie=cookie)
    csrf_cookie, csrf = _signed_session_with_csrf()
    cancel_scan = _run(
        runtime, '/cancel_scan_job/job-1', cookie=csrf_cookie, method='POST',
        form_body={'csrf_token': csrf},
    )
    restart_scan = _run(
        runtime, '/restart_scan_job/job-2', cookie=csrf_cookie, method='POST',
        form_body={'csrf_token': csrf, 'queue_policy': 'force'},
    )

    assert logs.status_code == summary.status_code == devices.status_code == health.status_code == 200
    assert system.status_code == 200 and 'theme_assets' in system.json()
    assert logs.json() == {'events': []}
    assert summary.json() == {'health': 'ok'}
    assert devices.json() == {
        'devices': [], 'ok': True, 'success': True,
        'error': None, 'error_code': None,
    }
    assert health.content == b''
    assert image_progress.json() == {'status': 'error', 'game_uuid': 'game-1'}
    assert deletion_progress.json() == {'status': 'error', 'job_id': 'job-1'}
    assert deletion_stream.status_code == 200
    assert deletion_stream.headers['content-type'].startswith('text/event-stream')
    assert '"status": "completed"' in deletion_stream.text
    assert cancel_scan.status_code == 302
    assert cancel_scan.headers['location'] == '/admin/scan_management?active_tab=jobs'
    assert restart_scan.status_code == 302
    assert scan_calls == [('cancel', 'job-1'), ('restart', 'job-2', 'force')]
    assert calls == [
        ('logs', 200), ('system', flask_app.name), ('summary', flask_app.name),
        ('devices', 1000, flask_app.name), ('library_health', flask_app.name),
    ]


def test_ops_system_log_projection_serializes_latest_event(monkeypatch):
    from oneirodex import routes_info

    timestamp = datetime(2026, 10, 14, tzinfo=timezone.utc)
    latest = SimpleNamespace(
        id=12, timestamp=timestamp, event_level='ERROR',
        event_type='test', event_text='snapshot marker',
    )
    monkeypatch.setattr(
        routes_info, 'get_log_info', lambda: {'count': 1, 'latest': latest},
    )

    assert routes_info._log_summary() == {
        'count': 1,
        'latest': {
            'id': 12, 'timestamp': timestamp.isoformat(), 'level': 'ERROR',
            'type': 'test', 'text': 'snapshot marker',
        },
    }


def test_lazy_asgi_dispatches_support_ticket_reads_natively(monkeypatch):
    calls = []
    ticket = SimpleNamespace(
        id=42, user_id=7,
        to_dict=lambda compact=False: {'id': 42, 'compact': compact},
    )
    data = SimpleNamespace(
        list_tickets=lambda user, *, admin: calls.append(('list', user.id, admin)) or [ticket],
        ticket=lambda ticket_id: calls.append(('ticket', ticket_id)) or ticket,
    )
    monkeypatch.setattr(native_support_reads, 'SupportReadsData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch)

    response = _run(runtime, '/api/support/tickets', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json() == {'tickets': [{'id': 42, 'compact': True}], 'empty': False}
    assert calls == [('list', 7, False)]


def test_lazy_asgi_dispatches_theme_font_catalogue_natively(monkeypatch):
    data = SimpleNamespace(catalogue=lambda: {
        'fonts': [{'id': 'fixture'}], 'platform_hints': {}, 'fonts_dir': '/fonts', 'note': 'fixture',
    })
    monkeypatch.setattr(native_theme_fonts_read, 'ThemeFontsData', lambda *_args: data)
    _flask_app, runtime = _runtime(monkeypatch)

    response = _run(runtime, '/api/theme/fonts', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json()['fonts'][0]['id'] == 'fixture'


def test_lazy_asgi_dispatches_admin_provider_catalogs_natively(monkeypatch):
    calls = []
    data = SimpleNamespace(
        artwork_providers=lambda: calls.append(('artwork',)) or [{'id': 'fixture'}],
        patch_catalog=lambda config: calls.append(('patch', bool(config.get('TESTING')))
            ) or {'module_enabled': False, 'catalog_path': None, 'providers': []},
    )
    monkeypatch.setattr(native_provider_catalog_reads, 'ProviderCatalogData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch, admin=True)

    artwork = _run(runtime, '/api/providers', cookie=_signed_session())
    patch_catalog = _run(runtime, '/api/patch-catalog/providers', cookie=_signed_session())

    assert artwork.status_code == 200 and artwork.json() == {'providers': [{'id': 'fixture'}]}
    assert patch_catalog.status_code == 200
    assert patch_catalog.json() == {'module_enabled': False, 'catalog_path': None, 'providers': []}
    assert calls == [('artwork',), ('patch', True)]


def test_lazy_asgi_dispatches_integrations_inventory_natively(monkeypatch):
    calls = []
    data = SimpleNamespace(inventory=lambda: calls.append(('inventory',)) or [
        {'id': 'igdb', 'configured': True},
    ])
    monkeypatch.setattr(native_integrations_inventory, 'IntegrationsInventoryData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch, admin=True)

    response = _run(runtime, '/api/admin/integrations/inventory', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json() == {
        'integrations': [{'id': 'igdb', 'configured': True}],
        'count': 1,
        'hub_href': '/admin/integrations',
    }
    assert calls == [('inventory',)]


def test_lazy_asgi_dispatches_integration_settings_natively(monkeypatch):
    calls = []
    data = SimpleNamespace(
        oidc_read=lambda: {'settings': {'configured': True}, 'readiness': {'ready': True}},
        oidc_save=lambda payload: calls.append(('oidc', payload)) or {'settings': {'configured': True}},
        community_read=lambda: {'community_chat_url': '', 'community_chat_label': 'Open community'},
        community_save=lambda url, label: calls.append(('community', url, label)) or {
            'community_chat_url': url, 'community_chat_label': label,
        },
    )
    monkeypatch.setattr(native_integration_settings, 'IntegrationSettingsData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()

    read = _run(runtime, '/api/admin/integrations/oidc', cookie=_signed_session())
    write = _run(
        runtime, '/api/admin/integrations/community', cookie=cookie, method='PUT',
        headers={'X-CSRFToken': csrf},
        json_body={'community_chat_url': 'https://community.example', 'community_chat_label': 'Chat'},
    )

    assert read.status_code == 200 and read.json()['settings']['configured'] is True
    assert write.status_code == 200 and write.json()['community_chat_label'] == 'Chat'
    assert calls == [('community', 'https://community.example', 'Chat')]


def test_lazy_asgi_dispatches_ownership_admin_connections_natively(monkeypatch):
    calls = []
    data = SimpleNamespace(connections=lambda cursor: calls.append(cursor) or {
        'schema_version': 1, 'household': {}, 'members': [], 'next_after_id': None,
        'stale_running_jobs': [],
    }, member_store_problem=lambda *_args: None,
       cancel=lambda user_id, store: ({'job': {'id': 'job-1', 'user_id': user_id, 'store': store}}, None))
    monkeypatch.setattr(native_ownership_admin_reads, 'OwnershipAdminReadData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch, admin=True)

    response = _run(
        runtime, '/api/admin/ownership/connections?after_id=9', cookie=_signed_session(),
    )

    assert response.status_code == 200
    assert response.json()['schema_version'] == 1
    assert calls == [9]

    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()
    cancel = _run(
        runtime, '/api/admin/ownership/connections/9/steam/cancel', cookie=cookie,
        method='POST', headers={'X-CSRFToken': csrf},
    )
    assert cancel.status_code == 202
    assert cancel.json()['job']['store'] == 'steam'


def test_lazy_asgi_dispatches_artwork_provider_search_natively(monkeypatch):
    calls = []
    result = SimpleNamespace(to_dict=lambda: {'id': 'art-1'})
    provider = SimpleNamespace(
        id='steamgriddb', is_enabled=lambda: True,
        search_artwork=lambda query, limit, art_kind: (
            calls.append((query, limit, art_kind)) or [result]
        ),
    )
    data = SimpleNamespace(provider=lambda name: provider)
    monkeypatch.setattr(native_artwork_provider_search, 'ArtworkProviderSearchData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch, admin=True)

    response = _run(
        runtime, '/api/providers/steamgriddb/search?q=fixture&limit=5&kind=cover',
        cookie=_signed_session(),
    )

    assert response.status_code == 200
    assert response.json()['results'] == [{'id': 'art-1'}]
    assert calls == [('fixture', 5, 'cover')]


def test_lazy_asgi_dispatches_patch_catalog_search_and_attach_natively(monkeypatch):
    calls = []
    hit = SimpleNamespace(to_dict=lambda: {'provider': 'fixture', 'url': 'https://patch.test'})
    game = SimpleNamespace(uuid='game-1', name='Fixture')
    data = SimpleNamespace(
        enabled=lambda _app: True,
        game=lambda uuid: game if uuid == 'game-1' else None,
        search=lambda query, **kwargs: calls.append(('search', query, kwargs)) or [hit],
        can_access_game=lambda user, found: user.id == 7 and found is game,
        attach=lambda found, **kwargs: calls.append(('attach', found.uuid, kwargs)) or {
            'game_uuid': found.uuid, 'source_url': kwargs['source_url'],
        },
    )
    monkeypatch.setattr(native_patch_catalog, 'PatchCatalogData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()

    search = _run(runtime, '/api/patch-catalog/search?q=Fixture&limit=4', cookie=_signed_session())
    attach = _run(
        runtime, '/api/patch-catalog/attach', cookie=cookie, method='POST',
        headers={'X-CSRFToken': csrf}, json_body={
            'game_uuid': 'game-1', 'source_url': 'https://patch.test/guide',
            'notes': 'fixture notes',
        },
    )

    assert search.status_code == 200 and search.json()['hits'][0]['provider'] == 'fixture'
    assert attach.status_code == 201 and attach.json()['game_uuid'] == 'game-1'
    assert calls[0][0:2] == ('search', 'Fixture')
    assert calls[1][0:2] == ('attach', 'game-1')


def test_lazy_asgi_dispatches_member_download_queue_natively(monkeypatch):
    data = SimpleNamespace(
        my_downloads=lambda user: [{'id': 5, 'user_id': user.id}],
        delete=lambda request_id: request_id == 5,
    )
    monkeypatch.setattr(native_download_request_reads, 'DownloadRequestReadData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch)

    response = _run(runtime, '/api/my_downloads', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json() == [{'id': 5, 'user_id': 7}]

    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()
    deleted = _run(
        runtime, '/api/delete_download/5', cookie=cookie, method='DELETE',
        headers={'X-CSRFToken': csrf},
    )
    assert deleted.status_code == 200
    assert deleted.json()['message'] == 'Download request deleted successfully'


def test_lazy_asgi_dispatches_manual_identify_options_natively(monkeypatch):
    data = SimpleNamespace(options=lambda: {
        'libraries': [{'uuid': 'lib-1'}], 'taxonomies': {}, 'categories': [], 'statuses': [],
    })
    monkeypatch.setattr(native_manual_identify_reads, 'ManualIdentifyReadData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch, admin=True)

    response = _run(
        runtime, '/api/admin/manual-identify/options', cookie=_signed_session(),
    )

    assert response.status_code == 200
    assert response.json()['libraries'] == [{'uuid': 'lib-1'}]


def test_lazy_asgi_dispatches_manual_identify_create_and_update_natively(monkeypatch):
    calls = []
    data = SimpleNamespace(
        create=lambda _app, body, actor, *, from_unmatched: calls.append(
            ('create', body.name, actor.id, from_unmatched)
        ) or {'game_uuid': 'created', 'redirect_url': '/admin/unmatched'},
        update=lambda _app, game_uuid, body, actor: calls.append(
            ('update', game_uuid, body.name, actor.id)
        ) or {'game_uuid': game_uuid, 'redirect_url': '/libraries'},
    )
    monkeypatch.setattr(native_manual_identify_mutations, 'ManualIdentifyMutationData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()
    payload = {
        'igdb_id': 2_000_000_420, 'name': 'Fixture game',
        'full_disk_path': '/safe/game', 'library_uuid': 'library-1',
        'summary': '', 'storyline': '', 'url': '', 'video_urls': '',
        'aggregated_rating': None, 'first_release_date': None,
        'status': '', 'category': '', 'item_kind': 'game',
        'developer': '', 'publisher': '', 'genre_ids': [], 'game_mode_ids': [],
        'theme_ids': [], 'platform_ids': [], 'player_perspective_ids': [],
        'provider_urls': {},
    }
    created = _run(
        runtime, '/api/admin/manual-identify?from_unmatched=true', cookie=cookie,
        method='POST', headers={'X-CSRFToken': csrf}, json_body=payload,
    )
    updated = _run(
        runtime, '/api/admin/manual-identify/game-42', cookie=cookie,
        method='PUT', headers={'X-CSRFToken': csrf}, json_body=payload,
    )

    assert created.status_code == 201 and created.json()['game_uuid'] == 'created'
    assert updated.status_code == 200 and updated.json()['game_uuid'] == 'game-42'
    assert calls == [
        ('create', 'Fixture game', 7, True),
        ('update', 'game-42', 'Fixture game', 7),
    ]


def test_lazy_asgi_dispatches_retroachievements_settings_natively(monkeypatch):
    calls = []
    data = SimpleNamespace(
        settings=lambda: {'username': 'fixture', 'api_key_configured': True},
        save_settings=lambda **kwargs: calls.append(kwargs) or {
            'username': kwargs['username'], 'has_key': True,
        },
    )
    monkeypatch.setattr(native_retroachievements_settings, 'RetroAchievementsSettingsData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch, admin=True)

    response = _run(
        runtime, '/api/admin/integrations/retroachievements', cookie=_signed_session(),
    )

    assert response.status_code == 200
    assert response.json()['api_key_configured'] is True
    assert 'api_key' not in response.json()

    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()
    updated = _run(
        runtime, '/api/admin/integrations/retroachievements', cookie=cookie,
        method='PUT', headers={'X-CSRFToken': csrf},
        json_body={'username': 'fixture', 'api_key': 'never-echo', 'clear_api_key': False},
    )
    assert updated.status_code == 200
    assert 'never-echo' not in updated.text
    assert calls == [{'username': 'fixture', 'api_key': 'never-echo', 'clear_api_key': False}]


def test_lazy_asgi_dispatches_game_achievements_natively(monkeypatch):
    game = SimpleNamespace(uuid='game-1')
    data = SimpleNamespace(
        game=lambda uuid: game if uuid == 'game-1' else None,
        can_access_game=lambda user, found: user.id == 7 and found is game,
        achievement_fields=lambda _game: {
            'supports_achievements': False, 'ra_game_id': None, 'achievements': [],
        },
        configured=lambda: False,
        progress=lambda *_args: pytest.fail('disabled achievement projection must not fetch provider data'),
    )
    monkeypatch.setattr(native_retroachievements_settings, 'RetroAchievementsSettingsData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch)

    response = _run(runtime, '/api/games/game-1/achievements', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json()['unlocks_here'] is False
    assert response.json()['configured'] is False


def test_lazy_asgi_dispatches_retroachievements_match_natively(monkeypatch):
    calls = []
    data = SimpleNamespace(
        configured=lambda: True,
        supported_platforms=lambda: ['SNES'],
        match_platform=lambda platform, *, rehash: calls.append((platform, rehash)) or {
            'platform': platform, 'matched': 1,
        },
    )
    monkeypatch.setattr(native_retroachievements_settings, 'RetroAchievementsSettingsData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()

    response = _run(
        runtime, '/api/retroachievements/match', cookie=cookie, method='POST',
        headers={'X-CSRFToken': csrf}, json_body={'platform': 'snes', 'rehash': False},
    )

    assert response.status_code == 200
    assert response.json()['matched'] == 1
    assert calls == [('SNES', False)]


def test_lazy_asgi_dispatches_scan_match_policy_write_natively(monkeypatch):
    calls = []
    data = SimpleNamespace(
        scan_match_read=lambda: {'max_depth': 2},
        scan_match_save=lambda body: calls.append(body) or {'max_depth': body['max_depth']},
        remote_read=lambda: {}, remote_save=lambda body: body,
    )
    monkeypatch.setattr(native_admin_policy_settings, 'AdminPolicySettingsData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()

    response = _run(
        runtime, '/api/admin/scan-match/config', cookie=cookie, method='PUT',
        headers={'X-CSRFToken': csrf}, json_body={'max_depth': 4},
    )

    assert response.status_code == 200
    assert response.json()['max_depth'] == 4
    assert calls == [{'max_depth': 4}]


def test_lazy_asgi_dispatches_launcher_import_formats_natively(monkeypatch):
    data = SimpleNamespace(formats=lambda: [{'id': 'fixture', 'name': 'Fixture', 'store': 'playnite'}])
    monkeypatch.setattr(native_launcher_import_reads, 'LauncherImportReadData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch)

    response = _run(runtime, '/api/imports/launchers', cookie=_signed_session())

    assert response.status_code == 200
    assert response.json()['launchers'][0]['id'] == 'fixture'


def test_lazy_asgi_dispatches_download_request_and_cleanup_natively(monkeypatch):
    calls = []
    game = SimpleNamespace(
        uuid='12345678-1234-1234-1234-123456789abc', name='Fixture',
        full_disk_path='/storage/fixture',
    )
    data = SimpleNamespace(
        game=lambda _uuid: game,
        can_access=lambda _user, _game: True,
        resolve_version=lambda _game, **_kwargs: ('/storage/fixture', '/storage/fixture', 'version-1'),
        exists=lambda _path: True, allowed_bases=lambda _app: ['/storage'],
        safe_path=lambda _path, _bases: (True, None),
        zip_path=lambda _game, path, **_kwargs: path,
        create_request=lambda _game, user, **_kwargs: (
            calls.append(('create', user.id)) or SimpleNamespace(id=87, status='available')
        ),
        cleanup_orphans=lambda _game: calls.append(('cleanup',)) or {'removed': [], 'kept': []},
        log_cleanup=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(native_download_mutations, 'DownloadMutationData', lambda: data)
    cookie, csrf = _signed_session_with_csrf()
    _flask_app, runtime = _runtime(monkeypatch)

    created = _run(
        runtime, '/api/downloads/games/12345678-1234-1234-1234-123456789abc',
        cookie=cookie, method='POST', headers={'X-CSRFToken': csrf}, json_body={'kind': 'base'},
    )
    assert created.status_code == 200 and created.json()['download_id'] == 87

    admin_cookie, admin_csrf = _signed_session_with_csrf()
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    cleanup = _run(
        runtime, '/api/games/12345678-1234-1234-1234-123456789abc/versions/cleanup_orphans',
        cookie=admin_cookie, method='POST', headers={'X-CSRFToken': admin_csrf}, json_body={},
    )
    assert cleanup.status_code == 200 and cleanup.json()['ok'] is True
    assert calls == [('create', 7), ('cleanup',)]


def test_lazy_asgi_dispatches_support_create_and_resolve_natively(monkeypatch):
    calls = []
    data = SimpleNamespace(
        recent_count=lambda *_args: 0,
        create=lambda user, body, _now: calls.append(('create', user.id, body['title'])) or {
            'id': 17, 'title': body['title'], 'status': 'open',
        },
        resolve=lambda ticket_id, admin_id, _now: calls.append(('resolve', ticket_id, admin_id)) or {
            'id': ticket_id, 'status': 'resolved',
        },
    )
    monkeypatch.setattr(native_support_mutations, 'SupportMutationData', lambda: data)
    cookie, csrf = _signed_session_with_csrf()
    _flask_app, runtime = _runtime(monkeypatch)

    created = _run(
        runtime, '/api/support/tickets', cookie=cookie, method='POST',
        headers={'X-CSRFToken': csrf}, json_body={'title': 'Fixture report'},
    )
    assert created.status_code == 201 and created.json()['ticket']['id'] == 17

    cookie, csrf = _signed_session_with_csrf()
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    resolved = _run(
        runtime, '/api/support/tickets/17/resolve', cookie=cookie, method='POST',
        headers={'X-CSRFToken': csrf}, json_body={},
    )
    assert resolved.status_code == 200 and resolved.json()['ticket']['status'] == 'resolved'
    assert calls == [('create', 7, 'Fixture report'), ('resolve', 17, 7)]


def test_lazy_asgi_dispatches_launcher_import_natively(monkeypatch):
    calls = []
    outcome = SimpleNamespace(
        errors=[], imported=1, updated=0,
        to_dict=lambda: {'imported': 1, 'updated': 0, 'skipped': 0},
    )
    data = SimpleNamespace(
        enabled=lambda: True,
        launcher=lambda user_id, value, *, filename, launcher: (
            calls.append((user_id, value, filename, launcher)) or outcome
        ),
    )
    monkeypatch.setattr(native_launcher_import_mutations, 'LauncherImportMutationData', lambda: data)
    cookie, csrf = _signed_session_with_csrf()
    _flask_app, runtime = _runtime(monkeypatch)

    response = _run(
        runtime, '/api/imports/launcher?launcher=heroic', cookie=cookie, method='POST',
        headers={'X-CSRFToken': csrf, 'Content-Type': 'application/json'}, json_body={'Games': []},
    )

    assert response.status_code == 200
    assert response.json()['imported'] == 1
    assert calls == [(7, b'{"Games":[]}', '', 'heroic')]


def test_lazy_asgi_dispatches_artwork_apply_natively(monkeypatch):
    calls = []
    data = SimpleNamespace(
        game_exists=lambda game_uuid: game_uuid == 'game-1',
        apply=lambda game_uuid, url, *, provider_id, image_type: (
            calls.append((game_uuid, url, provider_id, image_type))
            or {'applied': True, 'game_uuid': game_uuid}
        ),
    )
    monkeypatch.setattr(native_artwork_apply_mutation, 'ArtworkApplyData', lambda: data)
    cookie, csrf = _signed_session_with_csrf()
    _flask_app, runtime = _runtime(monkeypatch, admin=True)

    response = _run(
        runtime, '/api/games/game-1/artwork/steamgriddb', cookie=cookie,
        method='POST', headers={'X-CSRFToken': csrf},
        json_body={'url': 'https://images.invalid/game.jpg', 'provider': 'igdb'},
    )

    assert response.status_code == 200
    assert response.json()['applied'] is True
    assert calls == [('game-1', 'https://images.invalid/game.jpg', 'igdb', 'cover')]


def test_lazy_asgi_dispatches_admin_attract_settings_natively(monkeypatch):
    calls = []
    data = SimpleNamespace(
        state=lambda settings: {'enabled': settings.get('enabled', False), 'idle_timeout': settings.get('idle_timeout', 60)},
        read_settings=lambda: {'enabled': False, 'idle_timeout': 60},
        filter_options=lambda: {'libraries': [], 'genres': [], 'themes': [], 'date_range': {'min_year': None, 'max_year': None}},
        save=lambda user, body: calls.append((user.id, body)) or body,
    )
    monkeypatch.setattr(native_admin_attract_mode, 'AdminAttractModeData', lambda: data)
    cookie, csrf = _signed_session_with_csrf()
    _flask_app, runtime = _runtime(monkeypatch, admin=True)

    response = _run(
        runtime, '/api/admin/attract-mode/settings', cookie=cookie, method='PUT',
        headers={'X-CSRFToken': csrf}, json_body={
            'enabled': True, 'idle_timeout': 75,
            'filters': {'genres': [], 'themes': []},
            'autoplay': {'enabled': False, 'skipFirst': 0, 'skipAfter': 0},
        },
    )

    assert response.status_code == 200
    assert response.json()['settings']['enabled'] is True
    assert calls[0][0] == 7


def test_lazy_asgi_dispatches_admin_feature_settings_natively(monkeypatch):
    calls = []
    fields = (
        'enable_arr_module', 'enable_ai_assist', 'enable_malware_scan',
        'enable_game_updates', 'enable_game_extras', 'attract_mode_enabled',
        'allow_children_in_household_lobby',
    )
    data = SimpleNamespace(
        read=lambda _config: {'preferences': {key: False for key in fields}, 'process': [], 'challenge': {}, 'scanner': {}},
        save_preferences=lambda body: calls.append(body) or body,
        save_challenge=lambda body: calls.append(('challenge', body)) or body,
        test_challenge=lambda: {'enabled': True, 'reachable': True, 'probe_ok': True},
    )
    monkeypatch.setattr(native_admin_features, 'AdminFeaturesData', lambda: data)
    cookie, csrf = _signed_session_with_csrf()
    _flask_app, runtime = _runtime(monkeypatch, admin=True)

    response = _run(
        runtime, '/api/admin/features/settings', cookie=cookie, method='PUT',
        headers={'X-CSRFToken': csrf}, json_body={key: True for key in fields},
    )

    assert response.status_code == 200
    assert all(response.json()['preferences'].values())
    assert len(calls) == 1


def test_lazy_asgi_dispatches_admin_scan_filter_create_natively(monkeypatch):
    calls = []
    row = SimpleNamespace(id=3, filter_pattern='dir:Fixture', case_sensitive='no')
    data = SimpleNamespace(
        list=lambda: [],
        add=lambda pattern, case_sensitive: calls.append((pattern, case_sensitive)) or row,
        delete=lambda _filter_id: False,
        rollback=lambda: None,
    )
    monkeypatch.setattr(native_admin_scan_filters, 'AdminScanFiltersData', lambda: data)
    cookie, csrf = _signed_session_with_csrf()
    _flask_app, runtime = _runtime(monkeypatch, admin=True)

    response = _run(
        runtime, '/api/admin/scan-filters', cookie=cookie, method='POST',
        headers={'X-CSRFToken': csrf}, json_body={'kind': 'dir', 'pattern': 'Fixture'},
    )

    assert response.status_code == 201
    assert response.json()['filter']['filter_pattern'] == 'dir:Fixture'
    assert calls == [('dir:Fixture', False)]


def test_lazy_asgi_dispatches_admin_plugin_catalog_natively(monkeypatch):
    data = SimpleNamespace(
        list=lambda category=None: [{'id': 'sample', 'category': category or 'tools'}],
        get=lambda plugin_id: {'id': plugin_id} if plugin_id == 'sample' else None,
    )
    monkeypatch.setattr(native_admin_plugins_read, 'AdminPluginsData', lambda: data)
    cookie, _csrf = _signed_session_with_csrf()
    _flask_app, runtime = _runtime(monkeypatch, admin=True)

    response = _run(runtime, '/api/plugins?category=tools', cookie=cookie)

    assert response.status_code == 200
    assert response.json() == {'plugins': [{'id': 'sample', 'category': 'tools'}]}


def test_lazy_asgi_dispatches_manual_identify_list_natively(monkeypatch):
    calls = []
    library = SimpleNamespace(uuid='lib-1', name='Fixture library', scan_depth=1)
    data = SimpleNamespace(
        library=lambda _app, uuid: library if uuid == 'lib-1' else None,
        resolve_scan_path=lambda _app, _folder, _root: ('/safe/scan', None),
        safe_path=lambda _app, path: (path == '/safe/scan', None),
        readable_directory=lambda _path: True,
        scan_mode=lambda _app, _path, _requested: 'folders',
        is_scan_busy=lambda: False,
        write_local_metadata_enabled=lambda: False,
        games_in_folder=lambda _app, _path, _library: [{'name': 'Fixture', 'full_path': '/safe/scan/Fixture'}],
        write_preview_session=lambda session, lib, games, _body: (
            calls.append(('session', lib.uuid, len(games))), session.update({'selected_library_uuid': lib.uuid}),
        ),
        rollback=lambda: calls.append(('rollback',)),
    )
    monkeypatch.setattr(native_manual_identify, 'ManualIdentifyListData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()

    response = _run(
        runtime, '/api/library_tools/manual_identify/list', cookie=cookie, method='POST',
        headers={'X-CSRFToken': csrf}, json_body={'library_uuid': 'lib-1', 'scan_mode': 'folders'},
    )

    assert response.status_code == 200
    assert response.json()['action'] == 'preview'
    assert response.json()['games'][0]['name'] == 'Fixture'
    assert calls == [('session', 'lib-1', 1)]


def test_lazy_asgi_dispatches_legacy_integration_post_aliases_natively(monkeypatch):
    from oneirodex.runtime_native import igdb_settings_read as native_igdb_settings

    calls = []
    integration_data = SimpleNamespace(
        oidc_read=lambda: {},
        oidc_save=lambda payload: calls.append(('oidc', payload)) or {'settings': {}},
        community_read=lambda: {},
        community_save=lambda url, label: calls.append(('community', url, label)) or {
            'community_chat_url': url, 'community_chat_label': label,
        },
    )
    igdb_data = SimpleNamespace(
        read=lambda: {},
        save=lambda payload: calls.append(('igdb-save', payload)) or {'settings': {}},
        test_connection=lambda: calls.append(('igdb-test',)) or {'settings': {}},
    )
    monkeypatch.setattr(native_integration_settings, 'IntegrationSettingsData', lambda: integration_data)
    monkeypatch.setattr(native_igdb_settings, 'IgdbSettingsData', lambda: igdb_data)
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()
    headers = {'X-CSRFToken': csrf}

    community = _run(
        runtime, '/admin/integrations/community', cookie=cookie, method='POST',
        headers=headers,
        json_body={'community_chat_url': 'https://community.example', 'community_chat_label': 'Chat'},
    )
    igdb_save = _run(
        runtime, '/admin/integrations/igdb/save', cookie=cookie, method='POST', headers=headers,
        json_body={'igdb_client_id': 'client-id', 'igdb_client_secret': 'secret'},
    )
    igdb_test = _run(
        runtime, '/admin/integrations/igdb/test', cookie=cookie, method='POST', headers=headers,
    )

    assert community.status_code == 200
    assert igdb_save.status_code == 200
    assert igdb_test.status_code == 200
    assert [call[0] for call in calls] == ['community', 'igdb-save', 'igdb-test']


def test_lazy_asgi_dispatches_legacy_server_settings_post_aliases(monkeypatch):
    from oneirodex.runtime_native import admin_server_settings as native_settings

    saved = []
    state = {'settings': {'showVersion': True}, 'bounds': {}, 'text_limits': {}}
    data = SimpleNamespace(
        state=lambda: state,
        save=lambda payload: (saved.append(payload) or state, None, None),
    )
    monkeypatch.setattr(native_settings, 'AdminServerSettingsData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()
    response = _run(
        runtime, '/admin/settings', cookie=cookie, method='POST',
        headers={'X-CSRFToken': csrf}, json_body={'showVersion': False},
    )

    assert response.status_code == 200
    assert saved == [{'showVersion': False}]

    empty = _run(
        runtime, '/admin/settings', cookie=cookie, method='POST',
        headers={'X-CSRFToken': csrf}, json_body={},
    )
    assert empty.status_code == 400
    assert empty.json()['message'] == 'No settings data provided'
    assert saved == [{'showVersion': False}]
    second_alias = _run(
        runtime, '/admin/new_server_settings', cookie=cookie, method='POST',
        headers={'X-CSRFToken': csrf}, json_body={},
    )
    assert second_alias.status_code == 400
    assert second_alias.json()['message'] == 'No settings data provided'
    assert saved == [{'showVersion': False}]


def test_lazy_asgi_dispatches_legacy_attract_mode_post_alias(monkeypatch):
    from oneirodex.runtime_native import admin_attract_mode as native_attract_mode

    calls = []
    body = {
        'enabled': True, 'idle_timeout': 90,
        'filters': {'genres': [], 'themes': []},
        'autoplay': {'enabled': False, 'skipFirst': 0, 'skipAfter': 20},
    }
    data = SimpleNamespace(
        save=lambda user, payload: calls.append((user.id, payload)) or payload,
        state=lambda settings: {'enabled': settings['enabled'], 'idle_timeout': settings['idle_timeout']},
    )
    monkeypatch.setattr(native_attract_mode, 'AdminAttractModeData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()
    response = _run(
        runtime, '/admin/attract_mode_settings', cookie=cookie, method='POST',
        headers={'X-CSRFToken': csrf}, json_body=body,
    )

    assert response.status_code == 200
    assert calls == [(7, {**body, 'filters': {'library_uuid': None, 'genres': [], 'themes': [], 'date_from': None, 'date_to': None}})]


def test_lazy_asgi_dispatches_legacy_scan_filter_add_form(monkeypatch):
    from oneirodex.runtime_native import admin_scan_filters as native_scan_filters

    calls = []
    data = SimpleNamespace(
        add=lambda pattern, case_sensitive: calls.append((pattern, case_sensitive)),
        rollback=lambda: None,
    )
    monkeypatch.setattr(native_scan_filters, 'AdminScanFiltersData', lambda: data)
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()
    response = _run(
        runtime, '/admin/edit_filters', cookie=cookie, method='POST',
        headers={'X-CSRFToken': csrf},
        form_body={'filter_pattern': 'Scene Release', 'case_sensitive': 'yes', 'csrf_token': csrf},
    )

    assert response.status_code == 302
    assert response.headers['location'] == '/admin/edit_filters'
    assert calls == [('Scene Release', True)]


def test_lazy_asgi_dispatches_legacy_manage_downloads_post_to_pilot(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    _flask_app.static_folder = str(asgi.Path(__file__).resolve().parents[1] / 'oneirodex' / 'static')
    cookie, csrf = _signed_session_with_csrf()
    response = _run(
        runtime, '/admin/manage-downloads', cookie=cookie, method='POST',
        headers={'X-CSRFToken': csrf}, form_body={'csrf_token': csrf},
    )

    assert response.status_code == 200
    assert 'id="admin-app-root"' in response.text


def test_lazy_asgi_dispatches_legacy_reference_set_delete_form(monkeypatch):
    from oneirodex.runtime_native import reference_sets_read as native_reference_sets

    deleted = []
    monkeypatch.setattr(
        native_reference_sets, 'ReferenceSetsData',
        lambda: SimpleNamespace(delete=lambda set_id: deleted.append(set_id) or True),
    )
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()
    response = _run(
        runtime, '/admin/reference_sets', cookie=cookie, method='POST',
        headers={'X-CSRFToken': csrf},
        form_body={'action': 'delete', 'set_id': '42', 'csrf_token': csrf},
    )

    assert response.status_code == 302
    assert response.headers['location'] == '/admin/reference_sets'
    assert deleted == [42]
    assert 'session=' in response.headers.get('set-cookie', '')


def test_native_reference_sets_head_matches_get_representation(monkeypatch):
    from oneirodex.runtime_native import reference_sets_read as native_reference_sets

    monkeypatch.setattr(
        native_reference_sets, 'ReferenceSetsData',
        lambda: SimpleNamespace(read_sets=lambda: {'sets': []}),
    )
    _flask_app, runtime = _runtime(monkeypatch)
    cookie = _signed_session()

    get = _run(runtime, '/api/reference-sets', cookie=cookie)
    head = _run(runtime, '/api/reference-sets', cookie=cookie, method='HEAD')

    assert get.status_code == 200
    assert get.content == b'{"sets":[]}\n'
    assert head.status_code == get.status_code
    assert head.content == b''
    assert head.headers['content-length'] == str(len(get.content))


def test_native_response_vary_keeps_existing_dimensions_and_adds_cookie():
    from asgi import _ensure_cookie_vary, _vary_cookie_required

    start = {
        'type': 'http.response.start', 'status': 200,
        'headers': [(b'content-type', b'application/json'), (b'vary', b'Accept-Encoding')],
    }
    result = _ensure_cookie_vary(start)
    vary = [value.decode() for key, value in result['headers'] if key == b'vary']

    assert vary == ['Accept-Encoding', 'Cookie']
    assert _ensure_cookie_vary(result) is result
    assert not _vary_cookie_required('/static/app.js')
    assert not _vary_cookie_required('/pulse')
    assert _vary_cookie_required('/api/account/summary')


def test_lazy_asgi_dispatches_legacy_chat_emoji_delete_form(monkeypatch):
    from oneirodex.runtime_native import chat_emoji_read as native_chat_emoji

    deleted = []
    monkeypatch.setattr(
        native_chat_emoji, 'ChatEmojiData',
        lambda: SimpleNamespace(delete=lambda slug, upload_folder=None: deleted.append(slug) or True),
    )
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()
    response = _run(
        runtime, '/admin/chat_emoji', cookie=cookie, method='POST',
        headers={'X-CSRFToken': csrf},
        form_body={'action': 'delete', 'slug': 'cheer', 'csrf_token': csrf},
    )

    assert response.status_code == 302
    assert response.headers['location'] == '/admin/chat_emoji'
    assert deleted == ['cheer']


def test_lazy_asgi_dispatches_legacy_library_create_and_edit_forms(monkeypatch):
    from oneirodex.runtime_native import library_admin_mutations as native_library_admin

    calls = []
    library = SimpleNamespace(uuid='library-1')
    fake = SimpleNamespace(
        create=lambda **values: calls.append(('create', values)),
        library=lambda value: library if value == 'library-1' else None,
        update=lambda row, **values: calls.append(('update', row.uuid, values)),
    )
    monkeypatch.setattr(native_library_admin, 'LibraryAdminMutationData', lambda: fake)
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()
    form = {'name': 'Test library', 'platform': 'PCWIN', 'scan_depth': '1',
            'watch_enabled': 'default', 'csrf_token': csrf}

    created = _run(
        runtime, '/admin/library/add', cookie=cookie, method='POST',
        headers={'X-CSRFToken': csrf}, form_body=form,
    )
    edited = _run(
        runtime, '/admin/library/edit/library-1', cookie=cookie, method='POST',
        headers={'X-CSRFToken': csrf},
        form_body={**form, 'name': 'Updated library'},
    )

    assert created.status_code == 302
    assert created.headers['location'] == '/libraries'
    assert edited.status_code == 302
    assert edited.headers['location'] == '/libraries'
    assert [call[0] for call in calls] == ['create', 'update']


def test_lazy_asgi_dispatches_legacy_link_existing_game_form(monkeypatch):
    from oneirodex.runtime_native import library_tools_mutations as native_tools

    calls = []
    fake = SimpleNamespace(
        allowed_bases=lambda _app: ['/safe'],
        safe_path=lambda _app, path: (path.startswith('/safe'), 'outside allowed roots'),
        directory_readable=lambda path: path == '/safe/Game',
        link_existing_game=lambda _app, game_uuid, path, actor, actor_id: (
            calls.append((game_uuid, path, actor, actor_id)) or {
                'game_uuid': game_uuid, 'game_name': 'Game', 'full_disk_path': path,
                'removed_from_unmatched': True,
            }, None,
        ),
    )
    monkeypatch.setattr(native_tools, 'LibraryToolsMutationData', lambda: fake)
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()
    response = _run(
        runtime, '/link_existing_game', cookie=cookie, method='POST',
        headers={'X-CSRFToken': csrf},
        form_body={'game_uuid': 'game-1', 'full_disk_path': '/safe/Game',
                   'library_uuid': 'library-1', 'from_unmatched': 'true',
                   'csrf_token': csrf},
    )

    assert response.status_code == 302
    assert response.headers['location'] == '/admin/scan_management?active_tab=unmatched'
    assert calls == [('game-1', '/safe/Game', 'administrator', 7)]


def test_lazy_asgi_local_game_image_uses_vetted_descriptor_and_ranges(monkeypatch, tmp_path):
    _flask_app, runtime = _runtime(monkeypatch)
    image = tmp_path / 'cover.jpg'
    image.write_bytes(b'0123456789')
    data = runtime._fake_game_reads
    safe_state = {'value': True}
    monkeypatch.setattr(data, 'game', lambda uid: SimpleNamespace(uuid=uid, full_disk_path='/safe/game'))
    monkeypatch.setattr(data, 'allowed_bases', lambda _app: ['/safe'], raising=False)
    monkeypatch.setattr(data, 'safe_path', lambda _path, _bases: (safe_state['value'], None), raising=False)
    monkeypatch.setattr(data, 'local_image_path', lambda root, kind, index: str(image), raising=False)
    monkeypatch.setattr(data, 'open_local_image', lambda _root, path: open(path, 'rb'), raising=False)
    cookie = _signed_session()
    path = '/game/39c5ac18-1f18-4bf8-9c05-e6b268f24d40/local_image/cover'

    complete = _run(runtime, path, cookie=cookie)
    ranged = _run(runtime, path, cookie=cookie, headers={'Range': 'bytes=2-5'})
    unchanged = _run(
        runtime, path, cookie=cookie,
        headers={'If-None-Match': complete.headers['etag']},
    )
    invalid_range = _run(runtime, path, cookie=cookie, headers={'Range': 'bytes=99-'})
    safe_state['value'] = False
    unsafe = _run(runtime, path, cookie=cookie)
    safe_state['value'] = True
    data.allowed = False
    denied = _run(runtime, path, cookie=cookie)

    assert complete.status_code == 200
    assert complete.content == b'0123456789'
    assert complete.headers['content-length'] == '10'
    assert ranged.status_code == 206
    assert ranged.content == b'2345'
    assert ranged.headers['content-range'] == 'bytes 2-5/10'
    assert unchanged.status_code == 304
    assert invalid_range.status_code == 416
    assert invalid_range.headers['content-range'] == 'bytes */10'
    assert unsafe.status_code == 403
    assert denied.status_code == 403


def test_lazy_asgi_dispatches_legacy_image_refresh_for_admin(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    data = runtime._fake_batch_refresh
    monkeypatch.setattr(
        data, 'game', lambda game_uuid: SimpleNamespace(name='Fixture game'), raising=False,
    )
    cookie, csrf = _signed_session_with_csrf()
    denied = _run(
        runtime, '/refresh_game_images/game-1', cookie=cookie, method='POST',
    )
    assert denied.status_code == 400
    assert denied.headers['content-type'] == 'text/html; charset=utf-8'
    assert b'<p>The CSRF token is missing.</p>' in denied.content
    assert not any(call[0] == 'enqueue' for call in data.calls)

    response = _run(
        runtime, '/refresh_game_images/game-1', cookie=cookie, method='POST',
        headers={'X-CSRFToken': csrf},
    )
    ajax = _run(
        runtime, '/refresh_game_images/game-1', cookie=cookie, method='POST',
        headers={'X-CSRFToken': csrf, 'X-Requested-With': 'XMLHttpRequest'},
    )

    assert response.status_code == 302, response.text
    assert response.headers['location'] == '/libraries'
    assert ajax.status_code == 200
    assert ajax.json()['message'] == 'Game images refresh process started for Fixture game.'
    assert data.calls.count(('enqueue', 'game-1')) == 2


def test_lazy_asgi_dispatches_legacy_single_game_image_upload(monkeypatch):
    from oneirodex.runtime_native import admin_image_mutations as native_images
    monkeypatch.setattr('oneirodex.utils.scanning.is_scan_job_running', lambda: False)

    calls = []
    monkeypatch.setattr(
        native_images, 'ImageMutationsData',
        lambda: SimpleNamespace(
            upload_single=lambda app, game_uuid, filename, image_type, content: (
                calls.append((game_uuid, filename, image_type, content)) or {
                    'message': 'File uploaded successfully',
                    'url': '/static/library/images/fixture.jpg',
                    'flash': 'Image uploaded successfully!', 'image_id': 11,
                    'image_type': image_type, 'kind': image_type,
                }
            ),
            rollback=lambda: None,
        ),
    )
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()

    async def send(with_csrf):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='http://testserver',
        ) as client:
            client.cookies.set('session', cookie)
            headers = {'X-CSRFToken': csrf} if with_csrf else {}
            return await client.post(
                '/upload_image/game-1', data={'image_type': 'cover'},
                files={'file': ('cover.jpg', b'fixture-image', 'image/jpeg')},
                headers=headers,
            )

    rejected = asyncio.run(send(False))
    accepted = asyncio.run(send(True))

    assert rejected.status_code == 400
    assert accepted.status_code == 200
    assert accepted.json()['image_id'] == 11
    assert calls == [('game-1', 'cover.jpg', 'cover', b'fixture-image')]


def test_lazy_asgi_dispatches_legacy_manual_scan_folder_form(monkeypatch):
    from oneirodex.runtime_native import legacy_scan_forms as native_scan_forms

    calls = []
    fake = SimpleNamespace(
        resolve_path=lambda _app, folder_path, library_root: ('/safe/ROMs', None),
        allowed_bases=lambda _app: ['/safe'],
        safe_path=lambda path, _bases: (calls.append(('safe', path)) or True, None),
        readable_directory=lambda path: path == '/safe/ROMs',
        scan_patterns=lambda: (['ignored'], ['CaseSensitive']),
        list_games=lambda path, insensitive, sensitive: (
            calls.append(('list', path, insensitive, sensitive)) or
            [{'name': 'Example Game', 'full_path': '/safe/ROMs/Example Game'}]
        ),
    )
    monkeypatch.setattr(native_scan_forms, 'LegacyScanFormData', lambda: fake)
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()
    response = _run(
        runtime, '/scan_manual_folder', cookie=cookie, method='POST',
        headers={'X-CSRFToken': csrf},
        form_body={'csrf_token': csrf, 'folder_path': '/safe/ROMs',
                   'library_uuid': 'library-1'},
    )

    assert response.status_code == 302
    assert response.headers['location'] == '/admin/scan_management?active_tab=manualScan'
    assert calls == [
        ('safe', '/safe/ROMs'),
        ('list', '/safe/ROMs', ['ignored'], ['CaseSensitive']),
    ]


def test_lazy_asgi_dispatches_legacy_scan_management_filter_form(monkeypatch):
    from oneirodex.runtime_native import legacy_scan_management as native_scan_management

    added = []
    fake = SimpleNamespace(
        add_filter=lambda pattern, case_sensitive: added.append((pattern, case_sensitive)),
    )
    monkeypatch.setattr(
        native_scan_management, 'LegacyScanManagementData', lambda: fake,
    )
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()
    response = _run(
        runtime, '/scan_management', cookie=cookie, method='POST',
        headers={'X-CSRFToken': csrf},
        form_body={'submit': 'AddReleaseGroup', 'filter_pattern': ' Scene ',
                   'case_sensitive': 'yes', 'csrf_token': csrf},
    )

    assert response.status_code == 302
    assert response.headers['location'] == '/scan_management?active_tab=scan_filters'
    assert added == [('Scene', True)]


def test_lazy_asgi_dispatches_legacy_manual_identify_form(monkeypatch):
    from oneirodex.runtime_native import legacy_manual_identify_forms as native_manual_forms

    saved = []
    fake = SimpleNamespace(
        create=lambda app, body, actor, *, from_unmatched: (
            saved.append((body.name, body.igdb_id, from_unmatched)) or
            {'game_uuid': 'game-new', 'redirect_url': '/libraries'}
        ),
    )
    monkeypatch.setattr(native_manual_forms, 'ManualIdentifyMutationData', lambda: fake)
    _flask_app, runtime = _runtime(monkeypatch, admin=True)
    cookie, csrf = _signed_session_with_csrf()
    response = _run(
        runtime, '/add_game_manual?from_unmatched=true', cookie=cookie, method='POST',
        headers={'X-CSRFToken': csrf},
        form_body={'igdb_id': '101', 'name': 'Game', 'full_disk_path': '/safe/Game',
                   'library_uuid': 'lib-1', 'csrf_token': csrf},
    )

    assert response.status_code == 303
    assert response.headers['location'] == '/scan_management?active_tab=unmatched'
    assert saved == [('Game', 101, True)]


def test_lazy_asgi_dispatches_native_oidc_start_and_callback(monkeypatch):
    from oneirodex.runtime_native import oidc_auth as native_oidc_auth
    from oneirodex.runtime_native.session_compat import load_session_cookie
    from oneirodex.utils import oidc

    monkeypatch.setenv('OIDC_ENABLED', 'true')
    monkeypatch.setattr(oidc, 'AUTHLIB_AVAILABLE', True)

    async def async_value(value):
        return value

    fake_client = SimpleNamespace(
        create_authorization_url=lambda **kwargs: async_value({
            'url': 'https://idp.example/authorize?state=' + kwargs['state'],
        }),
        fetch_access_token=lambda **kwargs: async_value({'id_token': 'id-token'}),
        parse_id_token=lambda token, *, nonce: async_value({
            'sub': 'oidc-user', 'email': 'oidc@example.test', 'email_verified': True,
        }),
    )
    user = SimpleNamespace(name='OIDC User', get_id=lambda: '7:fp')
    fake_data = SimpleNamespace(
        settings=lambda: SimpleNamespace(
            oidc_enabled=True, oidc_issuer_url='https://idp.example',
            oidc_client_id='client', oidc_client_secret='secret',
            oidc_redirect_uri='https://app.example/login/oidc/callback',
            oidc_scopes='openid email profile', oidc_role_claim='groups',
            oidc_role_map=None, oidc_display_name='SSO',
        ),
        provision=lambda claims, config, app: user,
        rollback=lambda: None,
        log_login=lambda actor: None,
    )
    monkeypatch.setattr(native_oidc_auth, 'OidcAuthData', lambda: fake_data)
    monkeypatch.setattr(native_oidc_auth, '_make_oidc_client', lambda _config: fake_client)
    _flask_app, runtime = _runtime(monkeypatch)
    anonymous = dump_session_cookie({}, 'native-asgi-browse-secret')

    async def flow():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=runtime), base_url='https://app.example',
        ) as client:
            client.cookies.set('session', anonymous)
            start = await client.get('/login/oidc')
            assert start.status_code == 302
            session = load_session_cookie(
                start.cookies.get('session'), 'native-asgi-browse-secret', max_age=31_536_000,
            )
            callback = await client.get(
                '/login/oidc/callback?code=code&state=' + session['oidc_auth_state'],
            )
            return start, callback

    start, callback = asyncio.run(flow())
    assert start.headers['location'].startswith('https://idp.example/authorize?state=')
    assert callback.status_code == 302
    assert callback.headers['location'] == '/discover'
    assert 'remember_token=' in callback.headers.get('set-cookie', '')


def test_lazy_asgi_uses_native_404_without_wsgi_fallback(monkeypatch):
    _flask_app, runtime = _runtime(monkeypatch)
    response = _run(runtime, '/route-that-does-not-exist')
    assert response.status_code == 404
    assert response.json()['error_code'] == 'not_found'
    assert response.json()['message'] == 'Not found'
