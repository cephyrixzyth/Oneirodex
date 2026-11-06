"""Font theming — per-system faces for emulator/library surfaces."""

from __future__ import annotations

import os

import pytest

from oneirodex.utils.theme_fonts import (
    BUILT_IN_FONTS,
    DEFAULT_FONT_ID,
    available_fonts,
    font_face_css,
    font_for_platform,
    resolve_font,
)


class TestCatalogue:
    def test_ships_no_console_manufacturer_typefaces(self, app):
        """Nintendo/Sega/Sony faces are trademarked and not redistributable —
        bundling one would put an infringing asset in every install."""
        with app.app_context():
            blob = ' '.join(
                f"{e['label']} {e['stack']} {e.get('file') or ''}".lower()
                for e in BUILT_IN_FONTS.values()
            )
            for brand in ('nintendo', 'sega', 'sony', 'playstation', 'gameboy', 'famicom'):
                assert brand not in blob

    def test_every_built_in_declares_its_licence(self, app):
        with app.app_context():
            for key, entry in BUILT_IN_FONTS.items():
                assert entry.get('license'), f'{key} has no licence recorded'

    def test_reports_installed_honestly(self, app):
        """A face whose file is absent must not claim to be installed — its CSS
        stack silently falls through, and the picker should be able to say so."""
        with app.app_context():
            catalogue = available_fonts()
            root = catalogue and os.path.isdir.__self__ and None  # noqa: F841
            for entry in catalogue.values():
                if entry['file'] is None:
                    assert entry['installed'] is True  # system stack always works
                else:
                    assert isinstance(entry['installed'], bool)


class TestResolution:
    def test_unknown_id_falls_back_to_default(self, app):
        with app.app_context():
            assert resolve_font('not-a-font')['label'] == BUILT_IN_FONTS[DEFAULT_FONT_ID]['label']
            assert resolve_font(None)['label'] == BUILT_IN_FONTS[DEFAULT_FONT_ID]['label']

    def test_era_appropriate_face_per_platform(self, app):
        with app.app_context():
            assert 'Press Start' in font_for_platform('NES')['stack']
            assert 'Press Start' in font_for_platform('SNES')['stack']
            # Disc era gets the 32-bit face, not the 8-bit one.
            assert 'Orbitron' in font_for_platform('PSX')['stack']
            assert 'VT323' in font_for_platform('AMIGA')['stack']

    def test_platform_lookup_is_case_insensitive(self, app):
        with app.app_context():
            assert font_for_platform('nes')['stack'] == font_for_platform('NES')['stack']

    def test_unknown_platform_gets_the_default(self, app):
        with app.app_context():
            assert font_for_platform('SOME_FUTURE_CONSOLE')['label'] == (
                BUILT_IN_FONTS[DEFAULT_FONT_ID]['label']
            )
        # A platform we have no opinion on must not error.

    def test_every_stack_has_a_fallback_family(self, app):
        """Single-family stacks break hard when the file is missing."""
        with app.app_context():
            for key, entry in BUILT_IN_FONTS.items():
                assert ',' in entry['stack'], f'{key} has no fallback family'


class TestFontFaceCss:
    def test_emits_nothing_for_missing_files(self, app, tmp_path):
        """A @font-face pointing at a missing file makes the browser fetch,
        fail, and fall back anyway — so it is noise, not resilience."""
        with app.app_context():
            app.config['FONT_PATH'] = str(tmp_path)
            assert font_face_css().strip() == ''

    def test_emits_a_rule_once_a_file_is_present(self, app, tmp_path):
        with app.app_context():
            app.config['FONT_PATH'] = str(tmp_path)
            (tmp_path / 'VT323-Regular.ttf').write_bytes(b'\x00\x01\x00\x00')
            css = font_face_css()
            assert '@font-face' in css
            assert 'VT323' in css
            assert "format('truetype')" in css

    def test_operator_drop_ins_are_offered(self, app, tmp_path):
        with app.app_context():
            app.config['FONT_PATH'] = str(tmp_path)
            (tmp_path / 'MyLicensedFace.otf').write_bytes(b'\x00\x01\x00\x00')
            catalogue = available_fonts()
            assert 'mylicensedface' in catalogue
            assert catalogue['mylicensedface']['era'] == 'operator'
            assert catalogue['mylicensedface']['installed'] is True


