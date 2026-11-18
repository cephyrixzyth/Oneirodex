"""What the served HTML shells must carry, checked on the rendered pages.

Replaces source scans of the retired Flask shell builders: the toast script
loads after its dependency, the member shell links its bundle, the PWA
manifest and installer, the era styles and the source offer; heavy vendor
widgets stay out; the admin page boots the admin app; and the sign-in page
carries no member navigation.
"""
from uuid import uuid4

import pytest

from oneirodex.models import User


@pytest.fixture
def member(db_session):
    user = User(
        name=f'shell_{uuid4().hex[:8]}', email=f'shell_{uuid4().hex[:8]}@example.test',
        role='admin', user_id=str(uuid4()), state=True, is_email_verified=True,
    )
    user.set_password('a long test password')
    db_session.add(user)
    db_session.commit()
    return user


def _signed_in(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def test_member_shell_links_its_assets_in_order(client, member):
    _signed_in(client, member)
    html = client.get('/discover').get_data(as_text=True)

    assert 'member-app.css' in html and 'id="member-app-root"' in html
    assert html.index('notify.min.js') < html.index('od_toast.js')
    assert 'rel="manifest"' in html and 'od_pwa_install.js' in html
    assert 'od-era.css' in html and 'atmosphere' in html
    assert 'data-source' in html  # the source offer reaches the member app
    lowered = html.lower()
    assert 'datatables' not in lowered and 'cropper' not in lowered


def test_admin_page_boots_the_admin_app(client, member):
    _signed_in(client, member)
    html = client.get('/admin/dashboard').get_data(as_text=True)

    assert 'admin-spa' in html
    assert 'id="member-app-root"' not in html


def test_sign_in_page_has_no_member_navigation(client):
    html = client.get('/login').get_data(as_text=True)

    assert 'id="member-app-root"' not in html
