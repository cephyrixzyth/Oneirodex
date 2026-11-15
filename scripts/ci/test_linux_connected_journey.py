"""Private projections/control failures, never a native UI or server locally."""
import importlib.util
import unittest
from unittest import mock
from pathlib import Path
import tempfile
from types import SimpleNamespace

from probe_linux_packaged import ProbeFailure
spec=importlib.util.find_spec('linux_connected_journey')
journey=__import__('linux_connected_journey') if spec else None


class ConnectedJourneyContracts(unittest.TestCase):
    def setUp(self):self.assertIsNotNone(journey,'connected UI flow needs explicit projection/failure contracts')

    def test_secure_store_mismatch_cannot_be_marked_as_persistence_success(self):
        native=mock.Mock();native.execute_async.return_value={'secret_matches':False,'config_base_matches':True,'config_token_empty':True}
        report={}
        with self.assertRaisesRegex(ProbeFailure,'credential_check_failed'):
            journey.require_credentials(native,'PRIVATE','http://127.0.0.1:123',report,'persisted')
        self.assertNotIn('PRIVATE',repr(report));self.assertIsNot(report.get('connected_account_checks',{}).get('persisted'),True)

    def test_ui_failure_only_publishes_fixed_booleans_not_raw_state(self):
        native=mock.Mock();native.execute_js.side_effect=[None,{'online':False,'denied':False,'network_error':True,'PRIVATE':'PRIVATE'}]
        def once(check,seconds,code):
            if not check():raise ProbeFailure(code)
        report={}
        with mock.patch.object(journey,'wait_for',side_effect=once):
            with self.assertRaises(ProbeFailure):journey.connect(native,'http://127.0.0.1:123','PRIVATE','online',report,'valid')
        self.assertNotIn('PRIVATE',repr(report));self.assertTrue(report['failed_ui_snapshot']['network_error'])

    def test_owned_session_cleanup_keeps_original_ui_failure(self):
        native=mock.Mock();native.stop_round.side_effect=ProbeFailure('cleanup_failed')
        with self.assertRaisesRegex(ProbeFailure,'primary_ui_failed') as failed:
            with journey.ui_session(native,3):raise ProbeFailure('primary_ui_failed')
        native.stop_round.assert_called_once()
        self.assertIn('linux_connected_ui_cleanup_failed',failed.exception.__notes__)

    def test_fixed_protocol_category_survives_failure_without_raw_status(self):
        native=mock.Mock();native.execute_js.side_effect=[None,{'protocol_error':True,'PRIVATE':'PRIVATE'}]
        def once(check,seconds,code):
            if not check():raise ProbeFailure(code)
        report={}
        with mock.patch.object(journey,'wait_for',side_effect=once):
            with self.assertRaises(ProbeFailure):journey.connect(native,'http://127.0.0.1:123','PRIVATE','online',report,'valid')
        self.assertTrue(report['failed_ui_snapshot']['protocol_error'])
        self.assertNotIn('PRIVATE',repr(report))

    def test_failure_retains_fixed_request_stage_booleans_without_resource_urls(self):
        native=mock.Mock();native.execute_js.side_effect=[None,{'identity_requested':True,'search_requested':True,'PRIVATE':'PRIVATE'}]
        def once(check,seconds,code):
            if not check():raise ProbeFailure(code)
        report={}
        with mock.patch.object(journey,'wait_for',side_effect=once):
            with self.assertRaises(ProbeFailure):journey.connect(native,'http://127.0.0.1:123','PRIVATE','online',report,'valid')
        self.assertTrue(report['failed_ui_snapshot']['identity_requested'])
        self.assertTrue(report['failed_ui_snapshot']['search_requested'])
        self.assertNotIn('PRIVATE',repr(report))

    def test_transient_online_state_does_not_qualify_before_connect_finishes(self):
        native=mock.Mock();native.execute_js.side_effect=[None,{'online':True,'shared_visible':True,
            'private_visible':True,'connection_settled':False}]
        def once(check,seconds,code):
            if not check():raise ProbeFailure(code)
        report={}
        with mock.patch.object(journey,'wait_for',side_effect=once):
            with self.assertRaises(ProbeFailure):
                journey.connect(native,'http://127.0.0.1:123','PRIVATE','online',report,'valid',private_visible=True)
        self.assertIsNot(report.get('connected_account_checks',{}).get('valid'),True)

    def test_completed_online_state_qualifies_and_records_finalization(self):
        native=mock.Mock();native.execute_js.side_effect=[None,{'online':True,'shared_visible':True,
            'private_visible':True,'connection_settled':True}]
        def once(check,seconds,code):
            if not check():raise ProbeFailure(code)
        report={}
        with mock.patch.object(journey,'wait_for',side_effect=once):
            journey.connect(native,'http://127.0.0.1:123','PRIVATE','online',report,'valid',private_visible=True)
        self.assertTrue(report['connected_account_checks']['valid_connection_settled'])
        self.assertNotIn('failed_ui_snapshot',report);self.assertNotIn('PRIVATE',repr(report))

    def test_backend_cleanup_failure_cannot_leave_extended_acceptance_true(self):
        fixture=mock.Mock();fixture.close.side_effect=ProbeFailure('backend_cleanup_failed')
        def completed(deb,work,report,**kwargs):report['installed_runtime_acceptance']=True
        report={}
        with mock.patch.object(journey.ConnectedServer,'open',return_value=fixture), \
             mock.patch.object(journey,'execute_probe',side_effect=completed):
            with self.assertRaisesRegex(ProbeFailure,'backend_cleanup_failed'):
                journey.run_connected_package(Path('never.deb'),Path('PRIVATE'),report)
        self.assertFalse(report['installed_runtime_acceptance'])

    def test_plaintext_check_reads_real_app_data_config_not_unused_config_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp)/'data';app=data/'app';app.mkdir(parents=True)
            native=SimpleNamespace(data_root=data,app_directory=app)
            config=app/'config.json';config.write_text('{"token":"PRIVATE"}')
            with self.assertRaisesRegex(ProbeFailure,'plaintext'):
                journey.require_private_config(native,{'adult':'PRIVATE'},{},'check')
            config.write_text('{"token":null}')
            report={};journey.require_private_config(native,{'adult':'PRIVATE'},report,'check')
            self.assertTrue(report['connected_account_checks']['check'])


if __name__=='__main__':unittest.main()
