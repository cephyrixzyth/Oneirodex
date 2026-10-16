from datetime import datetime, timezone
from types import SimpleNamespace

from oneirodex.utils.account_invites import invite_row, invite_url, invites_unlimited


def test_invite_projection_preserves_legacy_fields_and_expiry_rules():
    created = datetime(2026, 10, 14, 9, 30, tzinfo=timezone.utc)
    invite = SimpleNamespace(
        token='invite-token',
        recipient_email='member@example.test',
        created_at=created,
        expires_at=datetime(2026, 10, 13, 9, 30),
    )

    assert invite_row(invite, origin='https://games.example.test') == {
        'token': 'invite-token',
        'email': 'member@example.test',
        'url': 'https://games.example.test/register?token=invite-token',
        'created_at': created.isoformat(),
        'expires_at': '2026-10-13T09:30:00',
        'expired': True,
    }


def test_invite_url_builder_and_unlimited_admin_projection():
    assert invite_url('opaque', origin='https://games.example.test/') == (
        'https://games.example.test/register?token=opaque'
    )
    assert invites_unlimited(SimpleNamespace(role='admin')) is True
    assert invites_unlimited(SimpleNamespace(role='user')) is False
