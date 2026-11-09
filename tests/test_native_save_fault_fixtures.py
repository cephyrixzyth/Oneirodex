"""P0-02: real native save authority/storage with test-only failure seams."""
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

# Imports register the shared, explicitly guarded PostgreSQL fixtures.
from tests.fixtures.household_safety import household, household_loop


@pytest.mark.parametrize('operation', ['write', 'file_fsync', 'replace', 'directory_fsync', 'commit'])
def test_native_save_failure_preserves_committed_progress_and_allows_retry(
    household, household_loop, app, db_session, monkeypatch, operation,
):
    from tests.fixtures.faults import fail_next_save_io
    from oneirodex.models import ApiToken, EmulatorSave, EmulatorSaveGeneration, User
    from oneirodex.runtime_native.emulator_mutations import create_emulator_mutations_router
    from oneirodex.utils.emulator_saves import audit_save_storage

    api = FastAPI()
    api.include_router(create_emulator_mutations_router(
        app, find_user=lambda user_id: db_session.get(User, user_id),
        find_token=lambda prefix: db_session.query(ApiToken).filter_by(token_prefix=prefix).first(),
        commit_token_touch=lambda token: db_session.commit(),
    ))
    child = household.users['child_some']
    game = household.games['allowed']

    async def upload(payload):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api), base_url='http://fixture.invalid',
        ) as client:
            return await client.post(
                f'/api/games/{game.uuid}/saves',
                headers={'Authorization': f"Bearer {household.bearers['child_save']}"},
                data={'slot': 'progress'}, files={'file': ('progress.state', payload)},
            )

    assert household_loop.run(upload(b'committed-progress')).status_code == 201
    saved = db_session.query(EmulatorSave).filter_by(user_id=child.id).one()
    saved_id = saved.id
    previous_path = Path(saved.storage_path)
    with fail_next_save_io(monkeypatch, operation, session=db_session()) as fault:
        failed = household_loop.run(upload(b'failed-progress'))
    assert fault.hits == 1
    assert failed.status_code == 500
    assert failed.json()['error_code'] == 'internal'
    assert 'synthetic-private-canary' not in failed.text
    assert str(previous_path) not in failed.text
    db_session.expire_all()
    unchanged = db_session.get(EmulatorSave, saved_id)
    assert unchanged.storage_path == str(previous_path)
    assert unchanged.revision == 1
    assert previous_path.read_bytes() == b'committed-progress'
    assert db_session.query(EmulatorSaveGeneration).filter_by(save_id=saved_id).count() == 0
    audit = audit_save_storage(db_session, household.root)
    assert audit['complete'] is True
    assert audit['unreferenced_files'] == (1 if operation in {'directory_fsync', 'commit'} else 0)
    assert audit['mutated_files'] is False

    retried = household_loop.run(upload(b'retried-progress'))
    assert retried.status_code == 201
    db_session.expire_all()
    current = db_session.get(EmulatorSave, saved_id)
    history = db_session.query(EmulatorSaveGeneration).filter_by(save_id=saved_id).one()
    assert current.revision == 2
    assert Path(current.storage_path).read_bytes() == b'retried-progress'
    assert history.storage_path == str(previous_path)
    assert previous_path.read_bytes() == b'committed-progress'
    assert household.legacy_path.read_bytes() == b'legacy-fixture'
    assert household.unrelated_path.read_bytes() == b'unrelated-fixture'
