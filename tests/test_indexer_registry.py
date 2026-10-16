"""Native Torznab/Newznab indexer registry + merged search (Track A / plan 1B)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from flask_login import login_user
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import GlobalSettings, User
from oneirodex.utils import arr_connectors
from oneirodex.utils.arr_connectors import search_indexers
from oneirodex.utils.indexer_registry import (
    add_indexer,
    bulk_import_indexers,
    enable_presets,
    list_indexers,
    load_indexer_presets,
    presets_path,
)


TORZNAB_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <item>
      <title>Stub Game Release</title>
      <guid>https://cdn.example.com/dl/stub.torrent</guid>
      <link>https://cdn.example.com/dl/stub.torrent</link>
      <comments>https://tracker.example.com/details/1</comments>
      <size>1048576</size>
      <enclosure url="https://cdn.example.com/dl/stub.torrent" length="1048576" type="application/x-bittorrent"/>
      <torznab:attr name="seeders" value="7"/>
    </item>
  </channel>
</rss>
"""


class _FakeResp:
    def __init__(self, text: str = '', status_code: int = 200, headers: dict | None = None):
        self.text = text
        self.content = text.encode('utf-8')
        self.status_code = status_code
        self.headers = headers or {'Content-Type': 'application/rss+xml'}

    def json(self):
        import json
        return json.loads(self.text)


@pytest.fixture
def admin(db_session):
    uid = str(uuid4())
    row = User(
        name=f'adm_{uid[:8]}',
        email=f'adm_{uid[:8]}@example.com',
        role='admin',
        user_id=uid,
        state=True,
    )
    row.set_password('password123')
    db_session.add(row)
    db_session.commit()
    return row


def _login(client, app, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.get_id())
        sess['_fresh'] = True
    with app.test_request_context():
        login_user(user)


def _ensure_arr_settings(db_session, **extra):
    # Ordered by id, like the product's settings reads. A bare `limit(1)` has no
    # defined order in Postgres, so with more than one GlobalSettings row around
    # these helpers could write the indexer list to one row while the code under
    # test read another — which is how indexers from an earlier test reappeared
    # in a later test's assertions despite the wipe below.
    settings = db_session.execute(
        select(GlobalSettings).order_by(GlobalSettings.id).limit(1)
    ).scalars().first()
    if not settings:
        settings = GlobalSettings()
        db_session.add(settings)
    cfg = dict(getattr(settings, 'arr_settings', None) or {})
    # Default: wipe hub URLs so tests do not inherit prior Prowlarr/Jackett keys.
    for key in (
        'prowlarr_url', 'prowlarr_api_key',
        'jackett_url', 'jackett_api_key',
    ):
        if key not in extra:
            cfg[key] = ''
    cfg.update(extra)
    settings.arr_settings = cfg
    settings.enable_arr_module = True
    db_session.commit()
    return settings


def test_stub_torznab_search_returns_hit(app, db_session, monkeypatch):
    _ensure_arr_settings(db_session, indexers=[])
    with app.app_context():
        add_indexer({
            'name': 'StubTorznab',
            'protocol': 'torznab',
            'url': 'https://indexer.example.com/torznab',
            'api_key': 'test-key',
            'enabled': True,
        })

        def fake_fetch(method, url, **kwargs):
            assert method.lower() == 'get'
            assert 't' in (kwargs.get('params') or {})
            return _FakeResp(TORZNAB_XML)

        monkeypatch.setattr(arr_connectors, 'fetch_with_challenge_retry', fake_fetch)
        hits = search_indexers('Stub', limit=10)
    assert len(hits) == 1
    assert hits[0].title == 'Stub Game Release'
    assert hits[0].indexer == 'StubTorznab'
    assert hits[0].seeders == 7
    assert 'stub.torrent' in (hits[0].download_url or '')


def test_bulk_import_json_and_csv(app, db_session):
    _ensure_arr_settings(db_session, indexers=[])
    with app.app_context():
        created = bulk_import_indexers([
            {
                'name': 'Bulk A',
                'protocol': 'torznab',
                'url': 'https://a.example.com/api',
                'api_key': 'k1',
            },
            {
                'name': 'Bulk B',
                'protocol': 'newznab',
                'url': 'https://b.example.com/api',
                'api_key': '',
            },
        ])
        assert len(created) == 2
        csv_created = bulk_import_indexers(
            'name,protocol,url,api_key\n'
            'CSV C,torznab,https://c.example.com/api,k3\n',
        )
        assert len(csv_created) == 1
        names = {row['name'] for row in list_indexers()}
    assert names == {'Bulk A', 'Bulk B', 'CSV C'}


def test_merge_prowlarr_and_native(app, db_session, monkeypatch):
    _ensure_arr_settings(
        db_session,
        indexers=[],
        prowlarr_url='https://prowlarr.example.com',
        prowlarr_api_key='p-key',
    )
    with app.app_context():
        add_indexer({
            'name': 'NativeOne',
            'protocol': 'torznab',
            'url': 'https://native.example.com/api',
            'api_key': 'n-key',
            'enabled': True,
        })

        def fake_fetch(method, url, **kwargs):
            if 'prowlarr' in url:
                return _FakeResp(
                    '[{"title":"From Prowlarr","downloadUrl":"https://dl.example.com/p","indexer":"P","size":1,"seeders":1,"protocol":"torrent"}]',
                    headers={'Content-Type': 'application/json'},
                )
            return _FakeResp(TORZNAB_XML)

        monkeypatch.setattr(arr_connectors, 'fetch_with_challenge_retry', fake_fetch)
        hits = search_indexers('Game', limit=25)
    titles = {h.title for h in hits}
    assert 'Stub Game Release' in titles
    assert 'From Prowlarr' in titles


