"""Pure denied/outage shelf, ownership and generation safety controls."""
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from probe_linux_packaged import ProbeFailure
import linux_game_journey as game
import linux_connected_server as server

spec = importlib.util.find_spec('linux_offline_journey')
offline = __import__('linux_offline_journey') if spec else None


class OfflineContracts(unittest.TestCase):
    def test_unfinished_or_foreign_generation_cannot_be_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            value = game.GameFixture.__new__(game.GameFixture)
            value.root=Path(tmp).resolve(); value.cleaned=False; value.handles=[]
            helper=getattr(value,'reset',None)
            self.assertIsNotNone(helper,'owned generation reset must exist')
            with self.assertRaises(ProbeFailure): helper()
            value.cleaned=True; value.progress={'game_fixture_cleanup_verified':True}; value.nonce='a'*32
            (value.root/'next').write_text('foreign')
            with mock.patch.object(game.os,'geteuid',return_value=value.root.stat().st_uid,create=True):
                with self.assertRaises(ProbeFailure): helper()
            self.assertEqual((value.root/'next').read_text(),'foreign')

    def test_verified_generation_preserves_history_before_fresh_nonce(self):
        with tempfile.TemporaryDirectory() as tmp:
            value=game.GameFixture.__new__(game.GameFixture)
            value.root=Path(tmp).resolve(); value.cleaned=True; value.handles=[]; value.nonce='a'*32
            value.progress={'game_fixture_cleanup_verified':True}
            (value.root/'next').write_bytes((value.nonce+'\n').encode('ascii'))
            helper=getattr(value,'reset',None)
            self.assertIsNotNone(helper,'owned generation reset must exist')
            with mock.patch.object(game.os,'geteuid',return_value=value.root.stat().st_uid,create=True): helper()
            self.assertEqual((value.root/('next-history-'+'a'*32)).read_text(),'a'*32+'\n')
            self.assertNotEqual(value.nonce,'a'*32)
            self.assertFalse(value.progress['game_fixture_cleanup_verified'])

    def test_foreign_listener_refuses_outage_before_stop_or_database_actions(self):
        api=server.NativeServerAPI.__new__(server.NativeServerAPI)
        api.root=Path('PRIVATE'); api.port=6121; api.process=SimpleNamespace(pid=123); api.progress={}; api.stop=mock.Mock()
        helper=getattr(api,'stop_for_outage',None)
        self.assertIsNotNone(helper,'owned server outage operation must exist')
        with mock.patch.object(server,'require_backend_ci'), mock.patch('linux_packaged_native.listener_owned',return_value=False):
            with self.assertRaises(ProbeFailure): helper()
        api.stop.assert_not_called()

    def test_outage_requires_actual_port_closure_and_does_not_drop_database(self):
        api=server.NativeServerAPI.__new__(server.NativeServerAPI)
        api.root=Path('PRIVATE'); api.port=6121; api.process=SimpleNamespace(pid=123)
        api.progress={}; api.stop=mock.Mock(); api.drop=mock.Mock()
        with mock.patch.object(server,'require_backend_ci'), \
             mock.patch('linux_packaged_native.listener_owned',return_value=True), \
             mock.patch('linux_packaged_native.port_closed',return_value=True):
            api.stop_for_outage()
        api.stop.assert_called_once(); api.drop.assert_not_called()
        self.assertTrue(api.progress['backend_intentionally_stopped_for_outage'])

    def test_denied_shelf_requires_disclosure_enabled_local_actions_and_blocked_server_actions(self):
        self.assertIsNotNone(offline,'actual local-access flow must exist')
        native=mock.Mock(); progress={}
        state={key:True for key in offline.SHELF_FIELDS}
        state['mode_offline']=False; state['private_visible']=False; state['PRIVATE']='PRIVATE'
        native.execute_js.return_value=state
        offline.require_local_shelf(native,'game','denied',progress,'denied')
        self.assertTrue(progress['local_access_checks']['denied_verified_local_shelf'])
        for key in ('possession_disclosed','play_enabled','server_actions_blocked'):
            with self.subTest(key=key):
                native.execute_js.return_value={**state,key:False}; report={}
                with self.assertRaises(ProbeFailure): offline.require_local_shelf(native,'game','denied',report,'denied')
                self.assertNotIn('PRIVATE',repr(report))

    def _run_journey(self, **kwargs):
        import contextlib
        import linux_connected_journey as connected
        import linux_installed_journey as installed
        native=mock.Mock(); native.execute_js.return_value={'offline':True}
        fixture=mock.Mock(); fixture.private_data={'installed_fixture':{'game_uuid':'game','manifest':{}},
            'base_url':'PRIVATE','tokens':{'adult':'PRIVATE'},'ids':{'adult':1}}
        progress={}; control=mock.Mock(); calls=[]
        fixture.api.revoke.side_effect=lambda *_: calls.append('revoke')
        fixture.api.stop_for_outage.side_effect=lambda: calls.append('outage')
        with mock.patch.object(offline,'RevealContext') as context,              mock.patch.object(offline,'wait_for'),              mock.patch.object(offline,'require_local_shelf',side_effect=lambda *a: calls.append('shelf_'+a[4])),              mock.patch.object(offline,'install_record',return_value=(Path('entry'),Path('target'))),              mock.patch.object(offline,'play_local',side_effect=lambda *a: calls.append('play_'+a[4])),              mock.patch.object(connected,'ui_session',side_effect=lambda *a: contextlib.nullcontext()),              mock.patch.object(connected,'connect'),              mock.patch.object(installed,'check_native_install'):
            offline.run_offline_journey(native,fixture,progress,control,**kwargs)
        return context,progress,calls

    def test_default_journey_plays_under_denial_and_outage_without_file_manager(self):
        self.assertIsNotNone(offline,'actual local-access flow must exist')
        context,progress,calls=self._run_journey()
        context.assert_not_called()
        self.assertEqual(calls,['revoke','shelf_denied','play_denied','outage',
                                'shelf_outage_cold','shelf_outage_after_connect','play_offline'])
        self.assertTrue(progress['denial_outage_play_journey_verified'])
        self.assertNotIn('reveal_denial_outage_journey_verified',progress)
        self.assertIn('Reveal was not exercised',progress['local_access_scope'])

    def test_reveal_remains_selectable_and_claims_reveal_only_then(self):
        self.assertIsNotNone(offline,'actual local-access flow must exist')
        context,progress,calls=self._run_journey(reveal=True)
        manager=context.return_value
        manager.start.assert_called_once(); manager.close.assert_called_once()
        self.assertEqual([c.args[2] for c in manager.reveal.call_args_list],['online','denied','offline'])
        self.assertTrue(progress['denial_outage_play_journey_verified'])
        self.assertTrue(progress['reveal_denial_outage_journey_verified'])
        self.assertIn('genuine file-manager Reveal',progress['local_access_scope'])


if __name__ == '__main__': unittest.main()
