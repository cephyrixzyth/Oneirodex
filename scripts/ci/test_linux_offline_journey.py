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


if __name__ == '__main__': unittest.main()
