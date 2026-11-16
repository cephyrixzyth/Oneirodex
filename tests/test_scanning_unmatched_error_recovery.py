from __future__ import annotations

from sqlalchemy import select, text

from oneirodex.models import SystemEvents, UnmatchedFolder
from oneirodex.utils.scanning import log_unmatched_folder


def test_integrity_error_rolls_back_before_audit_event_commit(app, db_session):
    folder_path = '/synthetic-scan-root/integrity-failure'
    constraint_name = 'test_unmatched_folder_forced_integrity_error'
    db_session.execute(text(
        'ALTER TABLE unmatched_folders '
        f"ADD CONSTRAINT {constraint_name} CHECK (folder_path <> '{folder_path}')"
    ))

    with app.app_context():
        log_unmatched_folder(None, folder_path, 'Unmatched')

    assert db_session.execute(
        select(UnmatchedFolder).filter_by(folder_path=folder_path)
    ).scalars().first() is None
    event = db_session.execute(
        select(SystemEvents)
        .filter_by(event_type='scan', event_level='warning')
        .order_by(SystemEvents.id.desc())
    ).scalars().first()
    assert event is not None
    assert folder_path in event.event_text