def test_native_indexer_ssrf_reject(app, db_session, monkeypatch):
    monkeypatch.setitem(app.config, 'ALLOW_PRIVATE_LAN_URLS', True)
    _ensure_arr_settings(db_session, indexers=[])
    with app.app_context():
        with pytest.raises(ValueError, match='not allowed|host|URL'):
            add_indexer({
                'name': 'LAN bad',
                'protocol': 'torznab',
                'url': 'http://192.168.1.50:9117/api',
                'api_key': 'k',
            })
        with pytest.raises(ValueError, match='not allowed|host|URL'):
            add_indexer({
                'name': 'Meta bad',
                'protocol': 'torznab',
                'url': 'http://169.254.169.254/latest',
                'api_key': 'k',
            })


def test_enable_presets_copies_without_mutating_pack(app, db_session):
    pack_path = presets_path()
    before = pack_path.read_text(encoding='utf-8')
    presets = load_indexer_presets()
    assert len(presets) >= 2
    ids = [presets[0]['id'], presets[1]['id']]
    _ensure_arr_settings(db_session, indexers=[])
    with app.app_context():
        created = enable_presets(ids)
        assert len(created) == 2
        for row in created:
            assert row['source'] == 'preset'
            assert row['api_key'] == ''
            assert row['preset_id'] in ids
            assert row['enabled'] is True
        # Incomplete keys are not ready for search
        ready_titles = search_indexers('anything', limit=5)
        assert ready_titles == []
        listed = list_indexers()
        assert len(listed) == 2
    after = pack_path.read_text(encoding='utf-8')
    assert after == before


def test_arr_indexers_api_add_and_list(client, app, admin, db_session):
    _login(client, app, admin)
    app.config['ENABLE_ARR_MODULE'] = True
    _ensure_arr_settings(db_session, indexers=[])
    resp = client.post('/api/arr/indexers', json={
        'name': 'API Torznab',
        'protocol': 'torznab',
        'url': 'https://api-idx.example.com/torznab',
        'api_key': 'secret',
    })
    assert resp.status_code == 201
    body = resp.get_json()
    assert body['indexer']['api_key_set'] is True
    assert 'api_key' not in body['indexer']
    listed = client.get('/api/arr/indexers')
    assert listed.status_code == 200
    data = listed.get_json()
    assert len(data['indexers']) >= 1
    assert isinstance(data['presets'], list)
    assert len(data['presets']) >= 1


def test_arr_config_response_reports_secret_presence_without_returning_secrets(client, app, admin, db_session):
    _login(client, app, admin)
    app.config['ENABLE_ARR_MODULE'] = True
    _ensure_arr_settings(
        db_session,
        prowlarr_url='https://example.com', prowlarr_api_key='never-return-this',
        qbittorrent_url='http://qbit.local:8080', qbittorrent_password='also-private',
    )
    response = client.get('/api/arr/config')
    assert response.status_code == 200
    body = response.get_json()
    assert body['prowlarr_api_key_set'] is True
    assert body['qbittorrent_password_set'] is True
    assert 'prowlarr_api_key' not in body
    assert 'qbittorrent_password' not in body

    saved = client.put('/api/arr/config', json={'prowlarr_url': 'https://example.com'})
    assert saved.status_code == 200
    body = saved.get_json()['config']
    assert body['prowlarr_api_key_set'] is True
    assert body['qbittorrent_password_set'] is True
    assert 'never-return-this' not in saved.get_data(as_text=True)
    assert 'also-private' not in saved.get_data(as_text=True)


def test_search_skips_incomplete_native(app, db_session, monkeypatch):
    _ensure_arr_settings(db_session, indexers=[])
    calls = {'n': 0}

    def fake_fetch(method, url, **kwargs):
        calls['n'] += 1
        return _FakeResp(TORZNAB_XML)

    with app.app_context():
        add_indexer({
            'name': 'NoKey',
            'protocol': 'torznab',
            'url': 'https://nokey.example.com/api',
            'api_key': '',
            'enabled': True,
        })
        monkeypatch.setattr(arr_connectors, 'fetch_with_challenge_retry', fake_fetch)
        hits = search_indexers('x', limit=5)
    assert hits == []
    assert calls['n'] == 0


def test_acquire_status_readiness_and_search_warnings(client, app, admin, db_session, monkeypatch):
    _login(client, app, admin)
    app.config['ENABLE_ARR_MODULE'] = True
    _ensure_arr_settings(db_session, indexers=[])
    with app.app_context():
        add_indexer({
            'name': 'NeedsKey',
            'protocol': 'torznab',
            'url': 'https://needskey.example.com/api',
            'api_key': '',
            'enabled': True,
        })
        add_indexer({
            'name': 'ReadyOne',
            'protocol': 'torznab',
            'url': 'https://ready.example.com/api',
            'api_key': 'rk',
            'enabled': True,
        })

    status = client.get('/api/acquire/status')
    assert status.status_code == 200
    body = status.get_json()
    assert body['native_ready'] is True
    assert body['hubs_ready'] is False
    assert body['indexers_ready'] is True
    assert body['native_ready_count'] == 1
    assert any('NeedsKey' in w for w in body['indexer_warnings'])

    monkeypatch.setattr(
        arr_connectors,
        'fetch_with_challenge_retry',
        lambda *a, **k: _FakeResp(TORZNAB_XML),
    )
    search = client.get('/api/acquire/search?q=Stub')
    assert search.status_code == 200
    sbody = search.get_json()
    assert 'warnings' in sbody
    assert any('NeedsKey' in w for w in sbody['warnings'])
    assert isinstance(sbody['results'], list)
