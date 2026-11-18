"""Licensed catalog — extra DAT regions + IGDB release_dates cache."""

from __future__ import annotations

from uuid import uuid4

import pytest

from flask_login import login_user
from sqlalchemy import delete, select

from oneirodex.models import Game, IgdbPlatformRelease, Library, User
from oneirodex.platform import LibraryPlatform
from oneirodex.utils.licensed_catalog import (
    DAT_ONLY_REGIONS,
    igdb_region_to_code,
    licensed_catalog_report,
    parse_release_date_rows,
    refresh_platform_catalog,
    upsert_releases_from_igdb_payload,
)
from oneirodex.utils.set_completion import (
    REGION_PREF_ORDER,
    VALID_REGIONS,
    normalize_region,
)


def _login(client, app, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.get_id())
        sess['_fresh'] = True
    with app.test_request_context():
        login_user(user)


def test_region_pref_covers_valid_set():
    assert set(REGION_PREF_ORDER) == VALID_REGIONS
    assert DAT_ONLY_REGIONS <= VALID_REGIONS
    assert 'FRA' in VALID_REGIONS
    assert 'BRA' in VALID_REGIONS


def test_normalize_region_extra_skus_stay_distinct():
    assert normalize_region('Brazil') == 'BRA'
    assert normalize_region('BR') == 'BRA'
    assert normalize_region('Korea') == 'KOR'
    assert normalize_region('FR') == 'FRA'
    assert normalize_region('France') == 'FRA'
    assert normalize_region('Germany') == 'DEU'
    assert normalize_region('Australia') == 'AUS'
    assert normalize_region('Spain') == 'ESP'
    assert normalize_region('China') == 'CHN'
    assert normalize_region('UK') == 'GBR'
    assert normalize_region('PAL') == 'EUR'
    assert normalize_region('France') != 'EUR'
    assert normalize_region('mystery') == 'OTHER'


def test_igdb_region_map_does_not_invent_france():
    assert igdb_region_to_code(1) == 'EUR'
    assert igdb_region_to_code(2) == 'USA'
    assert igdb_region_to_code(5) == 'JPN'
    assert igdb_region_to_code(9) == 'KOR'
    assert igdb_region_to_code(10) == 'BRA'
    assert igdb_region_to_code(4) == 'OTHER'
    assert igdb_region_to_code(7) == 'OTHER'
    assert igdb_region_to_code(99) is None


def test_parse_skips_other_platforms_and_unknown_regions():
    rows = parse_release_date_rows(
        {
            'id': 42,
            'name': 'Metroid',
            'release_dates': [
                {'date': 100, 'region': 2, 'platform': 18},
                {'date': 200, 'region': 2, 'platform': 19},
                {'date': 300, 'region': 99, 'platform': 18},
                {'date': 50, 'region': 5, 'platform': {'id': 18}},
            ],
        },
        igdb_platform_id=18,
    )
    by_code = {row['region_code']: row for row in rows}
    assert set(by_code) == {'USA', 'JPN'}


