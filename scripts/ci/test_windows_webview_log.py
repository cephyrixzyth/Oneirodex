"""No browser launch: privacy and bounds for selected SDK log diagnostics."""
import hashlib
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import probe_windows_packaged as probe


class WebViewLogTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(callable(getattr(probe, 'safe_webview_log_summary', None)),
                        'SDK errors need a bounded static-category sanitizer')
        self.assertTrue(callable(getattr(probe, '_read_webview_log', None)))

    def test_log_summary_selects_static_categories_and_codes_without_paths_names_or_messages(self):
        data = (b'[1:2:0115/030405.001:ERROR:process_singleton_win.cc(492)] '
                b'CreateMutex failed. Access is denied. HRESULT=0x80070005 '
                b'PRIVATE C:\\Users\\PRIVATE\\profile https://PRIVATE/?token=PRIVATE\n'
                b'[1:2:0115/030405.002:WARNING:PRIVATE.cc(44)] PRIVATE SID=S-PRIVATE\n')
        result = probe.safe_webview_log_summary(data)
        self.assertEqual(result['hresult_codes'], ['0x80070005'])
        self.assertIn('profile_lock', result['matched_categories'])
        self.assertIn('access_denied', result['matched_categories'])
        self.assertEqual(result['severity_counts']['error'], 1)
        self.assertEqual(result['severity_counts']['warning'], 1)
        self.assertEqual(result['known_locations'], [{'component': 'process_singleton_win.cc',
                                                    'line': 492, 'severity': 'error'}])
        self.assertNotIn('PRIVATE', repr(result))
        self.assertNotIn('Users', repr(result))
        self.assertNotIn('CreateMutex', repr(result))

    def test_reader_hashes_a_bounded_prefix_and_does_not_scan_trailing_private_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = b'x' * (256 * 1024) + b' PRIVATE HRESULT=0x12345678'
            (Path(tmp) / 'webview-startup-1.log').write_bytes(data)
            result = probe._read_webview_log(Path(tmp), 1)
        self.assertTrue(result['truncated'])
        self.assertEqual(result['bytes_read'], 256 * 1024)
        self.assertEqual(result['prefix_sha256'], hashlib.sha256(data[:256 * 1024]).hexdigest())
        self.assertEqual(result['hresult_codes'], [])
        self.assertNotIn('PRIVATE', repr(result))

    def test_reader_rejects_reparse_files_before_opening_them(self):
        attributes = SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=0x400)
        with mock.patch.object(Path, 'lstat', return_value=attributes), \
             mock.patch.object(Path, 'open', side_effect=AssertionError('must not read reparse target')) as opened:
            result = probe._read_webview_log(Path('never-opened'), 1)
        self.assertEqual(result['observation'], 'rejected_reparse_or_nonregular')
        opened.assert_not_called()


if __name__ == '__main__':
    unittest.main()
