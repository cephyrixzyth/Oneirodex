"""Per-member game-details layouts and named presets.

The layout editor already worked, but its one arrangement lived on
GlobalSettings — so it was install-wide, and one member re-arranging their
details page changed it for the whole household. These cover the two things
that fixes: a per-member override, and named arrangements someone can keep
more than one of.

The distinction worth protecting is between **no preference** and **an empty
one**. A member who has never opened the editor stores NULL and keeps tracking
whatever the admin sets; treating NULL as an empty layout would freeze everyone
at whatever the install default happened to be on their first visit.
"""

from uuid import uuid4

import pytest

from oneirodex.models import User
from oneirodex.utils.detail_layouts import (
    DEFAULT_SECTIONS,
    clear_user_detail_layout,
    delete_layout_preset,
    get_detail_layout,
    get_user_detail_layout,
    list_layout_presets,
    save_layout_preset,
    save_user_detail_layout,
    user_has_detail_override,
)


def _make_user(db_session, prefix):
    """Unique every time — the shared test DB keeps rows between runs."""
    user = User(
        user_id=str(uuid4()),
        name=f'{prefix}_{uuid4().hex[:8]}',
        email=f'{prefix}_{uuid4().hex[:8]}@test.com',
        role='user',
        is_email_verified=True,
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def member(db_session):
    return _make_user(db_session, 'layout_member')


def a_layout(order):
    """A layout listing `order` first, everything else after."""
    return {'sections': [{'id': sid, 'visible': True} for sid in order]}


class TestPerMemberOverride:
    def test_no_preference_follows_the_install_default(self, app, member):
        with app.app_context():
            assert get_user_detail_layout(member.id) == get_detail_layout()
            assert user_has_detail_override(member.id) is False

    def test_saving_makes_it_theirs_alone(self, app, member, db_session):
        with app.app_context():
            # Captured rather than assumed to be the shipped default: other
            # tests configure the install layout and the shared test DB keeps
            # it. What matters here is that saving a member's arrangement
            # leaves the install's *unchanged*, whatever it happened to be —
            # asserting a specific default would be testing test order.
            install_before = get_detail_layout()

            save_user_detail_layout(member.id, a_layout(['videos', 'hero']))

            mine = get_user_detail_layout(member.id)
            assert mine['sections'][0]['id'] == 'videos'
            assert user_has_detail_override(member.id) is True

            # The install layout is untouched — that was the whole bug.
            assert get_detail_layout() == install_before

    def test_clearing_returns_to_following_the_default(self, app, member):
        with app.app_context():
            save_user_detail_layout(member.id, a_layout(['related']))
            assert user_has_detail_override(member.id) is True

            cleared = clear_user_detail_layout(member.id)

            # Back to *tracking* the default, not to a copy of it — a copy would
            # pin the member to today's version forever.
            assert cleared == get_detail_layout()
            assert user_has_detail_override(member.id) is False

    def test_unknown_sections_are_dropped_not_stored(self, app, member):
        with app.app_context():
            with pytest.raises(ValueError):
                save_user_detail_layout(member.id, {'sections': [{'id': 'not-a-section'}]})

    def test_repeated_section_ids_cannot_expand_the_input_list(self):
        from oneirodex.utils.detail_layouts import validate_layout_payload

        oversized = {'sections': [{'id': 'hero'}] * (len(DEFAULT_SECTIONS) + 1)}
        with pytest.raises(ValueError, match='at most'):
            validate_layout_payload(oversized)

    def test_every_section_survives_a_partial_save(self, app, member):
        """A layout naming two sections must still render all of them."""
        with app.app_context():
            saved = save_user_detail_layout(member.id, a_layout(['playtime', 'hero']))

            ids = [s['id'] for s in saved['sections']]
            assert ids[:2] == ['playtime', 'hero']
            assert set(ids) == set(DEFAULT_SECTIONS)


class TestNamedPresets:
    def test_save_and_list(self, app, member):
        with app.app_context():
            save_layout_preset(member.id, 'Couch', a_layout(['videos']))
            save_layout_preset(member.id, 'Desk', a_layout(['metadata']))

            names = [p['name'] for p in list_layout_presets(member.id)]
            assert names == ['Couch', 'Desk']  # ordered by name

    def test_saving_an_existing_name_overwrites(self, app, member):
        """"Save as Couch" when Couch exists is an update in every editor."""
        with app.app_context():
            save_layout_preset(member.id, 'Couch', a_layout(['videos']))
            save_layout_preset(member.id, 'Couch', a_layout(['downloads']))

            presets = list_layout_presets(member.id)
            assert len(presets) == 1
            assert presets[0]['layout']['sections'][0]['id'] == 'downloads'

    def test_blank_name_is_rejected(self, app, member):
        with app.app_context():
            for bad in ('', '   ', None):
                with pytest.raises(ValueError):
                    save_layout_preset(member.id, bad, a_layout(['hero']))

    def test_delete_is_scoped_to_the_owner(self, app, member, db_session):
        """A preset id alone must not be enough to delete across accounts."""
        other = _make_user(db_session, 'layout_other')

        with app.app_context():
            mine = save_layout_preset(member.id, 'Mine', a_layout(['hero']))

            assert delete_layout_preset(other.id, mine['id']) is False
            assert len(list_layout_presets(member.id)) == 1

            assert delete_layout_preset(member.id, mine['id']) is True
            assert list_layout_presets(member.id) == []

    def test_deleting_something_that_is_not_there_is_not_an_error(self, app, member):
        with app.app_context():
            assert delete_layout_preset(member.id, 999999) is False
