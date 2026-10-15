"""Member pins and admin-forced shelves — the reserved block at the top."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from oneirodex import db
from oneirodex.models import DiscoverySection, User, UserPreference
from oneirodex.utils.api_tokens import generate_api_token
from oneirodex.utils.discover_feed import MAX_ADMIN_FORCED, MAX_MEMBER_PINS


@pytest.fixture
def pin_user(db_session):
    user = User(
        name=f'pins_{uuid4().hex[:8]}',
        email=f'pins_{uuid4().hex[:8]}@example.test',
        password_hash='hashed',
        role='user',
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture(autouse=True)
def clear_forced(db_session):
    """No shelf is forced unless a test says so."""
    for section in db.session.execute(
        select(DiscoverySection).where(DiscoverySection.pin_rank.isnot(None))
    ).scalars().all():
        section.pin_rank = None
    db_session.commit()


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _force(db_session, identifier, rank):
    section = db.session.execute(
        select(DiscoverySection).filter_by(identifier=identifier)
    ).scalar_one_or_none()
    if section is None:
        pytest.skip(f'{identifier} shelf not seeded in this database')
    section.pin_rank = rank
    section.is_visible = True
    db_session.commit()
    return section


class TestMemberPins:
    def test_read_only_bearer_can_read_discover_pins(self, client, db_session, pin_user):
        _row, token = generate_api_token(pin_user, 'read-only-pins-get', ['read:library'])
        response = client.get(
            '/api/discover/pins',
            headers={'Authorization': f'Bearer {token}'},
        )
        assert response.status_code == 200
        assert 'pins' in response.get_json()

    def test_read_only_bearer_cannot_change_discover_pins(self, client, db_session, pin_user):
        _row, token = generate_api_token(pin_user, 'read-only-pins', ['read:library'])
        response = client.put(
            '/api/discover/pins', json={'pins': [], 'hidden': []},
            headers={'Authorization': f'Bearer {token}'},
        )
        assert response.status_code == 403
        assert response.get_json()['error_code'] == 'forbidden'

    def test_write_bearer_can_change_discover_pins(self, client, db_session, pin_user):
        _row, token = generate_api_token(
            pin_user, 'writable-pins', ['read:library', 'write:library'],
        )
        response = client.put(
            '/api/discover/pins', json={'pins': [], 'hidden': []},
            headers={'Authorization': f'Bearer {token}'},
        )
        assert response.status_code == 200, response.get_json()

    def test_a_member_with_no_preferences_row_has_no_pins(self, app, pin_user):
        from oneirodex.utils.discover_pins import member_pins

        with app.app_context():
            assert member_pins(pin_user) == []

    # These write, so they run in the fixture's session rather than a nested
    # app context — pushing one makes a second scoped session, and the new
    # preferences row ends up attached to the wrong one.
    def test_pins_round_trip(self, app, db_session, pin_user):
        from oneirodex.utils.discover_pins import member_pins, set_member_pins

        stored = set_member_pins(
            pin_user, ['latest_games'], available=['latest_games', 'highest_rated']
        )
        assert stored == ['latest_games']
        assert member_pins(pin_user) == ['latest_games']

    def test_more_than_three_pins_are_trimmed(self, app, db_session, pin_user):
        from oneirodex.utils.discover_pins import set_member_pins

        available = [f'row{i}' for i in range(10)]
        stored = set_member_pins(pin_user, available, available=available)

        assert len(stored) == MAX_MEMBER_PINS

    def test_a_repeated_pin_is_one_pin_not_two_slots(self, app, db_session, pin_user):
        from oneirodex.utils.discover_pins import set_member_pins

        stored = set_member_pins(pin_user, ['a', 'a', 'b'], available=['a', 'b'])

        assert stored == ['a', 'b']

    def test_pinning_an_unknown_row_is_rejected(self, app, db_session, pin_user):
        """On the way in, a bad identifier is a client bug worth surfacing."""
        from oneirodex.utils.discover_pins import set_member_pins

        with pytest.raises(ValueError):
            set_member_pins(pin_user, ['nope'], available=['a'])

    def test_a_pinned_row_that_goes_away_is_dropped_on_read(
        self, app, db_session, pin_user
    ):
        """On the way out it is just a row that stopped existing.

        A genre row can go away when a member's taste moves, and an admin can
        hide a shelf somebody had pinned. Neither is an error.
        """
        from oneirodex.utils.discover_pins import member_pins, set_member_pins

        set_member_pins(pin_user, ['a', 'b'], available=['a', 'b'])
        assert member_pins(pin_user, available=['a']) == ['a']

    def test_a_corrupt_pin_value_reads_as_no_pins(self, app, db_session, pin_user):
        """The JSON column returns {} when a value fails to decode, so a list
        column can legitimately hand back a dict."""
        from oneirodex.utils.discover_pins import member_pins

        prefs = UserPreference(user_id=pin_user.id)
        prefs.discover_pins = {'not': 'a list'}
        db_session.add(prefs)
        db_session.commit()

        with app.app_context():
            assert member_pins(pin_user) == []


class TestAdminForced:
    def test_forced_shelves_come_back_lowest_rank_first(self, app, db_session):
        from oneirodex.utils.discover_pins import admin_forced

        _force(db_session, 'highest_rated', 2)
        _force(db_session, 'latest_games', 1)

        with app.app_context():
            forced = admin_forced()

        assert forced[:2] == ['latest_games', 'highest_rated']

    def test_an_admin_cannot_force_more_than_their_share(self, app, db_session):
        """Capped so a member's pins are never pushed below the fold."""
        from oneirodex.utils.discover_pins import admin_forced

        sections = db.session.execute(
            select(DiscoverySection).limit(MAX_ADMIN_FORCED + 3)
        ).scalars().all()
        if len(sections) < MAX_ADMIN_FORCED + 1:
            pytest.skip('not enough shelves seeded to test the cap')
        for rank, section in enumerate(sections):
            section.pin_rank = rank
        db_session.commit()

        with app.app_context():
            assert len(admin_forced()) == MAX_ADMIN_FORCED

    def test_no_forced_shelves_is_an_empty_list(self, app):
        from oneirodex.utils.discover_pins import admin_forced

        with app.app_context():
            assert admin_forced() == []


