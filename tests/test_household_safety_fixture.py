"""Real PostgreSQL/filesystem checks for the shared P0-02 seed fixture."""
import asyncio
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI


@pytest.fixture
def household_loop():
    # Windows creates a private loopback socket pair for its event loop. Build
    # it before the fixture network boundary; no general loopback exception.
    with asyncio.Runner() as runner:
        runner.get_loop()
        yield runner


@pytest.fixture
def household(app, db_session, tmp_path, monkeypatch, household_loop):
    from tests.fixtures.household_safety import seed_household

    return seed_household(app, db_session, tmp_path, monkeypatch)


def test_household_has_real_roles_grants_scopes_and_persistent_identities(household, db_session):
    from oneirodex.models import ApiToken, PersistentLoginSession
    from oneirodex.runtime_native.emulator_mutations import EmulatorMutationData
    from oneirodex.utils.api_tokens import VALID_SCOPES
    from oneirodex.utils.persistent_sessions import validate_login_identity

    assert set(household.users) == {
        'member', 'disabled', 'child_none', 'child_some', 'librarian', 'admin',
    }
    assert set(household.bearers) == VALID_SCOPES | {'child_save'}
    assert db_session.query(ApiToken).filter(ApiToken.user_id.in_(
        [user.id for user in household.users.values()],
    )).count() == len(VALID_SCOPES) + 1
    assert db_session.query(PersistentLoginSession).filter(
        PersistentLoginSession.user_id.in_([user.id for user in household.users.values()]),
    ).count() == 6
    for name, user in household.users.items():
        assert validate_login_identity(
            household.identities[name], user, touch=False,
        ) is (name != 'disabled')
    assert household.users['disabled'].is_active is False
    data = EmulatorMutationData()
    assert data.can_access(household.users['child_none'], household.games['allowed']) is False
    assert data.can_access(household.users['child_some'], household.games['allowed']) is True
    assert data.can_access(household.users['child_some'], household.games['denied']) is False


def test_native_save_route_uses_real_child_acl_generation_and_scope_adapters(
    household, app, db_session, household_loop,
):
    from oneirodex.models import ApiToken, EmulatorSave, EmulatorSaveGeneration, User
    from oneirodex.runtime_native.emulator_mutations import create_emulator_mutations_router

    api = FastAPI()
    api.include_router(create_emulator_mutations_router(
        app,
        find_user=lambda user_id: db_session.get(User, user_id),
        find_token=lambda prefix: db_session.query(ApiToken).filter_by(token_prefix=prefix).first(),
        commit_token_touch=lambda token: db_session.commit(),
    ))

    async def upload(game, credential, payload):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=api), base_url='http://fixture.invalid',
        ) as client:
            return await client.post(
                f'/api/games/{game.uuid}/saves',
                headers={'Authorization': f'Bearer {credential}'},
                data={'slot': 'progress'}, files={'file': ('progress.state', payload)},
            )

    allowed = household_loop.run(upload(
        household.games['allowed'], household.bearers['child_save'], b'child-progress',
    ))
    assert allowed.status_code == 201
    child = household.users['child_some']
    saved = db_session.query(EmulatorSave).filter_by(user_id=child.id).one()
    assert Path(saved.storage_path).read_bytes() == b'child-progress'
    assert Path(saved.storage_path).resolve().is_relative_to(household.root.resolve())
    assert db_session.query(EmulatorSaveGeneration).filter_by(save_id=saved.id).count() == 0
    previous = Path(saved.storage_path)
    replaced = household_loop.run(upload(
        household.games['allowed'], household.bearers['child_save'], b'child-progress-two',
    ))
    assert replaced.status_code == 201
    db_session.expire_all()
    assert Path(saved.storage_path).read_bytes() == b'child-progress-two'
    assert previous.read_bytes() == b'child-progress'
    assert db_session.query(EmulatorSaveGeneration).filter_by(save_id=saved.id).count() == 1
    paths_before = {p: p.read_bytes() for p in household.root.rglob('*') if p.is_file()}

    denied = household_loop.run(upload(
        household.games['denied'], household.bearers['child_save'], b'forbidden',
    ))
    assert denied.status_code == 403
    read_only = household_loop.run(upload(
        household.games['allowed'], household.bearers['read:library'], b'forbidden',
    ))
    assert read_only.status_code == 403
    assert db_session.query(EmulatorSave).filter_by(user_id=child.id).count() == 1
    assert paths_before == {p: p.read_bytes() for p in household.root.rglob('*') if p.is_file()}
    assert household.legacy_path.read_bytes() == b'legacy-fixture'
    assert household.unrelated_path.read_bytes() == b'unrelated-fixture'