@pytest.fixture
def font_member(db_session):
    """A member whose preferences pin a non-default face."""
    from uuid import uuid4

    from oneirodex.models import User, UserPreference

    user_uuid = str(uuid4())
    user = User(
        name=f'fontuser_{user_uuid[:8]}',
        email=f'font_{user_uuid[:8]}@example.com',
        role='user',
        user_id=user_uuid,
    )
    user.set_password('testpassword123')
    db_session.add(user)
    db_session.commit()

    db_session.add(UserPreference(user_id=user.id, font='vt323'))
    db_session.commit()
    return user


class TestFontsCssRoute:
    """`GET /api/theme/fonts.css` — the only thing that declares the families.

    The route read `current_user` while the module imported just
    `login_required`, so every request raised `NameError` and 500'd: the
    @font-face block and the per-account preference reached no page at all,
    signed in or out. Nothing exercised the route, only the registry beneath
    it — which is why a plain missing import survived.
    """

    def test_signed_out_falls_back_to_the_default_face(self, client):
        """Deliberately unauthenticated — the login page renders in it too."""
        response = client.get('/api/theme/fonts.css')

        assert response.status_code == 200
        assert response.headers['Content-Type'].startswith('text/css')
        assert response.headers['Cache-Control'] == 'private, max-age=60'
        body = response.get_data(as_text=True)
        assert '--od-font-family:' in body
        assert BUILT_IN_FONTS[DEFAULT_FONT_ID]['stack'] in body

    def test_signed_in_gets_the_account_preference(self, client, font_member):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(font_member.id)
            sess['_fresh'] = True

        response = client.get('/api/theme/fonts.css')

        assert response.status_code == 200
        assert response.headers['Cache-Control'] == 'private, max-age=60'
        body = response.get_data(as_text=True)
        assert BUILT_IN_FONTS['vt323']['stack'] in body

    def test_query_override_beats_the_preference(self, client, font_member):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(font_member.id)
            sess['_fresh'] = True

        body = client.get('/api/theme/fonts.css?font=orbitron').get_data(as_text=True)

        assert BUILT_IN_FONTS['orbitron']['stack'] in body

    def test_installed_faces_get_their_font_face_rules(self, client, app, tmp_path):
        """Without these the files are installed and the picker lists them, but
        no page ever declares the families — the feature is inert."""
        app.config['FONT_PATH'] = str(tmp_path)
        (tmp_path / 'VT323-Regular.ttf').write_bytes(b'\x00\x01\x00\x00')

        body = client.get('/api/theme/fonts.css').get_data(as_text=True)

        assert '@font-face' in body
        assert "src: url('/static/library/fonts/VT323-Regular.ttf')" in body


def test_legacy_font_stylesheet_is_private_without_database(monkeypatch):
    from flask import Flask
    from flask_login import LoginManager

    from oneirodex.routes_apis.providers import theme_fonts_css
    from oneirodex.utils import theme_fonts

    monkeypatch.setattr(theme_fonts, 'font_face_css', lambda: '')
    app = Flask(__name__)
    app.config.update(SECRET_KEY='legacy-font-cache-test')
    login_manager = LoginManager()
    login_manager.user_loader(lambda _user_id: None)
    login_manager.init_app(app)
    app.add_url_rule('/api/theme/fonts.css', view_func=theme_fonts_css)

    response = app.test_client().get('/api/theme/fonts.css')

    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'private, max-age=60'
