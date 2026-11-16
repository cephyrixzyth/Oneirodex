"""Pure controls for the full-library handoff probe; no native UI or server."""
import unittest
from unittest import mock

from probe_linux_packaged import ProbeFailure
import linux_library_window as library

BASE = 'http://127.0.0.1:6121'
PAGE = {'origin': BASE, 'path': '/login', 'query_or_fragment': '?next=%2Flibrary', 'ready': True,
        'native_secret_readable': False}


class FakeNative:
    session = '/session/fixture'

    def __init__(self, page=PAGE, extra_handles=('site',)):
        self.page, self.extra, self.current, self.open = page, list(extra_handles), 'main', False
        self.calls = []

    def request(self, method, suffix, payload=None):
        self.calls.append((method, suffix.rsplit('/', 1)[-1], payload))
        if suffix.endswith('/window/handles'):
            return ['main'] + (self.extra if self.open else [])
        if method == 'GET': return self.current
        if method == 'POST': self.current = payload['handle']; return None
        if method == 'DELETE': self.open = False; return None
        raise AssertionError(method)

    def execute_js(self, script, args=None):
        if script is library.CLICK_SCRIPT: self.open = True; return True
        return {'opened': self.open, 'error': False}

    def execute_async(self, script, args=None):
        if script is library.LABELS_SCRIPT: return ['main'] + ([library.LABEL] if self.open else [])
        return self.page


class LibraryWindowContracts(unittest.TestCase):
    def run_probe(self, native, token='PRIVATE-TOKEN'):
        progress = {}
        with mock.patch.object(library, 'wait_for', side_effect=lambda check, *_: check() or self.fail('not ready')):
            library.open_full_library(native, BASE, token, progress)
        return progress

    def test_inspected_site_window_is_verified_closed_and_main_restored(self):
        native = FakeNative()
        progress = self.run_probe(native)
        self.assertTrue(progress['full_library_handoff_verified'])
        checks = progress['full_library_checks']
        for key in ('native_window_created_with_site_label', 'site_window_is_server_origin',
                    'site_window_address_has_no_token', 'site_window_cannot_read_native_secret', 'site_window_closed'):
            self.assertTrue(checks[key], key)
        self.assertEqual(native.current, 'main')
        self.assertNotIn('PRIVATE-TOKEN', repr(progress))

    def test_window_without_a_driver_handle_is_created_but_not_claimed_as_inspected(self):
        progress = self.run_probe(FakeNative(extra_handles=()))
        self.assertFalse(progress['full_library_handoff_verified'])
        self.assertTrue(progress['full_library_checks']['native_window_created_with_site_label'])
        self.assertNotIn('site_window_is_server_origin', progress['full_library_checks'])

    def test_unsafe_site_pages_are_refused_and_main_window_is_restored(self):
        for change in ({'origin': 'http://127.0.0.1:9'}, {'path': '/api/search'},
                       {'query_or_fragment': '?token=PRIVATE-TOKEN'}, {'native_secret_readable': True},
                       {'ready': False}):
            with self.subTest(change=change):
                native = FakeNative(page={**PAGE, **change})
                with self.assertRaises((ProbeFailure, AssertionError)):
                    self.run_probe(native)
                self.assertEqual(native.current, 'main')

    def test_preexisting_window_or_reported_error_stops_before_any_claim(self):
        native = FakeNative(); native.open = True
        with self.assertRaises(ProbeFailure): self.run_probe(native)
        failing = FakeNative()
        failing.execute_js = lambda script, args=None: True if script is library.CLICK_SCRIPT else {'opened': False, 'error': True}
        with self.assertRaises(ProbeFailure): self.run_probe(failing)


if __name__ == '__main__': unittest.main()
