"""DB/UI-free contracts for the packaged Windows acceptance probe."""
import hashlib
import io
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest import mock
import zipfile
import contextlib
import probe_windows_packaged as probe

from probe_windows_packaged import (
    ProbeFailure, create_workspace, extract_installer, require_ci_execution,
    validate_source, verify_digest, listener_is_owned, runtime_environment, safe_process_diagnostic,
)

SOURCE = '6a03c6fbdadcdc8f585d0012b3a36879e408fa0b'
DIGEST = 'a' * 64
INSTALLER = 'Oneirodex_1.1.9_x64-setup.exe'


class PackageGuardTests(unittest.TestCase):
    def metadata(self):
        return ({'head_sha': SOURCE, 'head_branch': 'codex/release-v1.1.9',
                 'event': 'push', 'status': 'completed', 'conclusion': 'success'},
                [{'id': 123, 'name': 'oneirodex-full-windows', 'expired': False,
                  'digest': 'sha256:' + DIGEST, 'size_in_bytes': 200}])

    def test_only_the_expected_successful_push_artifact_is_selected(self):
        run, artifacts = self.metadata()
        self.assertEqual(validate_source(run, artifacts, SOURCE, DIGEST)['id'], 123)

    def test_wrong_source_branch_event_or_non_success_cannot_install(self):
        for key, value in [('head_sha', 'b' * 40), ('head_branch', 'main'),
                           ('event', 'pull_request'), ('status', 'in_progress'),
                           ('conclusion', 'failure')]:
            with self.subTest(key=key):
                run, artifacts = self.metadata()
                run[key] = value
                with self.assertRaises(ProbeFailure):
                    validate_source(run, artifacts, SOURCE, DIGEST)

    def test_wrong_flavor_expired_mismatched_oversized_or_ambiguous_artifacts_fail(self):
        for key, value in [('name', 'oneirodex-thin-windows'), ('expired', True),
                           ('digest', 'sha256:' + 'b' * 64), ('size_in_bytes', 100_000_000)]:
            with self.subTest(key=key):
                run, artifacts = self.metadata()
                artifacts[0][key] = value
                with self.assertRaises(ProbeFailure):
                    validate_source(run, artifacts, SOURCE, DIGEST)
        run, artifacts = self.metadata()
        with self.assertRaises(ProbeFailure):
            validate_source(run, artifacts + artifacts, SOURCE, DIGEST)

    def test_actual_archive_bytes_must_match_the_pinned_digest(self):
        data = b'owned fixture'
        verify_digest(data, hashlib.sha256(data).hexdigest())
        with self.assertRaises(ProbeFailure):
            verify_digest(data + b'corrupt', hashlib.sha256(data).hexdigest())

    def archive(self, names):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            for name in names:
                archive.writestr(name, b'owned fixture; never executed')
        return stream.getvalue()

    def test_one_regular_installer_is_written_without_extractall(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = extract_installer(self.archive([INSTALLER]), Path(tmp))
            self.assertEqual(path.name, INSTALLER)
            self.assertEqual(path.read_bytes(), b'owned fixture; never executed')

    def test_traversal_absolute_backslash_and_ambiguous_payloads_fail(self):
        cases = [['../' + INSTALLER], ['/' + INSTALLER], ['C:/' + INSTALLER],
                 ['folder\\' + INSTALLER], [INSTALLER, 'other/' + INSTALLER],
                 ['not-an-installer.txt']]
        with tempfile.TemporaryDirectory() as tmp:
            for names in cases:
                with self.subTest(names=names), self.assertRaises(ProbeFailure):
                    extract_installer(self.archive(names), Path(tmp))
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_symlink_payload_is_rejected(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            entry = zipfile.ZipInfo(INSTALLER)
            entry.create_system = 3
            entry.external_attr = 0o120777 << 16
            archive.writestr(entry, b'outside')
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ProbeFailure):
            extract_installer(stream.getvalue(), Path(tmp))

    def test_workspace_is_fresh_and_strictly_under_the_owned_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = create_workspace(root / 'owned', root)
            self.assertEqual(work, (root / 'owned').resolve())
            for path in [root, root / '..' / 'outside', work]:
                with self.subTest(path=path), self.assertRaises(ProbeFailure):
                    create_workspace(path, root)

    def test_execute_is_fenced_to_an_explicit_windows_github_runner(self):
        env = {'GITHUB_ACTIONS': 'true', 'RUNNER_OS': 'Windows',
               'GITHUB_REPOSITORY': 'cephyrixzyth/Oneirodex', 'GITHUB_RUN_ID': '123'}
        require_ci_execution('nt', env)
        for platform, values in [('posix', env), ('nt', {}), ('nt', {**env, 'RUNNER_OS': 'Linux'}),
                                 ('nt', {**env, 'GITHUB_REPOSITORY': 'other/repo'})]:
            with self.subTest(platform=platform, values=values), self.assertRaises(ProbeFailure):
                require_ci_execution(platform, values)

    def test_debug_endpoint_must_be_loopback_and_descended_from_the_live_app(self):
        self.assertTrue(listener_is_owned([{'address': '127.0.0.1', 'pid': 12}], {12: 11, 11: 10}, 10))
        self.assertTrue(listener_is_owned([{'address': '::1', 'pid': 11}], {11: 10}, 10))
        for listeners, parents in [([], {}), ([{'address': '0.0.0.0', 'pid': 11}], {11: 10}),
                                   ([{'address': '127.0.0.1', 'pid': 11}], {11: 9}),
                                   ([{'address': '127.0.0.1', 'pid': 11}], {11: 12, 12: 11})]:
            with self.subTest(listeners=listeners):
                self.assertFalse(listener_is_owned(listeners, parents, 10))

    def test_installer_and_app_environment_does_not_receive_ci_credentials(self):
        selected = runtime_environment({'SystemRoot': 'system', 'PATH': 'tools',
                                        'USERPROFILE': 'profile', 'GH_TOKEN': 'do-not-forward',
                                        'ACTIONS_RUNTIME_TOKEN': 'do-not-forward', 'DATABASE_URL': 'private'})
        self.assertEqual(selected, {'SystemRoot': 'system', 'PATH': 'tools', 'USERPROFILE': 'profile'})

    def test_runtime_failure_is_not_reported_as_a_successful_inspection(self):
        # Both installer paths are replaced: this fault test cannot launch an app.
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            argv = ['probe', '--source-run', '1', '--expected-source', SOURCE,
                    '--artifact-digest', DIGEST, '--work-dir', str(work), '--execute']
            output = io.StringIO()
            with mock.patch('sys.argv', argv), contextlib.redirect_stdout(output), \
                 mock.patch.object(probe, 'require_ci_execution'), \
                 mock.patch.object(probe, 'inspect_package', return_value=(work, work / 'never-run.exe', {})), \
                 mock.patch.object(probe, 'execute_cold_probe', side_effect=ProbeFailure('synthetic_runtime_failure')):
                code = probe.main()
            self.assertEqual(code, 1)
            self.assertEqual(__import__('json').loads(output.getvalue())['status'], 'failed')

    def test_failure_diagnostics_do_not_serialize_command_lines_or_paths(self):
        raw = {'pid': 12, 'parent': 10, 'name': 'msedgewebview2.exe',
               'command': 'browser --remote-debugging-port=1234 --user-data-dir=private/webview-profile SECRET-VALUE'}
        selected = safe_process_diagnostic(raw, 1234)
        self.assertTrue(selected['expected_debug_port_flag'])
        self.assertTrue(selected['probe_profile_flag'])
        self.assertNotIn('SECRET-VALUE', repr(selected))
        self.assertNotIn('private/', repr(selected))
        self.assertNotIn('command', selected)

    def test_browser_client_stop_failure_still_reaps_and_closes_the_owned_app(self):
        client = mock.Mock()
        client.chromium.connect_over_cdp.side_effect = ProbeFailure('synthetic_connect_failure')
        client.stop.side_effect = RuntimeError('synthetic_client_stop_failure')
        module = mock.Mock()
        module.sync_playwright.return_value.start.return_value = client
        process = mock.Mock(pid=123, security={'elevated': False, 'integrity_rid': 8192})
        process.poll.return_value = None
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.dict(probe.os.environ, {'GITHUB_ACTIONS': 'true', 'RUNNER_OS': 'Windows',
                 'GITHUB_REPOSITORY': 'cephyrixzyth/Oneirodex', 'GITHUB_RUN_ID': '123'}), \
             mock.patch.object(probe.subprocess, 'Popen', side_effect=AssertionError('unit must not spawn observer')) as observer_start, \
             mock.patch.object(probe, 'begin_startup_trace', return_value=None), \
             mock.patch.dict('sys.modules', {'playwright': mock.Mock(), 'playwright.sync_api': module}), \
             mock.patch.object(probe, 'start_standard_user', return_value=process), \
             mock.patch.object(probe, '_wait'), \
             mock.patch.object(probe, '_listener_snapshot', return_value=(
                 [{'address': '127.0.0.1', 'pid': 123}], {})), \
             mock.patch.object(probe, '_startup_diagnostics', return_value={'observation': 'synthetic'}):
            with self.assertRaisesRegex(RuntimeError, 'synthetic_client_stop_failure'):
                probe._cold_start(Path('never-executed.exe'), Path(tmp), 1, {})
        process.terminate.assert_called_once_with()
        process.wait.assert_called_once_with(timeout=20)
        process.close.assert_called_once_with()
        observer_start.assert_not_called()





    def test_native_initialization_summary_discards_raw_window_and_event_text(self):
        self.assertTrue(callable(getattr(probe, 'safe_native_initialization', None)))
        raw = {'window_count': 2, 'window_observation': 'complete',
               'keywords': ['WebView2', 'access', 'PRIVATE-UNKNOWN'],
               'hresult_codes': ['0x80070005', 'private/path', '0xABCDEF12'],
               'window_text': 'PRIVATE-TOKEN and private/path',
               'events': [{'event_id': 1000, 'application': 'msedgewebview2.exe',
                           'hresult_codes': ['0xc0000142'], 'message': 'PRIVATE-TOKEN',
                           'association': 'unproven-product-cause'}]}
        selected = probe.safe_native_initialization(raw)
        self.assertEqual(selected['keywords'], ['WebView2', 'access'])
        self.assertEqual(selected['hresult_codes'], ['0x80070005', '0xabcdef12'])
        self.assertEqual(selected['events'][0]['association'], 'name_and_time_only')
        self.assertNotIn('PRIVATE', repr(selected))
        self.assertNotIn('private/path', repr(selected))
        self.assertNotIn('message', repr(selected))
        self.assertNotIn('window_text', selected)

    def test_native_initialization_summary_is_bounded_and_rejects_foreign_records(self):
        self.assertTrue(callable(getattr(probe, 'safe_native_initialization', None)))
        valid = {'event_id': 1000, 'application': 'oneirodex-desktop.exe',
                 'hresult_codes': ['0x80070005'] * 100}
        raw = {'window_count': 999, 'window_observation': 'PRIVATE-VALUE',
               'keywords': ['error'] * 1000,
               'hresult_codes': ['0x80070005'] * 100,
               'events': [{'event_id': 9999, 'application': 'oneirodex-desktop.exe'},
                          {'event_id': 1000, 'application': 'foreign.exe'},
                          {'event_id': True, 'application': 'oneirodex-desktop.exe'},
                          *[valid] * 100]}
        selected = probe.safe_native_initialization(raw)
        self.assertEqual(selected['window_count'], 12)
        self.assertEqual(selected['window_observation'], 'unknown')
        self.assertEqual(selected['keywords'], ['error'])
        self.assertEqual(selected['hresult_codes'], ['0x80070005'])
        self.assertEqual(len(selected['events']), 12)
        self.assertTrue(all(e['event_id'] == 1000 and e['application'] == 'oneirodex-desktop.exe'
                            for e in selected['events']))



    def test_startup_trace_pairs_early_runtime_exit_and_does_not_reuse_an_old_pid(self):
        self.assertTrue(callable(getattr(probe, 'safe_startup_trace', None)))
        def event(kind, pid, parent, stamp, name='msedgewebview2.exe', exit_status=None):
            return {'kind': kind, 'pid': pid, 'parent': parent, 'time_created': str(stamp),
                    'name': name, 'exit_status': exit_status, 'command': 'PRIVATE-COMMAND'}
        raw = {'status': 'complete', 'dropped': 0, 'events': [
            event('start', 10, 1, 100, 'oneirodex-desktop.exe'),
            event('start', 11, 10, 110), event('stop', 11, 10, 120, exit_status='0xc0000142'),
            event('start', 11, 999, 130), event('stop', 11, 999, 140, exit_status='0x00000000'),
            event('stop', 10, 1, 210, 'oneirodex-desktop.exe', '0x00000001')]}
        selected = probe.safe_startup_trace(raw, 10, 200)
        self.assertTrue(selected['root_start_seen'])
        self.assertEqual(len(selected['parent_chain_events']), 4)
        self.assertEqual(len(selected['unattributed_events']), 2)
        stops = [e for e in selected['parent_chain_events'] if e['kind'] == 'stop']
        self.assertEqual(stops[0]['exit_status'], '0xc0000142')
        self.assertTrue(stops[0]['before_controller_cleanup'])
        self.assertFalse(stops[1]['before_controller_cleanup'])
        self.assertNotIn('PRIVATE', repr(selected))
        self.assertNotIn('command', repr(selected))

    def test_startup_trace_rejects_foreign_fields_and_does_not_promote_incomplete_capture(self):
        self.assertTrue(callable(getattr(probe, 'safe_startup_trace', None)))
        good = {'kind': 'start', 'pid': 10, 'parent': 1, 'time_created': '100',
                'name': 'oneirodex-desktop.exe', 'sid': 'PRIVATE', 'path': 'PRIVATE'}
        raw = {'status': 'deadline', 'dropped': 1, 'events': [
            {'kind': 'start', 'pid': 44, 'parent': 10, 'time_created': '90', 'name': 'foreign.exe'},
            good]}
        selected = probe.safe_startup_trace(raw, 10, 200)
        self.assertFalse(selected['capture_complete'])
        self.assertEqual(len(selected['parent_chain_events']), 1)
        self.assertNotIn('PRIVATE', repr(selected))
        self.assertTrue(all(isinstance(e['time_created'], str) for e in selected['parent_chain_events']))

    def test_startup_trace_constructor_refuses_local_execution(self):
        self.assertTrue(callable(getattr(probe, '_StartupProcessTrace', None)))
        with mock.patch.dict(probe.os.environ, {}, clear=True), mock.patch.object(probe.subprocess, 'Popen') as start:
            with self.assertRaisesRegex(ProbeFailure, 'execution_requires_disposable_windows_ci'):
                probe._StartupProcessTrace(Path('never-created'))
            start.assert_not_called()

    def test_startup_trace_setup_failure_reaps_only_its_observer_and_excludes_credentials(self):
        self.assertTrue(callable(getattr(probe, '_StartupProcessTrace', None)))
        observer = mock.Mock()
        observer.poll.return_value = None
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(probe, 'require_ci_execution'), \
             mock.patch.dict(probe.os.environ, {'GH_TOKEN': 'PRIVATE-CREDENTIAL'}), \
             mock.patch.object(probe.subprocess, 'Popen', return_value=observer) as start, \
             mock.patch.object(probe, '_wait', side_effect=ProbeFailure('synthetic_ready_failure')):
            with self.assertRaisesRegex(ProbeFailure, 'synthetic_ready_failure'):
                probe._StartupProcessTrace(Path(tmp))
        observer.terminate.assert_called_once_with()
        observer.wait.assert_called_once_with(timeout=10)
        self.assertNotIn('GH_TOKEN', start.call_args.kwargs['env'])

    def test_startup_trace_foreign_nonce_and_oversized_payload_are_not_reported(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            for content in [json.dumps({'nonce': 'wrong', 'message': 'PRIVATE'}), 'x' * 65537]:
                with self.subTest(size=len(content)):
                    trace = object.__new__(probe._StartupProcessTrace)
                    trace.nonce = 'owned'
                    trace.stop = Path(tmp) / 'stop'
                    trace.output = Path(tmp) / 'result.json'
                    trace.output.write_text(content, encoding='utf-8')
                    trace.process = mock.Mock()
                    trace.process.poll.return_value = 0
                    selected = trace.finish(10, 200)
                    self.assertEqual(selected['observation'], 'failed')
                    self.assertNotIn('PRIVATE', repr(selected))
                    trace.process.terminate.assert_not_called()
                    self.assertIn(mock.call(timeout=10), trace.process.wait.call_args_list)



    def test_startup_trace_timeout_reports_only_an_allowed_setup_stage(self):
        for raw, stage in [('start_subscription', 'start_subscription'), ('PRIVATE-STAGE', 'unknown')]:
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as tmp:
                observer = mock.Mock()
                observer.poll.return_value = None
                def fail_ready(*args):
                    (Path(tmp) / 'trace-stage-owned').write_text(raw, encoding='utf-8')
                    raise ProbeFailure('startup_trace_observer_not_ready')
                from types import SimpleNamespace
                with mock.patch.object(probe, 'require_ci_execution'), \
                     mock.patch.object(probe.uuid, 'uuid4', return_value=SimpleNamespace(hex='owned')), \
                     mock.patch.object(probe.subprocess, 'Popen', return_value=observer), \
                     mock.patch.object(probe, '_wait', side_effect=fail_ready):
                    with self.assertRaisesRegex(ProbeFailure, 'stage_' + stage):
                        probe._StartupProcessTrace(Path(tmp))
                observer.terminate.assert_called_once_with()




    @unittest.skipUnless(probe.os.name == 'nt' and probe.os.environ.get('GITHUB_ACTIONS') == 'true',
                         'Explicit disposable Windows CI prefix control')
    def test_native_observer_prefix_in_ci_without_subscribing_or_launching_the_app(self):
        probe.require_ci_execution(probe.os.name, probe.os.environ)
        import json
        results = []
        for label, env, child_input in [('observer', probe.observer_environment(probe.os.environ), None),
                                       ('inherited', dict(probe.os.environ), None)]:
            with tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp)
                nonce = 'owned-prefix-control'
                script = probe._STARTUP_TRACE_SCRIPT.split('try {', 1)[0]
                script += '\n[IO.File]::WriteAllText($ready,$nonce)\n'
                for key, value in [('READY_FILE', work / 'ready'), ('STOP_FILE', work / 'stop'),
                                   ('OUTPUT_FILE', work / 'output'), ('NONCE_VALUE', nonce),
                                   ('STAGE_FILE', work / 'stage')]:
                    script = script.replace(key, "'" + str(value).replace("'", "''") + "'")
                child = subprocess.Popen(
                    ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                    env=env, stdin=child_input, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                timed_out = False
                try:
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        timed_out = True
                    stage = (work / 'stage').read_text(encoding='utf-8-sig') if (work / 'stage').exists() else 'not_started'
                    results.append({'context': label, 'timed_out': timed_out,
                                    'stage': stage if stage in ('script_started', 'not_started') else 'unknown',
                                    'ready': (work / 'ready').exists()
                                    and (work / 'ready').read_text(encoding='utf-8-sig') == nonce})
                finally:
                    if child.poll() is None:
                        child.terminate()
                    child.wait(timeout=10)
        print('Native CLI prefix controls: ' + json.dumps(results))
        required = [result for result in results if result['context'] in ('observer', 'inherited')]
        self.assertEqual(len(required), 2)
        self.assertTrue(all(result['ready'] and not result['timed_out'] for result in required),
                        json.dumps(results))




    def test_observer_environment_preserves_module_discovery_without_ci_credentials(self):
        self.assertTrue(callable(getattr(probe, 'observer_environment', None)))
        env = {'SystemRoot': 'system', 'PSModulePath': 'configured-modules',
               'GH_TOKEN': 'PRIVATE', 'ACTIONS_RUNTIME_TOKEN': 'PRIVATE'}
        self.assertEqual(probe.observer_environment(env),
                         {'SystemRoot': 'system', 'PSModulePath': 'configured-modules'})
        self.assertNotIn('PSModulePath', probe.runtime_environment(env))




    @unittest.skipUnless(probe.os.name == 'nt' and probe.os.environ.get('GITHUB_ACTIONS') == 'true',
                         'Explicit disposable Windows CI provider control')
    def test_native_stop_delivery_for_short_and_long_lived_fixture_names(self):
        probe.require_ci_execution(probe.os.name, probe.os.environ)
        import json
        import shutil
        import sys
        script = r'''
$ErrorActionPreference='Stop'
$nonce=NONCE_VALUE;$original=ORIGINAL_EXE;$longFixture=LONG_EXE;$pythonHome=PYTHON_HOME
$currentTimeout=CURRENT_TIMEOUT
$where=" WHERE ProcessName='SHORT_NAME' OR ProcessName='oneirodex-trace-control.exe'"
$specs=@(
    @{label='start_current';class='Win32_ProcessStartTrace';suffix=$where;timeout=$currentTimeout;kind='start'},
    @{label='stop_current';class='Win32_ProcessStopTrace';suffix=CURRENT_STOP_SUFFIX;timeout=$currentTimeout;kind='stop'},
    @{label='stop_default';class='Win32_ProcessStopTrace';suffix=$where;timeout=$null;kind='stop'},
    @{label='stop_unfiltered';class='Win32_ProcessStopTrace';suffix='';timeout=$null;kind='stop'})
$result=@{error='none';fixture_exits=@{};sources=@{}}
$children=@();$watch=[Diagnostics.Stopwatch]::StartNew()
try {
    foreach($spec in $specs) {
        $settings=@{Namespace='root/cimv2';Query=('SELECT * FROM '+$spec.class+$spec.suffix);
            SourceIdentifier=($nonce+'-'+$spec.label);ErrorAction='Stop'}
        if($null -ne $spec.timeout){$settings.OperationTimeoutSec=[uint32]$spec.timeout}
        Register-CimIndicationEvent @settings | Out-Null
        $result.sources[$spec.label]=@{short=@{count=0;exact=0;prefix=0;empty=0;other=0;exit_codes=@()};
            long=@{count=0;exact=0;prefix=0;empty=0;other=0;exit_codes=@()};
            exception_events=0;query_hresult_codes=@();truncated=$false}
    }
    if($watch.Elapsed.TotalSeconds -gt 15){throw 'fixture_setup_deadline'}
    foreach($fixture in @(@{label='short';path=$original;exit=37},
                          @{label='long';path=$longFixture;exit=38})) {
        $info=[Diagnostics.ProcessStartInfo]::new()
        $info.FileName=$fixture.path
        $info.Arguments=('-c "import time;time.sleep(12);raise SystemExit('+[string]$fixture.exit+')"')
        $info.UseShellExecute=$false;$info.CreateNoWindow=$true
        $info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true
        $info.EnvironmentVariables['PYTHONHOME']=$pythonHome
        $info.EnvironmentVariables['PATH']=$pythonHome+';'+$env:PATH
        $child=[Diagnostics.Process]::new();$child.StartInfo=$info
        $child.Start()>$null
        $heldHandle=$child.Handle
        $children+=@(@{label=$fixture.label;process=$child;pid=$child.Id;
            expected_name=[IO.Path]::GetFileName($fixture.path).ToLowerInvariant()})
    }
    foreach($item in $children) {
        if(-not $item.process.WaitForExit(25000)){throw 'fixture_exit_deadline'}
        $result.fixture_exits[$item.label]=$item.process.ExitCode
    }
    $drain=[Diagnostics.Stopwatch]::StartNew()
    while($drain.Elapsed.TotalSeconds -lt 5) {
        foreach($spec in $specs) {
            $frames=@(Get-Event -SourceIdentifier ($nonce+'-'+$spec.label) -ErrorAction SilentlyContinue)
            if($frames.Count -gt 128){$result.sources[$spec.label].truncated=$true}
            foreach($frame in @($frames|Select-Object -First 128)) {
                $native=$frame.SourceEventArgs.NewEvent
                if($null -ne $native) {
                    foreach($item in $children) {
                        if([int]$native.ProcessID -ne $item.pid){continue}
                        $summary=$result.sources[$spec.label][$item.label]
                        $summary.count++
                        $name=([string]$native.ProcessName).ToLowerInvariant()
                        if(-not $summary.ContainsKey('name_lengths')){$summary.name_lengths=@()}
                        $summary.name_lengths+=@([int]$name.Length)
                        if($name -eq $item.expected_name){$summary.exact++}
                        elseif(-not $name){$summary.empty++}
                        elseif($item.expected_name.StartsWith($name)){$summary.prefix++}
                        else{$summary.other++}
                        if($spec.kind -eq 'stop' -and $null -ne $native.ExitStatus) {
                            $summary.exit_codes+=@(('0x{0:x8}' -f [uint32]$native.ExitStatus))
                        }
                    }
                } elseif($null -ne $frame.SourceEventArgs.Exception) {
                    $result.sources[$spec.label].exception_events++
                    $result.sources[$spec.label].query_hresult_codes+=@(
                        ('0x{0:x8}' -f $frame.SourceEventArgs.Exception.HResult))
                }
                Remove-Event -EventIdentifier $frame.EventIdentifier
            }
        }
        Start-Sleep -Milliseconds 100
    }
} catch {$result.error='provider_control_failed';$result.query_hresult=('0x{0:x8}' -f $_.Exception.HResult)}
finally {
    foreach($item in $children) {
        try {
            if(-not $item.process.HasExited){$item.process.Kill()}
            if(-not $item.process.WaitForExit(5000)){$result.fixture_cleanup_failed=$true}
        } catch {$result.fixture_cleanup_failed=$true}
        finally {$item.process.Dispose()}
    }
    foreach($spec in $specs) {
        Unregister-Event -SourceIdentifier ($nonce+'-'+$spec.label) -ErrorAction SilentlyContinue
        Remove-Event -SourceIdentifier ($nonce+'-'+$spec.label) -ErrorAction SilentlyContinue
    }
}
[Console]::WriteLine(($result|ConvertTo-Json -Depth 6 -Compress))
'''
        with tempfile.TemporaryDirectory() as tmp:
            original = Path(sys.executable).resolve()
            long_fixture = Path(tmp) / 'oneirodex-trace-control.exe'
            shutil.copyfile(original, long_fixture)
            self.assertEqual(long_fixture.read_bytes(), original.read_bytes())
            short_name = original.name.lower()
            self.assertRegex(short_name, r'^[a-z0-9_.-]{1,80}$')
            script = script.replace('SHORT_NAME', short_name)
            script = script.replace('CURRENT_TIMEOUT', str(probe.TRACE_OPERATION_TIMEOUT_SECONDS))
            script = script.replace('CURRENT_STOP_SUFFIX', '$where' if probe.TRACE_STOP_FILTER_BY_NAME else "''")
            for key, value in [('NONCE_VALUE', 'provider-' + probe.uuid.uuid4().hex),
                               ('ORIGINAL_EXE', original), ('LONG_EXE', long_fixture),
                               ('PYTHON_HOME', sys.prefix)]:
                script = script.replace(key, "'" + str(value).replace("'", "''") + "'")
            completed = subprocess.run(
                ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                env=probe.observer_environment(probe.os.environ), capture_output=True,
                encoding='utf-8', timeout=90, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.assertEqual(completed.returncode, 0, 'Native provider control did not complete')
            result = json.loads(completed.stdout)
        print('Native stop provider control: ' + json.dumps(result))
        self.assertEqual(result['error'], 'none', json.dumps(result))
        self.assertFalse(result.get('fixture_cleanup_failed', False), json.dumps(result))
        self.assertEqual(result['fixture_exits'], {'short': 37, 'long': 38})
        for label, status in [('short', '0x00000025'), ('long', '0x00000026')]:
            self.assertGreater(result['sources']['start_current'][label]['count'], 0, json.dumps(result))
            self.assertIn(status, result['sources']['stop_current'][label]['exit_codes'], json.dumps(result))
            native_names = result['sources']['stop_current'][label]
            if native_names['prefix']:
                self.assertTrue(all(length == probe.TRACE_STOP_NAME_PREFIX_LENGTH
                                    for length in native_names['name_lengths']), json.dumps(result))
            if label == 'short':
                self.assertIn(status, result['sources']['stop_default'][label]['exit_codes'], json.dumps(result))
            self.assertIn(status, result['sources']['stop_unfiltered'][label]['exit_codes'], json.dumps(result))




    def test_startup_trace_correlates_truncated_stop_name_only_to_a_live_start(self):
        raw = {'status': 'complete', 'dropped': 0, 'events': [
            {'kind': 'start', 'pid': 10, 'parent': 1, 'time_created': '100',
             'name': 'oneirodex-desktop.exe'},
            {'kind': 'start', 'pid': 11, 'parent': 10, 'time_created': '110',
             'name': 'msedgewebview2.exe'},
            {'kind': 'stop', 'pid': 11, 'parent': 10, 'time_created': '120',
             'name': 'msedgewebview2', 'exit_status': '0xc0000142'},
            {'kind': 'stop', 'pid': 12, 'parent': 999, 'time_created': '130',
             'name': 'PRIVATE-FOREIGN', 'exit_status': '0x00000000'}]}
        result = probe.safe_startup_trace(raw, 10, 200)
        self.assertEqual(len(result['parent_chain_events']), 3)
        stop = result['parent_chain_events'][-1]
        self.assertEqual(stop['name'], 'msedgewebview2.exe')
        self.assertEqual(stop['stop_name_match'], 'truncated')
        self.assertEqual(stop['exit_status'], '0xc0000142')
        self.assertNotIn('PRIVATE', repr(result))

    def test_startup_trace_subscription_errors_prevent_a_complete_capture_claim(self):
        raw = {'status': 'complete', 'dropped': 0, 'events': [],
               'subscription_errors': [{'kind': 'start', 'hresult': '0x80131500', 'message': 'PRIVATE'},
                                       {'kind': 'foreign', 'hresult': 'PRIVATE'}]}
        result = probe.safe_startup_trace(raw, 10, 200)
        self.assertFalse(result['capture_complete'])
        self.assertEqual(result['subscription_errors'], [{'kind': 'start', 'hresult': '0x80131500'}])
        self.assertNotIn('PRIVATE', repr(result))




    def test_unmatched_stop_for_an_active_lifetime_prevents_a_complete_capture_claim(self):
        raw = {'status': 'complete', 'dropped': 0, 'events': [
            {'kind': 'start', 'pid': 10, 'parent': 1, 'time_created': '100',
             'name': 'oneirodex-desktop.exe'},
            {'kind': 'stop', 'pid': 10, 'parent': 1, 'time_created': '110',
             'name': 'PRIVATE-FOREIGN', 'exit_status': '0x00000000'}]}
        result = probe.safe_startup_trace(raw, 10, 200)
        self.assertFalse(result['capture_complete'])
        self.assertEqual(result['unmatched_target_stops'], 1)
        self.assertNotIn('PRIVATE', repr(result))

    def test_rejected_stop_diagnostics_are_bounded_and_do_not_promote_identity(self):
        for parent, name, shape in [(999, 'msedgewebview2', 'prefix'),
                                     (10, 'msedgewebview2.', 'prefix'),
                                     (10, 'PRIVATE-FOREIGN', 'other')]:
            with self.subTest(parent=parent, shape=shape):
                raw = {'status': 'complete', 'dropped': 0, 'events': []}
                for pid in range(20, 40):
                    raw['events'].extend([
                        {'kind': 'start', 'pid': pid, 'parent': 10, 'time_created': str(pid * 10),
                         'name': 'msedgewebview2.exe'},
                        {'kind': 'stop', 'pid': pid, 'parent': parent, 'time_created': str(pid * 10 + 1),
                         'name': name, 'exit_status': '0xc0000142', 'private': 'PRIVATE'}])
                raw['events'].insert(0, {'kind': 'start', 'pid': 10, 'parent': 1,
                                         'time_created': '100', 'name': 'oneirodex-desktop.exe'})
                result = probe.safe_startup_trace(raw, 10, 1000)
                self.assertEqual(len(result.get('rejected_stop_diagnostics', [])), 12)
                rejected = result['rejected_stop_diagnostics'][0]
                self.assertEqual(rejected, {
                    'expected_name': 'msedgewebview2.exe', 'parent_matches': parent == 10,
                    'name_shape': shape, 'name_length': len(name), 'exit_status': '0xc0000142',
                    'before_controller_cleanup': True, 'association': 'rejected_stop_only'})
                self.assertFalse(result['capture_complete'])
                self.assertFalse(any(e['kind'] == 'stop' for e in result['parent_chain_events']))
                self.assertEqual(result['unmatched_target_stops'], 20)
                self.assertNotIn('PRIVATE', repr(result))


class StandardUserLaunchTests(unittest.TestCase):
    """No Win32 calls: verify suspended launch policy and owned-handle lifetime."""
    class API:
        def __init__(self, security=None, fail=None):
            self.security = security or {'elevated': False, 'integrity_rid': 8192}
            self.fail = fail
            self.events = []
            self.exited = False

        def restricted_token(self):
            self.events.append('restricted_token')
            return 'token'

        def create_suspended(self, token, executable, env):
            self.events.append('create_suspended')
            if self.fail == 'create':
                raise ProbeFailure('synthetic_create_failure')
            return 'process_handle', 'thread_handle', 123

        def process_security(self, handle):
            self.events.append(('security', handle))
            return self.security

        def resume(self, handle):
            self.events.append(('resume', handle))
            if self.fail == 'resume':
                raise ProbeFailure('synthetic_resume_failure')

        def terminate(self, handle):
            self.events.append(('terminate', handle))
            self.exited = True

        def wait(self, handle, milliseconds):
            self.events.append(('wait', handle, milliseconds))
            return self.exited

        def exit_code(self, handle):
            return 259  # A legitimate final exit code, not an "alive" assertion.

        def close_handle(self, handle):
            self.events.append(('close', handle))

    def setUp(self):
        self.assertTrue(callable(getattr(probe, '_start_standard_user', None)),
                        'A suspended, verified non-elevated launch path is required')

    def test_medium_non_elevated_token_is_checked_before_the_app_can_execute(self):
        api = self.API()
        process = probe._start_standard_user(Path('never-executed.exe'), {}, api)
        self.assertEqual(api.events, ['restricted_token', 'create_suspended', ('close', 'token'),
                                     ('security', 'process_handle'), ('resume', 'thread_handle'),
                                     ('close', 'thread_handle')])
        self.assertEqual(process.pid, 123)
        self.assertEqual(process.security, {'elevated': False, 'integrity_rid': 8192})
        process.close()

    def test_elevated_or_wrong_integrity_child_never_resumes_and_is_reaped(self):
        for state in [{'elevated': True, 'integrity_rid': 8192},
                      {'elevated': False, 'integrity_rid': 12288},
                      {'elevated': False, 'integrity_rid': 4096}]:
            with self.subTest(state=state):
                api = self.API(state)
                with self.assertRaisesRegex(ProbeFailure, 'child_not_standard_integrity'):
                    probe._start_standard_user(Path('never-executed.exe'), {}, api)
                self.assertNotIn(('resume', 'thread_handle'), api.events)
                self.assertIn(('terminate', 'process_handle'), api.events)
                self.assertIn(('wait', 'process_handle', 20000), api.events)
                for handle in ['token', 'process_handle', 'thread_handle']:
                    self.assertEqual(api.events.count(('close', handle)), 1)

    def test_failed_creation_closes_token_without_inventing_a_process_handle(self):
        api = self.API(fail='create')
        with self.assertRaisesRegex(ProbeFailure, 'synthetic_create_failure'):
            probe._start_standard_user(Path('never-executed.exe'), {}, api)
        self.assertEqual(api.events, ['restricted_token', 'create_suspended', ('close', 'token')])

    def test_failed_resume_terminates_only_the_retained_child_handle(self):
        api = self.API(fail='resume')
        with self.assertRaisesRegex(ProbeFailure, 'synthetic_resume_failure'):
            probe._start_standard_user(Path('never-executed.exe'), {}, api)
        self.assertIn(('terminate', 'process_handle'), api.events)
        for handle in ['token', 'process_handle', 'thread_handle']:
            self.assertEqual(api.events.count(('close', handle)), 1)

    def test_timeout_keeps_the_owned_handle_for_cleanup_and_final_259_is_an_exit(self):
        api = self.API()
        process = probe._start_standard_user(Path('never-executed.exe'), {}, api)
        self.assertIsNone(process.poll())
        with self.assertRaises(subprocess.TimeoutExpired):
            process.wait(timeout=1)
        self.assertNotIn(('close', 'process_handle'), api.events)
        process.terminate()
        self.assertEqual(process.poll(), 259)
        self.assertEqual(process.wait(timeout=1), 259)
        process.close()
        process.close()
        self.assertEqual(api.events.count(('close', 'process_handle')), 1)

    def test_native_factory_refuses_local_execution_before_loading_windows_api(self):
        with mock.patch.dict(probe.os.environ, {}, clear=True), \
             mock.patch.object(probe, '_WindowsStandardAPI') as native:
            with self.assertRaisesRegex(ProbeFailure, 'execution_requires_disposable_windows_ci'):
                probe.start_standard_user(Path('never-executed.exe'), {})
            native.assert_not_called()


    def test_native_launch_uses_same_user_restricted_token_api_without_handle_inheritance(self):
        import ctypes as c
        class Startup(c.Structure):
            _fields_ = [('cb', c.c_uint32)]
        class Info(c.Structure):
            _fields_ = [('hProcess', c.c_void_p), ('hThread', c.c_void_p),
                        ('dwProcessId', c.c_uint32)]
        api = object.__new__(probe._WindowsStandardAPI)
        api.c, api.STARTUPINFO, api.PROCESSINFO = c, Startup, Info
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / 'owned fixture with spaces.exe'
            executable.write_bytes(b'not executable; binding contract only')
            def create(*args):
                self.assertEqual(len(args), 11, 'Use CreateProcessAsUserW for our restricted primary token')
                self.assertEqual(args[0], 'owned_token')
                self.assertEqual(args[1], str(executable.resolve()))
                self.assertTrue(args[2].value.startswith('"'))
                self.assertEqual(args[3:6], (None, None, False))
                self.assertEqual(args[6], 0x404)
                self.assertEqual(''.join(args[7]).rstrip('\0'), 'APPDATA=owned-profile')
                self.assertEqual(args[8], str(executable.resolve().parent))
                info = args[10]._obj
                info.hProcess, info.hThread, info.dwProcessId = 111, 112, 113
                return True
            api._create = create
            self.assertEqual(api.create_suspended('owned_token', executable, {'APPDATA': 'owned-profile'}),
                             (111, 112, 113))


    def test_unicode_environment_has_a_double_terminator_and_no_ambiguous_keys(self):
        block = probe.windows_environment_block({'z': 'last', 'APPDATA': 'owned-é'})
        self.assertEqual(block, 'APPDATA=owned-é\0z=last\0\0')
        for env in [{'A': 'one', 'a': 'two'}, {'bad=key': 'value'},
                    {'key': 'bad\0value'}, {'': 'value'}, {'key': 42}]:
            with self.subTest(env=env), self.assertRaises(ProbeFailure):
                probe.windows_environment_block(env)


if __name__ == '__main__':
    unittest.main()
