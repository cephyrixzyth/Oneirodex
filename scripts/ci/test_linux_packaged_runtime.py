"""Fake native APIs only; no local package/display/driver/app execution."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace

from probe_linux_packaged import ProbeFailure
spec=importlib.util.find_spec('linux_packaged_runtime')
runtime=__import__('linux_packaged_runtime') if spec else None


class FakeNative:
    def __init__(self, work, fail=None, foreign=False):
        self.data_root=work/'data';self.data_root.mkdir()
        self.directory=self.data_root/'app'/'installs';self.directory.mkdir(parents=True)
        self.fail,self.foreign,self.events=fail,foreign,[]
        self.marker_seen_after_uninstall=False
    def event(self,name):
        self.events.append(name)
        if name==self.fail:raise ProbeFailure('synthetic_'+name)
    def present(self):self.event('present');return self.foreign
    def install(self,deb):self.event('install')
    def verify_binary(self):self.event('verify_binary')
    def start_context(self):self.event('start_context')
    def round(self,number):
        self.event('round_'+str(number))
        return self.directory,{'bundled_renderer':True,'native_ipc':True,'parent_directory_denied':True,'ordinary_user':True,'listener_ownership_verified':True}
    def stop_round(self):self.event('stop_round')
    def stop_context(self):self.event('stop_context')
    def uninstall(self):
        self.event('uninstall');self.marker_seen_after_uninstall=bool(list(self.directory.glob('oneirodex-ci-*')))
    def absent(self):self.event('absent');return True


class LinuxRuntimeContracts(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(runtime,'real Linux runtime controller must have cleanup contracts first')
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.work=Path(self.tmp.name)

    def test_two_cold_rounds_uninstall_retention_and_all_cleanup_are_required(self):
        native=FakeNative(self.work);progress={}
        runtime.execute_probe(self.work/'never-executed.deb',self.work,progress,native=native)
        self.assertEqual(native.events,['present','install','verify_binary','start_context','round_1','stop_round','round_2','stop_round','stop_context','uninstall','absent'])
        self.assertTrue(progress['installed_runtime_acceptance']);self.assertTrue(progress['cleanup_verified'])
        self.assertTrue(native.marker_seen_after_uninstall);self.assertFalse(list(native.directory.iterdir()))
        self.assertEqual(len(progress['cold_rounds']),2)

    def test_foreign_package_is_never_installed_removed_or_context_started(self):
        native=FakeNative(self.work,foreign=True)
        with self.assertRaisesRegex(ProbeFailure,'foreign'):
            runtime.execute_probe(self.work/'never.deb',self.work,{},native=native)
        self.assertEqual(native.events,['present'])

    def test_partial_install_failure_is_cleaned_without_runtime_acceptance(self):
        native=FakeNative(self.work,fail='install');progress={}
        with self.assertRaisesRegex(ProbeFailure,'synthetic_install'):
            runtime.execute_probe(self.work/'never.deb',self.work,progress,native=native)
        self.assertIn('uninstall',native.events);self.assertTrue(progress['cleanup_verified'])
        self.assertFalse(progress['installed_runtime_acceptance'])

    def test_primary_ui_failure_survives_context_cleanup_failure_and_no_uninstall_with_live_children(self):
        native=FakeNative(self.work,fail='round_1');progress={}
        native.stop_context=mock.Mock(side_effect=ProbeFailure('synthetic_context_cleanup'))
        with self.assertRaisesRegex(ProbeFailure,'synthetic_round_1') as failed:
            runtime.execute_probe(self.work/'never.deb',self.work,progress,native=native)
        self.assertIn('linux_context_cleanup_failed',failed.exception.__notes__)
        self.assertFalse(progress['cleanup_verified']);self.assertNotIn('uninstall',native.events)

    def test_directory_outside_owned_data_is_rejected_and_native_check_failure_is_not_qualified(self):
        native=FakeNative(self.work);native.directory=self.work;progress={}
        with self.assertRaisesRegex(ProbeFailure,'directory_not_owned'):
            runtime.execute_probe(self.work/'never.deb',self.work,progress,native=native)
        self.assertFalse(progress['installed_runtime_acceptance']);self.assertTrue(progress['cleanup_verified'])

    def test_runtime_environment_excludes_credentials_and_unrelated_home(self):
        env=runtime.runtime_environment(self.work,{'PATH':'PRIVATE','GH_TOKEN':'PRIVATE','HOME':'PRIVATE','DISPLAY':'PRIVATE','DBUS_SESSION_BUS_ADDRESS':'PRIVATE'})
        self.assertNotIn('PRIVATE',repr(env));self.assertEqual(env['HOME'],str(self.work/'home'))
        self.assertEqual(env['XDG_DATA_HOME'],str(self.work/'data'))

    def test_group_cleanup_keeps_guardian_unreaped_until_other_members_stop(self):
        import linux_packaged_native as native
        events=[]
        process=mock.Mock(pid=123,returncode=None)
        process.wait.side_effect=lambda **kwargs: events.append('wait')
        api=native.NativeLinuxAPI.__new__(native.NativeLinuxAPI)
        with mock.patch.object(native,'process_group_members',side_effect=[[(123,'1')],[]]), \
             mock.patch.object(native.os,'killpg',side_effect=lambda *args:events.append('group_term'),create=True), \
             mock.patch.object(native.os,'kill',side_effect=lambda *args:events.append('guardian_finish')), \
             mock.patch.object(native,'signal',SimpleNamespace(SIGTERM=15,SIGKILL=9,SIGUSR1=10)):
            api.stop(process)
        self.assertEqual(events,['group_term','guardian_finish','wait'])
        process.poll.assert_not_called()

    def test_package_query_errors_cannot_be_treated_as_absence(self):
        import linux_packaged_native as native
        api=native.NativeLinuxAPI.__new__(native.NativeLinuxAPI)
        api.command=mock.Mock(return_value=SimpleNamespace(returncode=2))
        with self.assertRaisesRegex(ProbeFailure,'package_query_failed'):api.present()

    def test_listener_requires_loopback_socket_owned_by_same_uid_and_group(self):
        import linux_packaged_native as native
        proc=self.work/'proc';(proc/'net').mkdir(parents=True)
        pid=proc/'123';(pid/'fd').mkdir(parents=True)
        fields=['S','1','123','123']+['0']*15+['100']
        (pid/'stat').write_text('123 (driver with spaces) '+' '.join(fields))
        (pid/'fd'/'0').write_text('');(pid/'fd'/'1').write_text('')
        row='0: 0100007F:115C 00000000:0000 0A 0:0 0:0 0 1001 0 999\n'
        (proc/'net'/'tcp').write_text('header\n'+row);(proc/'net'/'tcp6').write_text('header\n')
        def route(value):
            value=str(value)
            return proc/value[6:] if value.startswith('/proc/') else proc if value=='/proc' else Path(value)
        def link(path):
            if path.name=='0':raise FileNotFoundError()
            return 'socket:[999]'
        with mock.patch.object(native,'Path',side_effect=route), \
             mock.patch.object(native.os,'geteuid',return_value=pid.stat().st_uid,create=True), \
             mock.patch.object(native.os,'readlink',side_effect=link):
            self.assertTrue(native.listener_owned(4444,123))
            (proc/'net'/'tcp').write_text('header\n'+row.replace('0100007F','00000000'))
            self.assertFalse(native.listener_owned(4444,123))
            (proc/'net'/'tcp').write_text('header\n'+row)
            self.assertFalse(native.listener_owned(4444,999))

    def test_reaped_group_leader_must_never_authorize_a_numeric_group_signal(self):
        import linux_packaged_native as native
        api=native.NativeLinuxAPI.__new__(native.NativeLinuxAPI)
        process=mock.Mock(pid=123,returncode=0)
        with mock.patch.object(native,'process_group_members',return_value=[(456,'9')]), \
             mock.patch.object(native.os,'killpg',create=True) as kill:
            with self.assertRaisesRegex(ProbeFailure,'already_reaped'):api.stop(process)
        kill.assert_not_called()


if __name__=='__main__':unittest.main()
