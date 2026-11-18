"""Tests for Wave 2d loading icon admin settings (rotate | lock)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from oneirodex.models import GlobalSettings, User
from oneirodex.utils.global_settings import global_settings_row_or_create
from oneirodex.utils.loading_icons import (
    BUILTIN_LOADING_ICONS,
    DEFAULT_LOADING_ICON_MODE,
    catalogue_ids,
    get_loading_icon_settings,
    save_loading_icon_settings,
)


def _login(client, db_session, *, role='admin'):
    user = User(
        user_id=str(uuid4()),
        name=f'li_{uuid4().hex[:8]}',
        email=f'li_{uuid4().hex[:8]}@test.local',
        role=role,
        is_email_verified=True,
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
    return user


def test_global_settings_has_loading_icon_columns():
    assert hasattr(GlobalSettings, 'loading_icon_mode')
    assert hasattr(GlobalSettings, 'loading_icon_id')
    assert GlobalSettings.loading_icon_mode.default.arg == 'rotate'


def test_defaults_rotate_null_id(app, db_session):
    row = db_session.query(GlobalSettings).order_by(GlobalSettings.id).first()
    if row is None:
        row = GlobalSettings()
        db_session.add(row)
        db_session.commit()
    row.loading_icon_mode = None
    row.loading_icon_id = None
    db_session.commit()

    with app.app_context():
        data = get_loading_icon_settings(admin=True)
    assert data['loading_icon_mode'] == DEFAULT_LOADING_ICON_MODE
    assert data['loading_icon_id'] is None
    assert data['resolved_id'] is None
    assert data['defaults']['loading_icon_mode'] == 'rotate'
    assert data['defaults']['loading_icon_id'] is None
    assert {c['id'] for c in data['catalogue']} == set(catalogue_ids())
    assert len(BUILTIN_LOADING_ICONS) >= 1


def test_lock_requires_id(app, db_session):
    row = global_settings_row_or_create()
    # Cleared explicitly: save_loading_icon_settings falls back to the *stored*
    # id when the payload omits one, so a leftover pick from an earlier test
    # would satisfy the lock and this would assert nothing.
    row.loading_icon_id = None
    db_session.commit()
    with app.app_context():
        with pytest.raises(ValueError, match='required'):
            save_loading_icon_settings({'loading_icon_mode': 'lock'})


def test_unknown_icon_id_rejected(app, db_session):
    row = global_settings_row_or_create()
    db_session.commit()
    with app.app_context():
        with pytest.raises(ValueError, match='Unknown'):
            save_loading_icon_settings({
                'loading_icon_mode': 'lock',
                'loading_icon_id': 'not-a-real-icon',
            })


def test_retired_motif_ids_resolve_instead_of_raising():
    """A stored preference naming an old motif must not break (GT-B23).

    normalize_icon_id raises on anything outside the catalogue, and the
    catalogue changed under members who had already picked one. Their stored
    value is not theirs to fix, so retired ids map forward rather than erroring.
    """
    from oneirodex.utils.loading_icons import normalize_icon_id

    assert normalize_icon_id('ring') == 'disc'
    assert normalize_icon_id('orbit') == 'disc'
    assert normalize_icon_id('pulse') == 'crt'
    assert normalize_icon_id('blocks') == 'cart'
    assert normalize_icon_id('scan') == 'crt'

    # 'arcade' is NOT aliased, and asserting it mapped to 'dpad' was wrong in
    # both directions: LEGACY_LOADING_ICON_ALIASES deliberately omits it, and it
    # is a live id in the per-system catalogue (the Arcade platform). Someone who
    # picked the old abstract "arcade" keeps a working id and gets a cabinet,
    # which is the better outcome than being redirected to a d-pad.
    assert normalize_icon_id('arcade') == 'arcade'


def test_unknown_motif_id_still_raises():
    """The alias map must not turn validation into a silent accept-anything."""
    import pytest as _pytest

    from oneirodex.utils.loading_icons import normalize_icon_id

    with _pytest.raises(ValueError):
        normalize_icon_id('not-a-motif')
