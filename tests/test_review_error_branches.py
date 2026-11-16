"""Regressions for error branches cited by the independent repository review."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from oneirodex.runtime_native import admin_art_studio_preview
from oneirodex.utils import scanning


def test_unmatched_integrity_error_rolls_back_before_best_effort_audit(monkeypatch):
    calls = []

    class Session:
        def execute(self, _statement):
            return Mock(scalar_one_or_none=lambda: None)

        def add(self, _row):
            calls.append('add')

        def commit(self):
            raise IntegrityError('insert unmatched folder', {}, Exception('duplicate'))

        def rollback(self):
            calls.append('rollback')

    monkeypatch.setattr(scanning, 'db', SimpleNamespace(session=Session()))
    from oneirodex.utils import event_logging

    monkeypatch.setattr(
        event_logging,
        'log_system_event',
        lambda *_args, **_kwargs: calls.append('log'),
    )

    scanning.log_unmatched_folder(
        'scan-id', '/library/game', 'Unmatched',
        match_reason='provided', suggested_kind='game',
        suggested_candidate_name='Game', stage_e_candidates=[], stage_e={},
    )

    assert calls == ['add', 'rollback', 'log']


def test_art_preview_validation_error_is_formatted_in_helper_scope():
    validation_error = ValidationError.from_exception_data(
        'Preview',
        [{'type': 'int_parsing', 'loc': ('width',), 'input': 'invalid'}],
    )

    class PreviewData:
        def render(self, **_kwargs):
            raise validation_error

    body = Mock(
        title='Game', system=None, width=400, height=600, format='webp',
        artistic=True, headline=None, subtitle=None, title_scale=None,
    )

    result, error = admin_art_studio_preview._render_preview(body, PreviewData())

    assert result is None
    assert isinstance(error, dict)
    assert error
