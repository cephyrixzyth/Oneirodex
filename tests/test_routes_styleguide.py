"""Coverage guards for the design-system styleguide page (GT-A6).

The styleguide is the visual contract for the primitives: it renders the GT
button family and the bridged Bootstrap family side by side so a divergence is
visible instead of arriving as a bug report. Its checked-in specimen HTML is
expanded before serving, so these tests assert two things a stylesheet edit can quietly break:

  * every ``.od-btn`` modifier defined in od-primitives.css is rendered here
  * every token scale the page advertises actually exists in od-tokens.css

Both read the real theme source rather than a fixture list, so adding a variant
without showing it fails rather than silently shipping an unrepresented one.
"""

import re
from pathlib import Path
from uuid import uuid4

import pytest

from oneirodex.models import User


THEME_CSS = Path(__file__).resolve().parent.parent / 'oneirodex' / 'setup' / 'default_theme' / 'css'


@pytest.fixture
def admin_user(db_session):
    unique_id = str(uuid4())[:8]
    admin = User(
        user_id=str(uuid4()),
        name=f'TestAdmin_{unique_id}',
        email=f'admin_{unique_id}@test.com',
        role='admin',
        is_email_verified=True,
    )
    admin.set_password('testpass123')
    db_session.add(admin)
    db_session.commit()
    return admin


@pytest.fixture
def regular_user(db_session):
    unique_id = str(uuid4())[:8]
    user = User(
        user_id=str(uuid4()),
        name=f'TestUser_{unique_id}',
        email=f'user_{unique_id}@test.com',
        role='user',
        is_email_verified=True,
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


class TestStyleguideAccess:
    def test_requires_login(self, client, configured_install):
        """`configured_install` states the precondition this was relying on.

        `check_setup_status` is a `before_request` hook and `is_setup_required()`
        means "no users exist", so against an empty schema every anonymous
        request is redirected to `/setup` and never reaches the login gate this
        asserts on. Locally it passed because the shared test database always
        had a user left behind by an earlier test; on CI, which starts clean and
        runs this first in the class, it failed with
        `assert 'login' in '/setup'`.

        The precondition is what needed stating, not the assertion. Widening it
        to accept `/setup` as well would have gone green while testing nothing —
        a styleguide with its auth decorator removed would still redirect to the
        wizard on a fresh database and pass.
        """
        response = client.get('/dev/styleguide')
        assert response.status_code == 302
        assert 'login' in response.location

    def test_requires_admin(self, client, configured_install, regular_user):
        _login(client, regular_user)
        response = client.get('/dev/styleguide')
        assert response.status_code == 302
        assert 'login' in response.location

    def test_renders_for_admin(self, client, configured_install, admin_user):
        _login(client, admin_user)
        response = client.get('/dev/styleguide')
        assert response.status_code == 200


class TestStyleguideCoverage:
    def test_renders_every_gt_button_modifier(self, client, admin_user):
        """A variant added to the primitives must be shown on the styleguide.

        Otherwise the page keeps passing while no longer being a full contract,
        which is how `--ghost` came to be redefined in three page stylesheets
        without anyone noticing it had no canonical home.
        """
        primitives = (THEME_CSS / 'od-primitives.css').read_text(encoding='utf-8')
        modifiers = set(re.findall(r'\.od-btn--([a-z0-9-]+)', primitives))
        assert modifiers, 'expected od-primitives.css to define .od-btn modifiers'

        _login(client, admin_user)
        html = client.get('/dev/styleguide').get_data(as_text=True)

        missing = sorted(m for m in modifiers if f'od-btn--{m}' not in html)
        assert missing == [], f'styleguide does not render .od-btn--{{{",".join(missing)}}}'

    def test_advertised_token_scales_exist(self, client, admin_user):
        """Every --od-* token the page references must be defined.

        The page advertises its scale tokens directly, so a step removed from
        od-tokens.css shows up here as an empty swatch rather than an error.
        """
        tokens = (THEME_CSS / 'od-tokens.css').read_text(encoding='utf-8')
        defined = set(re.findall(r'^\s*(--od-[a-zA-Z0-9-]+)\s*:', tokens, re.MULTILINE))

        _login(client, admin_user)
        html = client.get('/dev/styleguide').get_data(as_text=True)

        referenced = set(re.findall(r'var\((--od-(?:font|radius|space)-[a-z0-9]+)\)', html))
        assert referenced, 'expected the styleguide to reference the token scales'

        missing = sorted(referenced - defined)
        assert missing == [], f'styleguide references undefined tokens: {missing}'

    def test_shows_both_button_families(self, client, admin_user):
        """The side-by-side comparison is the reason the page exists."""
        _login(client, admin_user)
        html = client.get('/dev/styleguide').get_data(as_text=True)

        assert 'data-sg-family="gt"' in html
        assert 'data-sg-family="bootstrap"' in html
        assert 'btn btn-primary' in html
        assert 'od-btn od-btn--primary' in html