class TestPinsEndpoint:
    def test_requires_login(self, client):
        assert client.get('/api/discover/pins').status_code in (302, 401)

    def test_get_reports_the_cap_and_what_can_be_pinned(self, app, client, pin_user):
        _login(client, pin_user)

        body = client.get('/api/discover/pins').get_json()

        assert body['ok'] is True
        assert body['max_pins'] == MAX_MEMBER_PINS
        assert isinstance(body['available'], list)

    def test_put_stores_pins(self, app, client, pin_user):
        _login(client, pin_user)
        available = client.get('/api/discover/pins').get_json()['available']
        if not available:
            pytest.skip('no rows available to pin in this database')

        response = client.put('/api/discover/pins', json={'pins': available[:1]})

        assert response.status_code == 200
        assert response.get_json()['pins'] == available[:1]

    def test_a_non_list_body_is_rejected(self, app, client, pin_user):
        _login(client, pin_user)

        response = client.put('/api/discover/pins', json={'pins': 'latest_games'})

        assert response.status_code == 400
        assert response.get_json()['error_code'] == 'bad_request'

    def test_too_many_pins_is_rejected_rather_than_silently_trimmed(
        self, app, client, pin_user
    ):
        """A fourth pin that vanished without a word would look like a bug."""
        _login(client, pin_user)

        response = client.put(
            '/api/discover/pins',
            json={'pins': [f'r{i}' for i in range(MAX_MEMBER_PINS + 1)]},
        )

        assert response.status_code == 422
        assert response.get_json()['error_code'] == 'unprocessable'

    def test_pinning_a_row_that_is_not_on_the_feed_is_a_404_envelope(
        self, app, client, pin_user
    ):
        _login(client, pin_user)

        response = client.put('/api/discover/pins', json={'pins': ['no_such_row']})

        assert response.status_code == 404
        body = response.get_json()
        assert body['ok'] is False
        assert body['error_code'] == 'not_found'


class TestForcedShelvesReachTheFeed:
    def test_a_forced_shelf_leads_the_feed(self, app, db_session, pin_user):
        from oneirodex.routes_discover import build_discover_sections

        _force(db_session, 'highest_rated', 1)

        with app.app_context(), app.test_request_context('/'):
            sections = build_discover_sections(pin_user)

        identifiers = [row['identifier'] for row in sections]
        if 'highest_rated' not in identifiers:
            pytest.skip('highest_rated had nothing to show in this database')
        assert identifiers[0] == 'highest_rated'
