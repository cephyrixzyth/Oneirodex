"""Linked store accounts must stay current, not sync once and rot (GT-B27).

`sync_steam_owned_games` always worked; nothing ever ran it a second time. So
linking a Steam account synced at the moment you linked it and was stale from
the next purchase onward — which makes a linked account no better than the CSV
import it was meant to improve on.

These pin the behaviours that make the poller safe to leave running unattended:
it respects the admin kill switch, it does not thrash a third-party API on our
users' keys, and one member's broken link does not stop everyone else's refresh.
"""

from uuid import uuid4

import pytest

from oneirodex.models import StoreAccount, User


@pytest.fixture
def member(db_session):
    user = User(
        user_id=str(uuid4()),
        name=f'Owner_{uuid4().hex[:8]}',
        email=f'owner_{uuid4().hex[:8]}@test.com',
        role='user',
        is_email_verified=True,
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


def test_poll_interval_is_clamped(app):
    from oneirodex.utils.ownership_poller import _poll_seconds

    app.config['OWNERSHIP_POLL_HOURS'] = 0.01
    assert _poll_seconds(app) == 3600, 'floor protects a third-party API'

    app.config['OWNERSHIP_POLL_HOURS'] = 10_000
    assert _poll_seconds(app) == 168 * 3600, 'ceiling keeps it a refresh, not a one-off'

    app.config['OWNERSHIP_POLL_HOURS'] = 'nonsense'
    assert _poll_seconds(app) == 12 * 3600, 'a bad value must not crash the poller'


def test_disabled_by_config(app):
    from oneirodex.utils.ownership_poller import _is_enabled

    app.config['ENABLE_OWNERSHIP_POLL'] = False
    assert _is_enabled(app) is False


def test_respects_the_admin_kill_switch(app, monkeypatch):
    """Admin disabling ownership sync must stop the background job too.

    Otherwise the setting only governs the button a member can see, while the
    poller keeps talking to Steam behind it.
    """
    from oneirodex.utils import ownership_poller

    monkeypatch.setattr(
        'oneirodex.utils.store_ownership.is_ownership_sync_enabled', lambda: False
    )

    with app.app_context():
        result = ownership_poller.sync_all_linked_accounts()

    assert 'skipped' in result
    assert 'disabled' in result['skipped']


def test_skips_cleanly_without_an_api_key(app, monkeypatch):
    """No key means every call fails identically — say it once, not per member."""
    from oneirodex.utils import ownership_poller

    monkeypatch.setattr(
        'oneirodex.utils.store_ownership.is_ownership_sync_enabled', lambda: True
    )
    monkeypatch.setattr(
        'oneirodex.utils.store_ownership.get_steam_web_api_key', lambda: None
    )
    monkeypatch.setattr(
        'oneirodex.utils.store_ownership.gog_live_ready', lambda: False
    )
    monkeypatch.setattr(
        'oneirodex.utils.store_ownership.epic_live_ready', lambda: False
    )
    monkeypatch.setattr(
        'oneirodex.utils.store_ownership.amazon_live_ready', lambda: False
    )

    with app.app_context():
        result = ownership_poller.sync_all_linked_accounts()

    assert 'Steam Web API' in result['skipped']


def test_one_broken_account_does_not_stop_the_rest(app, db_session, member, monkeypatch):
    """The usual way a batch job silently stops working for a whole install."""
    from oneirodex.utils import ownership_poller

    other = User(
        user_id=str(uuid4()),
        name=f'Owner2_{uuid4().hex[:8]}',
        email=f'owner2_{uuid4().hex[:8]}@test.com',
        role='user',
        is_email_verified=True,
    )
    other.set_password('testpass123')
    db_session.add(other)
    db_session.commit()

    for user in (member, other):
        db_session.add(
            StoreAccount(user_id=user.id, store='steam', external_account_id='7656119')
        )
    db_session.commit()

    monkeypatch.setattr(
        'oneirodex.utils.store_ownership.is_ownership_sync_enabled', lambda: True
    )
    monkeypatch.setattr(
        'oneirodex.utils.store_ownership.get_steam_web_api_key', lambda: 'key'
    )
    monkeypatch.setattr(
        'oneirodex.utils.store_ownership.gog_live_ready', lambda: False
    )
    monkeypatch.setattr(
        'oneirodex.utils.store_ownership.epic_live_ready', lambda: False
    )
    monkeypatch.setattr(
        'oneirodex.utils.store_ownership.amazon_live_ready', lambda: False
    )

    calls = []

    def flaky(user_id):
        calls.append(user_id)
        if user_id == member.id:
            raise ValueError('private profile')
        return {'added': 1}

    monkeypatch.setattr(
        'oneirodex.utils.store_ownership.sync_steam_owned_games', flaky
    )

    with app.app_context():
        result = ownership_poller.sync_all_linked_accounts()

    # Scoped to the two accounts this test created. The shared test DB keeps
    # StoreAccount rows from earlier runs, so a global count climbs every run —
    # the same collision _unique_steam_app_id() guards against in
    # test_store_ownership.py. What matters is that the raising account did not
    # stop the other one, which is a statement about these two users.
    mine = [user_id for user_id in calls if user_id in (member.id, other.id)]
    assert sorted(mine) == sorted([member.id, other.id]), (
        'the failure must not abort the loop'
    )
    assert result['failed'] >= 1
    assert result['synced'] >= 1


def test_only_stores_with_a_live_api_are_polled():
    """Amazon is live register now; Steam / GOG / Epic / Amazon are enrolled."""
    from oneirodex.utils.ownership_poller import LIVE_SYNC_STORES

    assert set(LIVE_SYNC_STORES) == {'steam', 'gog', 'epic', 'amazon'}


class TestSyncModeHonesty:
    """What the product claims must match what it can actually do.

    Linking a GOG or Epic account looked exactly like linking Steam: same flow,
    a one-time list of titles, and then nothing — no refresh, and nothing
    anywhere saying so. A register that silently goes stale is worse than one
    you know is a snapshot, because you trust it.

    STORE_SYNC_MODE is what the ownership UI reads to decide between "current"
    and "snapshot from a while ago". These keep it tied to the poller, so a
    store cannot be advertised as live before it can be synced.
    """

    def test_steam_gog_and_epic_claim_live_sync(self):
        from oneirodex.utils.store_ownership import STORE_SYNC_MODE, store_sync_mode

        live = [s for s in STORE_SYNC_MODE if store_sync_mode(s) == 'live']
        assert live == ['steam', 'gog', 'epic', 'amazon']
        assert store_sync_mode('playnite') == 'snapshot'

    def test_unknown_stores_default_to_snapshot(self):
        """The safe direction to be wrong in — claiming less, never more."""
        from oneirodex.utils.store_ownership import store_sync_mode

        assert store_sync_mode('some-new-store') == 'snapshot'
        assert store_sync_mode('') == 'snapshot'
        assert store_sync_mode(None) == 'snapshot'

    def test_advertising_a_store_as_live_without_a_handler_fails_loudly(
        self, app, monkeypatch
    ):
        """The guard that stops the UI over-claiming again."""
        from oneirodex.utils import ownership_poller, store_ownership

        monkeypatch.setitem(store_ownership.STORE_SYNC_MODE, 'playnite', 'live')

        with app.app_context():
            with pytest.raises(RuntimeError, match='advertises'):
                ownership_poller._live_sync_handlers()

    def test_summary_reports_sync_mode_per_store(self, app, db_session, member):
        """The field the UI needs to tell a snapshot from a live register."""
        from oneirodex.utils.store_ownership import get_ownership_summary

        with app.app_context():
            summary = get_ownership_summary(member.id)

            assert summary['stores']['steam']['live_sync'] is True
            assert summary['stores']['gog']['live_sync'] is True
            assert summary['stores']['gog']['sync_mode'] == 'live'
            assert summary['stores']['amazon']['live_sync'] is True
            assert summary['stores']['amazon']['sync_mode'] == 'live'
            # Present even when never synced, so the UI does not have to guess
            # whether the key is missing or the value is genuinely unknown.
            assert 'last_synced_at' in summary['stores']['gog']

    def test_a_mismatch_stops_the_poller_starting_not_the_app(self, app, monkeypatch):
        """Where the guard fires matters as much as that it fires.

        The checks only ran inside sync_all_linked_accounts(), which the loop
        wraps in a try/except that prints — so a mismatched registry booted
        cleanly and then failed every twelve hours where nobody was looking.
        Validating at start makes it loud and immediate, and returning rather
        than raising keeps a developer error from taking a household's install
        down after an upgrade.
        """
        from oneirodex.utils import ownership_poller, store_ownership

        monkeypatch.setitem(store_ownership.STORE_SYNC_MODE, 'playnite', 'live')
        app.config['ENABLE_OWNERSHIP_POLL'] = True

        # Must not raise — the app keeps booting.
        assert ownership_poller.start_ownership_scheduler(app) is None

        # And must not have armed a poller that can only fail.
        assert ownership_poller._scheduler.thread is None
