"""W28 — the member-facing update sweep, and the Latest Games / New Library split.

Two reported gaps, both about a surface that could only *read* state nobody
could produce:

* The Updates inbox lists titles a previous freshness probe found behind. The
  only ways to make a probe happen were per-title, the library multi-select, and
  an admin-only bulk refresh — so a member whose library had never been probed
  saw an empty inbox and no way to fill it. ``POST /api/updates/scan`` is the
  member's own sweep.
* "Latest Games" ordered by ``date_created`` — when a scan first wrote the row —
  so it answered "what did I import most recently" under a heading that promises
  new releases. It orders by release date now, and the question it used to
  answer has its own shelf.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import DiscoverySection, Game, Library, User
from oneirodex.platform import LibraryPlatform


@pytest.fixture
def scan_user(db_session):
    user = User(
        name=f'sweeper_{uuid4().hex[:8]}',
        email=f'sweeper_{uuid4().hex[:8]}@example.com',
        password_hash='hashed_password',
        role='user',
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def scan_library(db_session):
    library = Library(
        name=f'Sweep Library {uuid4().hex[:6]}',
        platform=LibraryPlatform.PCWIN,
    )
    db_session.add(library)
    db_session.commit()
    return library


def _game(db_session, library, name, *, created, released=None, checked=None):
    game = Game(
        name=name,
        library_uuid=library.uuid,
        date_created=created,
        first_release_date=released,
        freshness_checked_at=checked,
    )
    db_session.add(game)
    db_session.commit()
    return game


def _body(result):
    """Read the JSON out of a route's return value.

    Every route in this codebase answers through ``api_ok`` / ``api_error``,
    and both end in ``return jsonify(body), status`` — so calling a view
    function directly yields a ``(Response, int)`` tuple, not a Response.
    Unwrap here rather than at each call site.
    """
    response = result[0] if isinstance(result, tuple) else result
    return response.get_json()


class TestUpdatesScanRoute:
    def test_requires_login(self, client):
        response = client.post('/api/updates/scan', json={})
        assert response.status_code in (302, 401)

    def test_sweeps_unprobed_titles_oldest_first_and_reports_what_is_left(
        self, app, db_session, scan_user, scan_library, monkeypatch
    ):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        # Three never probed, one probed an hour ago. `only_stale` defaults on,
        # so the recent one is not due and must not be counted or touched.
        for i in range(3):
            _game(db_session, scan_library, f'Unprobed {i}', created=now)
        recent = _game(
            db_session,
            scan_library,
            'Just probed',
            created=now,
            checked=now - timedelta(hours=1),
        )

        probed = []

        def fake_check(game, *, commit=False, db_session=None):
            probed.append(game.name)
            return {'status': 'behind'}

        monkeypatch.setattr(
            'oneirodex.utils.freshness.check_and_store_freshness', fake_check
        )

        # Scoped to this run's library. `scan_library` is function-scoped with a
        # fresh uuid, so this pins the sweep to the four games above — without
        # it the batch is every due game in `oneirodextest`, which nothing ever
        # cleans up, and `remaining` counts years of other test files' fixtures.
        with app.test_request_context(
            '/api/updates/scan',
            json={'limit': 2, 'library_uuid': scan_library.uuid},
        ):
            from flask_login import login_user

            login_user(scan_user)
            from oneirodex.routes_apis.updates import updates_scan

            body = _body(updates_scan())
        assert body['ok'] is True
        assert body['checked'] == 2
        assert body['behind_count'] == 2
        # Three were due; two were done, so one is left. The page turns this
        # into "press again to continue" rather than implying one press swept
        # the whole library.
        assert body['remaining'] == 1
        assert recent.name not in probed

    def test_a_failing_title_does_not_end_the_sweep(
        self, app, db_session, scan_user, scan_library, monkeypatch, caplog
    ):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        _game(db_session, scan_library, 'Aaa breaks', created=now)
        _game(db_session, scan_library, 'Bbb works', created=now)

        def fake_check(game, *, commit=False, db_session=None):
            if 'breaks' in game.name:
                raise RuntimeError('store timed out')
            return {'status': 'current'}

        monkeypatch.setattr(
            'oneirodex.utils.freshness.check_and_store_freshness', fake_check
        )

        # Scoped for the same reason as above: an unscoped sweep checks every
        # due game in the shared test database, not the two created here.
        with app.test_request_context(
            '/api/updates/scan', json={'library_uuid': scan_library.uuid}
        ):
            from flask_login import login_user

            login_user(scan_user)
            from oneirodex.routes_apis.updates import updates_scan

            response = updates_scan()

        body = _body(response)
        # One error, one success — a single unreachable store must not cost the
        # member the rest of the batch.
        assert body['checked'] == 1
        assert len(body['errors']) == 1
        assert body['errors'][0]['error'] == 'Could not check this title'
        assert 'store timed out' not in body['errors'][0]['error']
        assert any('store timed out' in record.message for record in caplog.records)

    def test_limit_is_clamped(self, app, db_session, scan_user, scan_library, monkeypatch):
        monkeypatch.setattr(
            'oneirodex.utils.freshness.check_and_store_freshness',
            lambda game, **kwargs: {'status': 'current'},
        )
        with app.test_request_context('/api/updates/scan', json={'limit': 5000}):
            from flask_login import login_user

            login_user(scan_user)
            from oneirodex.routes_apis.updates import UPDATES_SCAN_MAX, updates_scan

            body = _body(updates_scan())
        # Each title is a live store probe, so an unbounded sweep would sit on a
        # request thread for minutes and rate-limit the caller out of the stores.
        assert body['limit'] == UPDATES_SCAN_MAX


class TestUpdatesStoreSearch:
    def test_q_required(self, client, scan_user):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(scan_user.id)
            sess['_fresh'] = True
        response = client.get('/api/updates/store_search')
        assert response.status_code == 400
        body = response.get_json()
        assert body['ok'] is False
        assert body['error'] == 'q required'
        assert body['error_code'] == 'bad_request'

    def test_unknown_source(self, client, scan_user):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(scan_user.id)
            sess['_fresh'] = True
        response = client.get('/api/updates/store_search?q=Celeste&source=xbox')
        assert response.status_code == 400
        body = response.get_json()
        assert body['ok'] is False
        assert body['error'] == 'source must be steam, gog, or all'
        assert body['error_code'] == 'bad_request'


class TestLatestGamesIsNewestReleased:
    def test_latest_orders_by_release_and_excludes_the_unreleased(
        self, app, db_session, scan_user, scan_library
    ):
        from oneirodex.routes_discover import build_discover_sections

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        # The release dates are minutes apart rather than years, because the
        # shelf is a global `limit(8)` and `conftest.db_session` never cleans up
        # (`db.drop_all()` is commented out for speed) — so every game any other
        # test file has ever committed to `oneirodextest` is still there and
        # competing for those eight slots. Dated in years, these two fixtures
        # sort below the accumulated rows and the shelf never contains them at
        # all, which is a fact about the test database rather than about the
        # ordering under test. Minutes-from-now guarantees they lead it.
        #
        # What the assertion actually proves survives the compression intact:
        # 'Old cartridge' is imported *last* (`created=now`) and released
        # *first*, so if it sorts below 'This year' the shelf is ordering by
        # release date and not by import date.
        _game(
            db_session,
            scan_library,
            'Old cartridge',
            created=now,
            released=now - timedelta(minutes=2),
        )
        _game(
            db_session,
            scan_library,
            'This year',
            created=now - timedelta(days=400),
            released=now - timedelta(minutes=1),
        )
        _game(
            db_session,
            scan_library,
            'Not out yet',
            created=now - timedelta(days=1),
            released=now + timedelta(days=90),
        )

        for identifier, name, order in (
            ('latest_games', 'Latest Games', 1),
            ('new_library_games', 'New Library Games', 2),
        ):
            row = db.session.execute(
                select(DiscoverySection).filter_by(identifier=identifier)
            ).scalar_one_or_none()
            if row is None:
                db_session.add(
                    DiscoverySection(
                        identifier=identifier,
                        name=name,
                        is_visible=True,
                        display_order=order,
                    )
                )
            else:
                row.is_visible = True
        db_session.commit()

        with app.test_request_context('/'):
            sections = {s['identifier']: s for s in build_discover_sections(scan_user)}

        latest = [g['name'] for g in sections['latest_games']['games']]
        assert 'Not out yet' not in latest, (
            'an unreleased title belongs to the Upcoming shelf; letting it lead '
            'this one makes both shelves open with the same game'
        )
        assert latest.index('This year') < latest.index('Old cartridge')

        # The question the old shelf actually answered now has its own row,
        # ordered by when the row was written here rather than by release date.
        #
        # Not asserting a specific leader: the feed dedups across rows, so
        # anything `latest_games` already showed is stripped from this one
        # instead of repeated. Naming a title here would assert the dedup order
        # rather than the ordering under test, and would break the moment an
        # earlier row's contents changed. What matters is that the row exists,
        # never repeats a title, and is still newest-imported-first.
        row = sections['new_library_games']['games']
        library_new = [g['name'] for g in row]
        assert library_new, 'the shelf rendered nothing at all'
        assert not set(library_new) & set(latest), (
            'a title Latest Games already showed must not repeat here — the two '
            'rows would open with the same game, which is what splitting them '
            'was for'
        )
        created = [g['date_created'] for g in row if g.get('date_created')]
        assert created == sorted(created, reverse=True), (
            'New Library Games is newest-imported-first; this came back in some '
            'other order'
        )