def test_refresh_and_report(app, client, db_session):
    uid = str(uuid4())
    admin = User(
        name=f'cat_admin_{uid[:8]}',
        email=f'cat_admin_{uid[:8]}@example.com',
        role='admin',
        user_id=uid,
        state=True,
    )
    admin.set_password('password123')
    member_uid = str(uuid4())
    member = User(
        name=f'cat_user_{member_uid[:8]}',
        email=f'cat_user_{member_uid[:8]}@example.com',
        role='user',
        user_id=member_uid,
        state=True,
    )
    member.set_password('password123')
    library = Library(name=f'NES_{uuid4().hex[:6]}', platform=LibraryPlatform.NES)
    db_session.add_all([admin, member, library])
    db_session.commit()

    igdb_id = 8_100_000 + (uuid4().int % 90_000)
    db_session.add(
        Game(
            uuid=str(uuid4()),
            name='Metroid',
            library_uuid=library.uuid,
            igdb_id=igdb_id,
        )
    )
    db_session.commit()

    payload = [
        {
            'id': igdb_id,
            'name': 'Metroid',
            'release_dates': [
                {'date': 500_000_000, 'region': 2, 'platform': 18},
                {'date': 500_000_100, 'region': 5, 'platform': 18},
            ],
        },
        {
            'id': igdb_id + 1,
            'name': 'Kid Icarus',
            'release_dates': [
                {'date': 500_000_200, 'region': 2, 'platform': 18},
            ],
        },
    ]

    def fake_request(_endpoint, query):
        assert 'category = (0)' in query
        assert 'platforms = (18)' in query
        assert 'release_dates.region' in query
        return payload

    result = refresh_platform_catalog('NES', delay_s=0, request_fn=fake_request)
    assert result['unique_titles'] == 2
    assert result['pages'] == 1
    assert result['cached_rows'] == 3

    report = licensed_catalog_report('NES', member)
    assert report['empty'] is False
    assert report['unique_titles'] == 2
    assert report['owned_titles'] == 1
    by_code = {row['region_code']: row for row in report['by_region']}
    assert by_code['USA']['titles'] == 2
    assert by_code['USA']['owned'] == 1
    assert by_code['JPN']['titles'] == 1
    assert by_code['JPN']['owned'] == 1
    assert by_code['FRA']['source'] == 'dat_only'
    assert by_code['FRA']['titles'] == 0

    with client:
        _login(client, app, member)
        empty_meta = client.get('/api/licensed-catalog')
        assert empty_meta.status_code == 200
        meta = empty_meta.get_json()
        assert meta['ok'] is True
        assert 'BRA' in meta['regions']

        body = client.get('/api/licensed-catalog?library_platform=NES')
        assert body.status_code == 200
        data = body.get_json()
        assert data['ok'] is True
        assert data['unique_titles'] == 2
        assert data['error'] is None

        refused = client.get('/api/licensed-catalog?library_platform=PCWIN')
        assert refused.status_code == 400
        assert refused.get_json()['ok'] is False

        refresh = client.post(
            '/api/licensed-catalog/refresh',
            json={'library_platform': 'NES'},
        )
        assert refresh.status_code in (302, 401, 403)

    with client:
        _login(client, app, admin)
        pc = client.post(
            '/api/licensed-catalog/refresh',
            json={'library_platform': 'PCWIN'},
        )
        assert pc.status_code == 400
        assert 'Windows' in pc.get_json()['error']


def test_empty_cache_is_honest(app, db_session):
    uid = str(uuid4())
    member = User(
        name=f'cat_empty_{uid[:8]}',
        email=f'cat_empty_{uid[:8]}@example.com',
        role='user',
        user_id=uid,
        state=True,
    )
    member.set_password('password123')
    db_session.add(member)
    db_session.commit()
    db_session.execute(
        delete(IgdbPlatformRelease).where(IgdbPlatformRelease.library_platform == 'POKE_MINI')
    )
    db_session.commit()
    with app.app_context():
        report = licensed_catalog_report('POKE_MINI', member)
        assert report['empty'] is True
        assert report['unique_titles'] == 0
        assert 'not fetched' in report['note'].lower() or 'empty' in report['note'].lower()


def test_identify_upsert_writes_cache(app, db_session):
    igdb_id = 8_200_000 + (uuid4().int % 90_000)
    with app.app_context():
        written = upsert_releases_from_igdb_payload(
            'NES',
            {
                'id': igdb_id,
                'name': 'Balloon Fight',
                'release_dates': [
                    {'date': 400_000_000, 'region': 2, 'platform': 18},
                ],
            },
        )
        db_session.commit()
        assert written == 1
        row = db_session.execute(
            select(IgdbPlatformRelease).filter_by(igdb_game_id=igdb_id, region_code='USA')
        ).scalars().first()
        assert row is not None
        assert row.name == 'Balloon Fight'
        skipped = upsert_releases_from_igdb_payload(
            'PCWIN',
            {
                'id': igdb_id + 2,
                'name': 'Doom',
                'release_dates': [{'date': 1, 'region': 2, 'platform': 6}],
            },
        )
        assert skipped == 0


def test_gbc_refresh_filters_igdb_platform_22(app):
    def fake_request(_endpoint, query):
        assert 'platforms = (22)' in query
        return []

    with app.app_context():
        result = refresh_platform_catalog('GBC', delay_s=0, request_fn=fake_request)
        assert result['unique_titles'] == 0


def test_gx4000_is_catalog_eligible_and_unmapped_is_refused(app):
    def fake_request(_endpoint, query):
        assert 'platforms = (506)' in query
        return []

    with app.app_context():
        refresh_platform_catalog('GX4000', delay_s=0, request_fn=fake_request)
        with pytest.raises(ValueError, match='No IGDB'):
            refresh_platform_catalog('CREATIVISION', delay_s=0, request_fn=fake_request)
        with pytest.raises(ValueError, match='Windows'):
            refresh_platform_catalog('MAC', delay_s=0, request_fn=fake_request)
