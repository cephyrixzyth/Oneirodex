"""Librarian unmatched-folder batch errors never expose DB diagnostics."""

import inspect
from types import SimpleNamespace

from flask import Flask

from oneirodex.routes_apis import scan_unmatched_edit


PRIVATE_ERROR = RuntimeError(
    'postgres://private-user:private-password@db/private-db'
)


class _Session:
    def __init__(self, folder):
        self.folder = folder

    def get(self, _model, _folder_id):
        return self.folder

    def delete(self, _folder):
        pass

    def add(self, _row):
        pass

    def commit(self):
        raise PRIVATE_ERROR

    def rollback(self):
        pass


def test_librarian_batch_errors_redact_database_details(monkeypatch):
    app = Flask(__name__)
    folder = SimpleNamespace(
        id='folder-1', folder_path='/library/Example', search_name=None,
        display_name=None, matched_game_uuid=None, match_reason=None,
        match_score=None, status='Unmatched',
    )
    monkeypatch.setattr(
        scan_unmatched_edit, 'db', SimpleNamespace(session=_Session(folder))
    )
    monkeypatch.setattr(
        scan_unmatched_edit, 'current_user',
        SimpleNamespace(id=9, name='Librarian'),
    )
    monkeypatch.setattr(scan_unmatched_edit, 'log_system_event', lambda *_a, **_k: None)
    monkeypatch.setattr(
        'oneirodex.utils.software_identify.mark_unmatched_as_kind',
        lambda *_args, **_kwargs: SimpleNamespace(
            uuid='game-1', name='Example', item_kind='utility'
        ),
    )

    cases = (
        (
            scan_unmatched_edit.batch_clear_unmatched_folders,
            '/unmatched_folders/batch/clear',
            {'ids': ['folder-1']},
            'Could not clear unmatched folder',
        ),
        (
            scan_unmatched_edit.batch_mark_unmatched_kind,
            '/unmatched_folders/batch/mark_kind',
            {'ids': ['folder-1'], 'item_kind': 'utility'},
            'Could not mark unmatched folder kind',
        ),
        (
            scan_unmatched_edit.batch_fix_unmatched_duplicates,
            '/unmatched_folders/batch/fix',
            {'ids': ['folder-1'], 'action': 'keep'},
            'Could not update duplicate match',
        ),
        (
            scan_unmatched_edit.batch_amend_unmatched_names,
            '/unmatched_folders/batch/amend',
            {'items': [{'id': 'folder-1', 'search_name': 'Example'}]},
            'Could not amend unmatched folder',
        ),
    )

    for handler, path, payload, expected_error in cases:
        with app.test_request_context(path, method='POST', json=payload):
            response = inspect.unwrap(handler)()
        if isinstance(response, tuple):
            response = response[0]
        body = response.get_json()
        assert body['results'][0]['error'] == expected_error
        text = response.get_data(as_text=True)
        assert 'private-password' not in text
        assert 'private-user' not in text
        assert 'postgres://' not in text

    def _raise_private_value_error(*_args, **_kwargs):
        raise ValueError(str(PRIVATE_ERROR))

    monkeypatch.setattr(
        'oneirodex.utils.software_identify.mark_unmatched_as_kind',
        _raise_private_value_error,
    )
    with app.test_request_context(
        '/unmatched_folders/batch/mark_kind', method='POST',
        json={'ids': ['folder-1'], 'item_kind': 'utility'},
    ):
        response = inspect.unwrap(scan_unmatched_edit.batch_mark_unmatched_kind)()
    if isinstance(response, tuple):
        response = response[0]
    text = response.get_data(as_text=True)
    assert response.get_json()['results'][0]['error'] == 'Could not mark unmatched folder kind'
    assert 'private-password' not in text
    assert 'private-user' not in text
    assert 'postgres://' not in text
