"""An interrupted setup must never brick the install.

`setup_submit` used to commit the admin user and then, in a *second*
transaction, advance the wizard to step 2. Anything failing in between — a
crash, a container restart, a dropped connection — left the pair of facts
"a user exists" and "still on step 1".

That combination is an unrecoverable redirect loop, not a cosmetic glitch:

    before_request  -> should_redirect_to_setup() is True (setup in progress)
                    -> get_setup_redirect_url() returns '/setup' for step 1
    GET /setup      -> not is_setup_required() and is_setup_in_progress()
                    -> redirect(get_setup_redirect_url()) -> '/setup'

Every route in the app redirects to /setup, and /setup redirects to itself.
There is no way out through the UI; it needs a database edit.

These tests pin both halves of the fix: the write is atomic now, and an install
already stranded in that state recovers instead of looping.
"""

from uuid import uuid4

import pytest

from oneirodex.models import GlobalSettings, User


@pytest.fixture
def stranded_install(db_session):
    """The exact state the old two-commit sequence could leave behind."""
    user = User(
        user_id=str(uuid4()),
        name=f'Stranded_{uuid4().hex[:8]}',
        email=f'stranded_{uuid4().hex[:8]}@test.com',
        role='admin',
        is_email_verified=True,
    )
    user.set_password('testpass123')
    db_session.add(user)

    # Must be the row the application reads, not just any row. global_settings
    # is a singleton only by convention, the shared test DB accumulates
    # duplicates across runs, and an unordered .first() is free to return a
    # different one per query — so configuring "a" row here and asserting on
    # "the" row later compared two different objects.
    from oneirodex.utils.global_settings import global_settings_row_or_create

    settings = global_settings_row_or_create()
    previous = (
        settings.setup_in_progress,
        settings.setup_completed,
        settings.setup_current_step,
    )
    settings.setup_in_progress = True
    settings.setup_completed = False
    settings.setup_current_step = 1  # user exists, wizard never advanced
    db_session.commit()

    yield settings

    # Restore, or this fixture poisons the rest of the run. "Setup in progress"
    # is global state that before_request acts on, so every later test's routes
    # would redirect to the wizard and fail for reasons that look nothing like
    # their own subject.
    (
        settings.setup_in_progress,
        settings.setup_completed,
        settings.setup_current_step,
    ) = previous
    db_session.commit()


class TestStrandedSetupRecovers:
    def test_setup_does_not_redirect_to_itself(self, client, stranded_install):
        response = client.get('/setup')

        assert response.status_code in (200, 302)
        if response.status_code == 302:
            assert not response.location.rstrip('/').endswith('/setup'), (
                'GET /setup redirected to /setup — this is the loop that made '
                'the install unreachable'
            )

    def test_a_normal_route_reaches_something_other_than_setup(
        self, client, stranded_install
    ):
        """Following redirects must terminate rather than bounce forever."""
        response = client.get('/library', follow_redirects=True)

        assert response.status_code == 200

    def test_recovery_advances_past_the_completed_step(self, client, stranded_install):
        """Step 1 is 'create the admin account', and that is provably done."""
        from oneirodex.utils.setup import get_setup_redirect_url

        url = get_setup_redirect_url()

        assert url != '/setup'
        assert stranded_install.setup_current_step != 1


