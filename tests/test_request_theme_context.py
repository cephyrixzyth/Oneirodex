"""Member theme isolation without an app, database or filesystem fixture."""
import asyncio
from types import SimpleNamespace
import unittest

from oneirodex.utils.request_theme import request_theme, set_request_theme_from_user


def member(theme):
    return SimpleNamespace(preferences=SimpleNamespace(theme=theme))


class RequestThemeContextTests(unittest.TestCase):
    def tearDown(self):
        set_request_theme_from_user(None)

    def test_member_theme_is_available_to_server_art(self):
        set_request_theme_from_user(member('mosslight'))
        self.assertEqual(request_theme(), 'mosslight')

    def test_signed_out_request_clears_previous_member_theme(self):
        set_request_theme_from_user(member('mosslight'))
        set_request_theme_from_user(None)
        self.assertIsNone(request_theme())

    def test_missing_or_failed_preferences_do_not_reuse_previous_theme(self):
        class MissingPreferences:
            @property
            def preferences(self):
                raise RuntimeError('unavailable preference row')
        for user in (SimpleNamespace(), MissingPreferences(), member('')):
            set_request_theme_from_user(member('mosslight'))
            set_request_theme_from_user(user)
            self.assertIsNone(request_theme())

    def test_concurrent_members_keep_separate_themes(self):
        async def read(theme):
            set_request_theme_from_user(member(theme))
            await asyncio.sleep(0)
            return request_theme()
        async def check():
            return await asyncio.gather(read('mosslight'), read('signal-room'), read('default'))
        set_request_theme_from_user(None)
        self.assertEqual(asyncio.run(check()), ['mosslight','signal-room','default'])
        self.assertIsNone(request_theme())


if __name__ == '__main__':
    unittest.main()
