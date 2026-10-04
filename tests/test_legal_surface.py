"""Phase 6 of the security/legal playbook — AGPL §13 offer + log scrub (L4, L5, S9).

The configurability of the source URL is the point of the L4 tests, not a nicety:
§13 obliges *this* deployment to offer *its* source. A hardcoded upstream link
would be the wrong answer for exactly the person the clause exists to protect —
someone using a modified copy over the network.

See docs/strategy/security-legal-playbook.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from oneirodex.utils.security import sanitize_path_for_logging

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = REPO_ROOT / 'oneirodex' / 'templates'


# --- S9: path scrubbing ---------------------------------------------------

class TestPathScrub:
    @pytest.mark.parametrize('path,leaked', [
        (r'C:\Users\alice\games\rom.zip', 'alice'),
        (r'D:\users\bob\library', 'bob'),
        ('/home/carol/games/rom.zip', 'carol'),
        ('/Users/dave/Library/roms', 'dave'),
        ('/usr/home/erin/roms', 'erin'),
    ])
    def test_username_is_removed(self, path, leaked):
        """The Windows rule matched only doubled backslashes, so it never fired."""
        assert leaked not in sanitize_path_for_logging(path)

    def test_windows_separator_is_preserved(self):
        scrubbed = sanitize_path_for_logging(r'C:\Users\alice\games')
        assert '[USER]' in scrubbed
        assert '\\' in scrubbed

    def test_posix_separator_is_preserved(self):
        scrubbed = sanitize_path_for_logging('/home/carol/games')
        assert '[USER]' in scrubbed
        assert '/home/' in scrubbed

    def test_the_rest_of_the_path_survives(self):
        """Scrubbing must leave a log line an operator can still act on."""
        scrubbed = sanitize_path_for_logging(r'C:\Users\alice\games\Chrono.zip')
        assert 'games' in scrubbed
        assert 'Chrono.zip' in scrubbed

    def test_paths_without_a_home_directory_are_untouched(self):
        assert sanitize_path_for_logging('/mnt/storage/roms') == '/mnt/storage/roms'

    def test_invalid_input_is_handled(self):
        assert sanitize_path_for_logging(None) == '[INVALID_PATH]'
        assert sanitize_path_for_logging(123) == '[INVALID_PATH]'


# --- L4: the AGPL §13 source offer ----------------------------------------

class TestSourceOffer:
    def test_config_carries_a_source_url(self):
        from config import Config

        assert Config.ONEIRODEX_SOURCE_URL
        assert Config.ONEIRODEX_SOURCE_URL.startswith('http')

    def test_source_url_is_configurable(self, monkeypatch):
        """A modified deployment owes its users *its* source, not upstream's."""
        monkeypatch.delenv('ONEIRODEX_SOURCE_URL', raising=False)
        monkeypatch.setenv('ONEIRODEX_SOURCE_URL', 'https://git.example.com/my/fork')
        import importlib

        import config as config_module

        importlib.reload(config_module)
        try:
            assert config_module.Config.ONEIRODEX_SOURCE_URL == 'https://git.example.com/my/fork'
        finally:
            monkeypatch.delenv('ONEIRODEX_SOURCE_URL', raising=False)
            monkeypatch.delenv('ONEIRODEX_SOURCE_URL', raising=False)
            importlib.reload(config_module)

    def test_oneirodex_source_url_wins(self, monkeypatch):
        monkeypatch.setenv('ONEIRODEX_SOURCE_URL', 'https://git.example.com/legacy')
        monkeypatch.setenv('ONEIRODEX_SOURCE_URL', 'https://git.example.com/new')
        import importlib

        import config as config_module

        importlib.reload(config_module)
        try:
            assert config_module.Config.ONEIRODEX_SOURCE_URL == 'https://git.example.com/new'
        finally:
            monkeypatch.delenv('ONEIRODEX_SOURCE_URL', raising=False)
            monkeypatch.delenv('ONEIRODEX_SOURCE_URL', raising=False)
            importlib.reload(config_module)

    def test_templates_receive_the_offer(self, app, db_session):
        """Injected for every template, so both surfaces can render it.

        render_template_string, not jinja_env.from_string: only the former runs
        the app's context processors, which is where source_url comes from.

        `db_session` is what builds the schema, and one of those context
        processors reads global_settings — without it this passed only when an
        earlier test in the run happened to have built the tables first, and
        failed against a freshly created database.
        """
        from flask import render_template_string

        with app.test_request_context('/'):
            rendered = render_template_string('{{ source_url }}|{{ app_version }}')
        url, version = rendered.split('|')
        assert url.startswith('http')
        assert version

    def test_member_shell_hands_it_to_the_spa(self):
        shell = (TEMPLATES / 'site' / 'member_spa.html').read_text(encoding='utf-8')
        assert 'data-source-url' in shell

    def _help_page_source(self) -> str:
        return (
            REPO_ROOT / 'frontend' / 'member-app' / 'src' / 'pages' / 'HelpPage.tsx'
        ).read_text(encoding='utf-8')

    def test_help_renders_the_offer(self):
        """Help → About is the offer's home.

        It used to be stamped in a footer under every admin screen as well.
        That footer is gone, so this is now the only surface carrying it and
        the assertions that guarded the footer live here instead: §13 asks
        that the offer be reachable, and one findable place satisfies it.
        """
        help_page = self._help_page_source()
        assert 'sourceUrl' in help_page
        assert 'agpl-3.0' in help_page.lower()

    def test_help_offer_is_skipped_when_unset(self):
        """An offer of source that goes nowhere is worse than none."""
        help_page = self._help_page_source()
        assert '{shellConfig.sourceUrl ?' in help_page

    def test_admin_carries_no_licence_footer(self):
        """Removed by request; asserted so it does not creep back unnoticed."""
        base = (TEMPLATES / 'base_admin.html').read_text(encoding='utf-8')
        assert 'od-admin-licence' not in base


# --- L5: provider attribution ---------------------------------------------

class TestAttribution:
    def _help_page(self) -> str:
        return (
            REPO_ROOT / 'frontend' / 'member-app' / 'src' / 'pages' / 'HelpPage.tsx'
        ).read_text(encoding='utf-8')

    @pytest.mark.parametrize('provider', ['IGDB', 'Giant Bomb', 'SteamGridDB'])
    def test_metadata_providers_are_credited(self, provider):
        assert provider in self._help_page()

    def test_licence_is_named_in_the_member_app(self):
        page = self._help_page()
        assert 'Affero' in page or 'AGPL' in page

    def test_source_link_comes_from_config_not_a_constant(self):
        page = self._help_page()
        assert 'sourceUrl' in page
        # The source offer must come from config, not a baked GitHub URL.
        assert 'href="https://github.com/cephyrixzyth/oneirodex"' not in page
        assert 'href="https://github.com/cephyrixzyth/oneirodex"' not in page
