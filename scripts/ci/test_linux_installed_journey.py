"""Archive/file and UI projection controls; never execute a payload locally."""
import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import zipfile

from probe_linux_packaged import ProbeFailure

spec = importlib.util.find_spec('linux_installed_journey')
installed = __import__('linux_installed_journey') if spec else None


class InstalledArchiveContracts(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(installed, 'installed archive verification must exist')

    def test_archive_is_deterministic_bounded_and_has_exact_members_and_modes(self):
        first, manifest = installed.fixture_archive()
        second, _ = installed.fixture_archive()
        self.assertEqual(first, second)
        self.assertLess(len(first), 8192)
        self.assertEqual(hashlib.sha256(first).hexdigest(), manifest['archive_sha256'])
        with zipfile.ZipFile(io.BytesIO(first)) as archive:
            self.assertEqual(set(archive.namelist()), set(manifest['members']))
            for name, item in manifest['members'].items():
                self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), item['sha256'])
                self.assertEqual((archive.getinfo(name).external_attr >> 16) & 0o777, item['mode'])

    def fixture(self, root):
        root = root.resolve(strict=True)
        data, manifest = installed.fixture_archive()
        app = root/'app'; downloads = app/'downloads'; target = app/'installs'/'game'
        downloads.mkdir(parents=True); target.mkdir(parents=True)
        archive = downloads/'game.zip'; archive.write_bytes(data)
        with zipfile.ZipFile(io.BytesIO(data)) as source:
            for name in source.namelist():
                path = target/name; path.write_bytes(source.read(name))
                path.chmod(manifest['members'][name]['mode'])
        return app, {'archive_path': str(archive), 'extract_path': str(target),
                     'exe_path': str(target/'synthetic-game.sh')}, manifest

    def test_changed_downloaded_or_extracted_bytes_cannot_qualify(self):
        for which in ('archive_path', 'exe_path'):
            with self.subTest(which=which), tempfile.TemporaryDirectory() as tmp:
                app, record, manifest = self.fixture(Path(tmp))
                Path(record[which]).write_bytes(b'wrong')
                with self.assertRaises(ProbeFailure):
                    installed.verify_install_files(app, record, manifest, require_unix_mode=False)

    def test_foreign_archive_and_extra_file_cannot_qualify(self):
        for which in ('foreign', 'extra'):
            with self.subTest(which=which), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); app, record, manifest = self.fixture(root)
                if which == 'foreign':
                    foreign = root/'foreign.zip'
                    foreign.write_bytes(Path(record['archive_path']).read_bytes())
                    record['archive_path'] = str(foreign)
                else:
                    (Path(record['extract_path'])/'unexpected.txt').write_text('foreign')
                with self.assertRaises(ProbeFailure):
                    installed.verify_install_files(app, record, manifest, require_unix_mode=False)

    def test_correct_files_qualify_without_executing_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, record, manifest = self.fixture(Path(tmp))
            with mock.patch('subprocess.Popen', side_effect=AssertionError('no execution')):
                result = installed.verify_install_files(app, record, manifest, require_unix_mode=False)
            self.assertEqual(result, {'archive_hash_verified': True, 'member_hashes_verified': True,
                                      'selected_executable_verified': True, 'member_count': 2,
                                      'unix_modes_verified': False})

    def test_unsafe_member_or_symlink_metadata_is_rejected_before_file_read(self):
        for member in ('../foreign', '/foreign', 'nested/foreign'):
            with self.subTest(member=member), tempfile.TemporaryDirectory() as tmp:
                app, record, manifest = self.fixture(Path(tmp))
                manifest['members'] = {member: next(iter(manifest['members'].values()))}
                with self.assertRaises(ProbeFailure):
                    installed.verify_install_files(app, record, manifest, require_unix_mode=False)

    def test_native_validation_rejects_missing_executable_mode_and_symlink_metadata(self):
        for which in ('mode', 'symlink'):
            with self.subTest(which=which), tempfile.TemporaryDirectory() as tmp:
                app, record, manifest = self.fixture(Path(tmp))
                exe = Path(record['exe_path'])
                original_stat = Path.stat
                def metadata(path, *args, **kwargs):
                    value = original_stat(path, *args, **kwargs)
                    if path == exe:
                        return SimpleNamespace(st_size=value.st_size, st_mode=(0o100644 if which == 'mode' else 0o120777))
                    return value
                with mock.patch.object(Path, 'stat', metadata):
                    with self.assertRaises(ProbeFailure):
                        installed.verify_install_files(app, record, manifest)

    def test_fixture_write_refuses_collision_and_preserves_existing_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(strict=True)
            path, manifest = installed.write_fixture_archive(root)
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), manifest['archive_sha256'])
            path.write_bytes(b'foreign')
            with self.assertRaises(FileExistsError):
                installed.write_fixture_archive(root)
            self.assertEqual(path.read_bytes(), b'foreign')

    def test_native_record_missing_or_wrong_executable_cannot_qualify(self):
        with tempfile.TemporaryDirectory() as tmp:
            app, record, manifest = self.fixture(Path(tmp))
            with self.assertRaises(ProbeFailure):
                installed.verify_install_files(app, None, manifest, require_unix_mode=False)
            record['exe_path'] = str(Path(record['extract_path'])/'README.txt')
            with self.assertRaises(ProbeFailure):
                installed.verify_install_files(app, record, manifest, require_unix_mode=False)

    def test_synthetic_archive_is_created_only_in_guarded_marked_seed(self):
        import ast
        import linux_connected_server as server
        tree = ast.parse(Path(server.__file__).read_text())
        seed = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'seed_native_fixture')
        calls = [node for node in ast.walk(seed) if isinstance(node, ast.Call)]
        fence = next(node.lineno for node in calls if isinstance(node.func, ast.Name) and node.func.id == 'require_backend_ci')
        write = next(node.lineno for node in calls if isinstance(node.func, ast.Name) and node.func.id == 'write_fixture_archive')
        source = Path(server.__file__).read_text()
        marker_refusal = next(node.lineno for node in ast.walk(seed) if isinstance(node, ast.Raise)
                              and 'linux_seed_database_marker_mismatch' in ast.get_source_segment(source, node))
        self.assertLess(fence, marker_refusal)
        self.assertLess(marker_refusal, write)

    def test_install_failure_revokes_acceptance_after_account_flow_and_closes_backend(self):
        import linux_connected_journey as connected
        fixture = mock.Mock()
        report = {}
        def real_callback(deb, work, progress, journey):
            progress['installed_runtime_acceptance'] = True
            journey(mock.Mock(), progress)
        with mock.patch.object(connected.ConnectedServer, 'open', return_value=fixture), \
             mock.patch.object(connected, 'execute_probe', side_effect=real_callback), \
             mock.patch.object(connected, 'run_connected_journey') as account, \
             mock.patch.object(installed, 'run_installed_journey', side_effect=ProbeFailure('synthetic_install_failed')):
            with self.assertRaisesRegex(ProbeFailure, 'synthetic_install_failed'):
                connected.run_connected_package(Path('never.deb'), Path('PRIVATE'), report)
        account.assert_called_once()
        fixture.close.assert_called_once()
        self.assertFalse(report['installed_runtime_acceptance'])

    def test_failed_ui_action_reports_only_allowlisted_booleans(self):
        native = mock.Mock()
        native.execute_js.side_effect = [True, {'state_downloaded': False, 'status_error': True, 'PRIVATE': 'PRIVATE'}]
        report = {}
        def once(check, seconds, code):
            if not check():
                raise ProbeFailure(code)
        with mock.patch.object(installed, 'wait_for', side_effect=once):
            with self.assertRaises(ProbeFailure):
                installed.ui_action(native, 'private-game-id', 'download', 'state_downloaded', report)
        self.assertEqual(report['failed_install_ui_snapshot']['status_error'], True)
        self.assertNotIn('PRIVATE', repr(report))
        self.assertNotIn('private-game-id', repr(report))


if __name__ == '__main__':
    unittest.main()
