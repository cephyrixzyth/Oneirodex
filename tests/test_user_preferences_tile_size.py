"""tile_size preference: model field, form field, normalization, settings save.

Tile size used to be one of `S`/`M`/`L`/`XL` in a `VARCHAR(4)` defaulting to
`'M'`. It is a **0–100 percentage** now, and these four tests all pinned the
old design — one of them by asserting a literal `ADD COLUMN … VARCHAR(4)
DEFAULT 'M'` string was present in `updateschema.py`.

Two of them read source files and asserted on their text. That is worth calling
out, because such a test cannot tell a working implementation from a renamed
variable: it passes while the feature is broken and fails while the feature is
fine, which is precisely backwards. They assert behaviour now.
"""
import pytest
from unittest.mock import patch

from flask import Flask


def test_user_preference_model_has_tile_size():
    from oneirodex.models import UserPreference

    col = UserPreference.__table__.c.tile_size
    assert col is not None
    assert 'String' in type(col.type).__name__
    # A percentage, and never null — the grid has to size itself somehow.
    assert col.default.arg == '50'
    assert col.nullable is False


def test_user_preferences_form_includes_tile_size():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'test'
    app.config['WTF_CSRF_ENABLED'] = False

    with app.app_context():
        with patch('oneirodex.forms.ThemeManager') as tm:
            tm.return_value.get_installed_themes.return_value = []
            from oneirodex.forms import UserPreferencesForm

            form = UserPreferencesForm()
            assert 'tile_size' in form._fields
            # Free text, not a choice list: the slider is continuous, so
            # asserting `.choices` now raises AttributeError rather than
            # failing an equality check.
            assert not hasattr(form.tile_size, 'choices')
            assert form.tile_size.default == '50'


class TestTilePercentNormalization:
    """The conversion that lets old rows keep working."""

    def test_legacy_sizes_map_onto_the_percentage_scale(self):
        from oneirodex.routes_settings import _normalize_tile_percent

        mapped = {size: _normalize_tile_percent(size) for size in ('S', 'M', 'L', 'XL')}
        assert all(v.isdigit() for v in mapped.values())
        # Ordered, or a saved 'L' would come back smaller than a saved 'S'.
        assert sorted(mapped.values(), key=int) == [
            mapped['S'], mapped['M'], mapped['L'], mapped['XL']
        ]

    def test_lowercase_legacy_values_still_map(self):
        from oneirodex.routes_settings import _normalize_tile_percent

        assert _normalize_tile_percent('m') == _normalize_tile_percent('M')

    def test_out_of_range_is_clamped_not_rejected(self):
        from oneirodex.routes_settings import _normalize_tile_percent

        assert _normalize_tile_percent('999') == '100'
        assert _normalize_tile_percent('-40') == '0'

    def test_nonsense_falls_back_to_the_default(self):
        from oneirodex.routes_settings import _normalize_tile_percent

        for junk in ('', None, 'huge', '12px'):
            assert _normalize_tile_percent(junk) == '50'


@pytest.fixture
def member(db_session):
    """A logged-in member. This file has no shared fixtures of its own."""
    from uuid import uuid4

    from oneirodex.models import User

    suffix = uuid4().hex[:8]
    user = User(
        name=f'tilesize_{suffix}',
        email=f'tilesize_{suffix}@example.com',
        password_hash='x',
        role='user',
        user_id=str(uuid4()),
        avatarpath='newstyle/avatar_default.jpg',
    )
    user.set_password('tilesizepassword123')
    db_session.add(user)
    db_session.commit()
    return user


def test_settings_panel_persists_the_tile_size(client, member, db_session):
    """Replaces a test that grepped routes_settings.py for an assignment line.

    Posting the preference and reading it back covers the thing that actually
    matters, and survives the code being refactored — which the string match
    would not have.
    """
    from oneirodex.models import UserPreference

    with client.session_transaction() as sess:
        sess['_user_id'] = str(member.id)
        sess['_fresh'] = True

    response = client.post('/settings_panel', data={
        'items_per_page': 20,
        'default_sort': 'name',
        'default_sort_order': 'asc',
        'theme': 'default',
        'icon_pack': 'outline',
        'font': 'system-ui',
        'tile_size': '85',
        'preferred_game_locale': 'en-US',
    })

    assert response.status_code == 200
    prefs = db_session.execute(
        db_session.query(UserPreference).filter_by(user_id=member.id).statement
    ).scalars().first()
    assert prefs is not None
    assert prefs.tile_size == '85'


def test_partial_save_keeps_the_fields_it_did_not_send(client, member, db_session):
    """The top-bar slider posts `tile_size` alone.

    The form has five SelectFields, and WTForms rejects a SelectField that is
    absent from the POST — so every slider save used to come back 400 and the
    size never persisted (the client swallows the error as best-effort). A
    partial save now fills the stored values in underneath the posted ones,
    and leaves them exactly as they were.
    """
    from oneirodex.models import UserPreference

    with client.session_transaction() as sess:
        sess['_user_id'] = str(member.id)
        sess['_fresh'] = True

    full = client.post('/settings_panel', data={
        '_full_form': '1',
        'items_per_page': 100,
        'default_sort': 'rating',
        'default_sort_order': 'desc',
        'theme': 'default',
        'icon_pack': 'outline',
        'font': 'system-ui',
        'tile_size': '40',
        # Checkbox left unchecked: absent from a whole-form post.
        'preferred_game_locale': 'ja-JP',
    })
    assert full.status_code == 200, full.get_json()

    partial = client.post('/settings_panel', data={'tile_size': '85'})
    assert partial.status_code == 200, partial.get_json()

    prefs = db_session.execute(
        db_session.query(UserPreference).filter_by(user_id=member.id).statement
    ).scalars().first()
    assert prefs.tile_size == '85'
    assert prefs.items_per_page == 100
    assert prefs.default_sort == 'rating'
    assert prefs.default_sort_order == 'desc'
    assert prefs.preferred_game_locale == 'ja-JP'
    # The whole-form save switched titles off; the partial one must not
    # switch them back on just because it did not mention them.
    assert prefs.show_tile_titles is False


def test_engine_picker_choice_is_exposed_only_when_admin_allows_it(client, member, monkeypatch):
    from oneirodex.routes_apis import preferences as preferences_api

    with client.session_transaction() as sess:
        sess['_user_id'] = str(member.id)
        sess['_fresh'] = True

    monkeypatch.setattr(
        preferences_api,
        'play_engine_fields',
        lambda: {'browser_player_member_choice': False},
    )
    hidden = client.get('/api/account/preferences')
    assert hidden.status_code == 200
    hidden_body = hidden.get_json()
    assert hidden_body['member_engine_choice'] is False
    assert {choice['value'] for choice in hidden_body['choices']['browser_player_engines']} >= {
        '', 'webretro', 'emulatorjs'
    }

    monkeypatch.setattr(
        preferences_api,
        'play_engine_fields',
        lambda: {'browser_player_member_choice': True},
    )
    visible = client.get('/api/account/preferences')
    assert visible.status_code == 200
    assert visible.get_json()['member_engine_choice'] is True
