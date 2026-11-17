"""Small JSON stores on the library volume must survive a failed write and a second writer."""
import json
import multiprocessing
import os
from pathlib import Path

import pytest

from oneirodex.utils import json_file_store

ROOT = Path(__file__).resolve().parents[1]


def test_failed_write_keeps_the_previous_document(tmp_path, monkeypatch):
    target = tmp_path / 'user_1.json'
    json_file_store.write_json_atomic(str(target), {'records': [1, 2, 3]})

    def explode(payload, handle, **kwargs):
        handle.write('{"records": [')  # a torn document, as a crash mid-write leaves it
        raise OSError('disk full')

    monkeypatch.setattr(json_file_store.json, 'dump', explode)
    with pytest.raises(OSError):
        json_file_store.write_json_atomic(str(target), {'records': [9]})

    assert json.loads(target.read_text(encoding='utf-8')) == {'records': [1, 2, 3]}
    assert sorted(p.name for p in tmp_path.iterdir() if not p.name.startswith('.json-store')) == ['user_1.json']


def test_write_replaces_whole_document_and_keeps_readable_mode(tmp_path):
    target = tmp_path / 'pack.json'
    json_file_store.write_json_atomic(str(target), {'a': 1})
    json_file_store.write_json_atomic(str(target), {'b': 2}, trailing_newline=True)

    assert target.read_text(encoding='utf-8').endswith('}\n')
    assert json.loads(target.read_text(encoding='utf-8')) == {'b': 2}
    if os.name != 'nt':
        assert (target.stat().st_mode & 0o777) == 0o644


def _append_many(path, worker, count):
    for index in range(count):
        with json_file_store.locked(path):
            try:
                with open(path, 'r', encoding='utf-8') as handle:
                    items = json.load(handle)['items']
            except FileNotFoundError:
                items = []
            items.append(f'{worker}-{index}')
            json_file_store.write_json_atomic(path, {'items': items})


def test_writers_in_separate_processes_do_not_lose_each_others_updates(tmp_path):
    path = str(tmp_path / 'user_7.json')
    context = multiprocessing.get_context('spawn')
    workers = [context.Process(target=_append_many, args=(path, worker, 40)) for worker in range(4)]
    for process in workers:
        process.start()
    for process in workers:
        process.join(60)
        assert process.exitcode == 0

    with open(path, 'r', encoding='utf-8') as handle:
        items = json.load(handle)['items']
    assert len(items) == 160
    assert len(set(items)) == 160


def test_lock_is_reentrant_free_and_released_after_an_error(tmp_path):
    path = str(tmp_path / 'user_2.json')
    with pytest.raises(RuntimeError):
        with json_file_store.locked(path):
            raise RuntimeError('boom')
    # A leaked lock would make this block until the timeout.
    with json_file_store.locked(path, timeout=2):
        pass


STORES = (
    'oneirodex/utils/client_commands.py',
    'oneirodex/utils/client_lifecycle.py',
    'oneirodex/utils/wanted_updates.py',
    'oneirodex/utils/game_mods.py',
    'oneirodex/utils/match_proposal.py',
    'oneirodex/utils/preset_themes.py',
    'oneirodex/runtime_native/game_reads.py',
)


@pytest.mark.parametrize('relative', STORES)
def test_json_stores_write_through_the_shared_atomic_writer(relative):
    source = (ROOT / relative).read_text(encoding='utf-8')
    assert 'json.dump(' not in source, f'{relative} rewrites a JSON file in place'
    assert 'write_json_atomic(' in source


@pytest.mark.parametrize('relative', (
    'oneirodex/utils/client_commands.py',
    'oneirodex/utils/client_lifecycle.py',
    'oneirodex/utils/wanted_updates.py',
    'oneirodex/utils/game_mods.py',
))
def test_read_modify_write_stores_hold_the_process_shared_lock(relative):
    source = (ROOT / relative).read_text(encoding='utf-8')
    assert 'locked(' in source, f'{relative} updates a shared file without the process-shared lock'
