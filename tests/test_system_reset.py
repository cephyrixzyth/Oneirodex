"""Tests for the scoped admin factory reset.

The load-bearing assertion here is the coverage one: every table in the model
metadata must belong to exactly one scope. A reset feature fails quietly — you
only find out it missed a table when stale rows resurface long after the reset —
so the guard has to be structural rather than a list someone remembers to
update.
"""

from uuid import uuid4

import pytest

from oneirodex import db
from oneirodex.models import User
from oneirodex.utils.system_reset import (
    RESET_SCOPES,
    PRESERVED_RESET_TABLES,
    SCOPE_IMPLIES,
    expand_scopes,
    plan_reset,
)


def test_every_table_has_exactly_one_reset_or_preservation_policy():
    """New models need an explicit policy; preservation cannot hide unknowns."""
    import oneirodex.models  # noqa: F401  — populates db.metadata

    all_tables = {table.name for table in db.metadata.sorted_tables}
    # NativeSessionProbe is declared by test_native_db_session for its isolated
    # SQLite fixture and is not an application table or migration target.
    all_tables.discard('native_session_probe')

    seen: set[str] = set()
    duplicated: list[str] = []
    for tables in RESET_SCOPES.values():
        for name in tables:
            if name in seen:
                duplicated.append(name)
            seen.add(name)

    assert not duplicated, f'tables listed in two scopes: {sorted(set(duplicated))}'
    assert PRESERVED_RESET_TABLES == {'user_deletion_file_jobs'}
    assert seen.isdisjoint(PRESERVED_RESET_TABLES)
    covered = seen | PRESERVED_RESET_TABLES
    assert not (all_tables - covered), (
        'tables missing a reset/preservation policy: '
        f'{sorted(all_tables - covered)}'
    )
    assert not (covered - all_tables), (
        f'reset policy names tables that do not exist: {sorted(covered - all_tables)}'
    )


def test_clearing_libraries_implies_clearing_the_catalog():
    """A library row cannot go while its games still point at it."""
    assert 'catalog' in SCOPE_IMPLIES['libraries']
    assert expand_scopes(['libraries']) == ['catalog', 'libraries']


def test_unknown_scopes_are_dropped_not_raised():
    assert expand_scopes(['catalog', 'nonsense']) == ['catalog']
    assert expand_scopes([]) == []


def test_user_reset_explicitly_covers_save_history_and_login_sessions():
    assert {'emulator_save_generations', 'persistent_login_sessions'} <= set(RESET_SCOPES['users'])


def test_reset_refuses_a_cascade_into_committed_file_cleanup(monkeypatch):
    from oneirodex.utils import system_reset

    monkeypatch.setattr(system_reset, '_cascade_closure', lambda tables: [
        *tables, 'user_deletion_file_jobs',
    ])
    with pytest.raises(ValueError, match='preserved'):
        plan_reset(['users'])


def test_plan_reports_cascaded_tables_beyond_those_named(app):
    """The plan must not understate what TRUNCATE CASCADE will empty."""
    with app.app_context():
        plan = plan_reset(['libraries'])

    assert plan['touches_files'] is False
    assert 'libraries' in plan['tables']
    # Everything named is counted, plus anything reached by foreign key.
    assert plan['table_count'] >= len(plan['tables'])
    assert set(plan['cascaded']).isdisjoint(plan['tables'])


def test_plan_matches_what_postgres_will_actually_truncate(app, db_session):
    """The preview must never understate the damage.

    `plan_reset` walks SQLAlchemy metadata to work out what TRUNCATE CASCADE
    will reach. The confirm dialog is built from that walk, so if it comes back
    short the operator types the phrase against a list that is missing tables
    they are about to lose — the one failure this feature cannot afford.

    Asserted against the database's own view of the foreign-key graph rather
    than against a hand-written expectation, so a schema change that adds a
    relationship is caught here instead of in production.
    """
    from sqlalchemy import text

    pg_closure = """
    WITH RECURSIVE deps AS (
      SELECT unnest(CAST(:names AS text[])) AS t
      UNION
      SELECT c.conrelid::regclass::text
      FROM pg_constraint c JOIN deps d ON c.confrelid::regclass::text = d.t
      WHERE c.contype = 'f'
    )
    SELECT t FROM deps
    """

    with app.app_context():
        for scopes in (['catalog'], ['libraries'], ['users'], ['settings'], list(RESET_SCOPES)):
            plan = plan_reset(scopes)
            predicted = set(plan['tables']) | set(plan['cascaded'])
            assert predicted.isdisjoint(PRESERVED_RESET_TABLES)

            actual = set(
                db_session.execute(
                    text(pg_closure), {'names': list(plan['tables'])}
                ).scalars().all()
            )

            assert not (actual - predicted), (
                f'plan for {scopes} under-reports — Postgres would also truncate '
                f'{sorted(actual - predicted)}'
            )


def test_plan_changes_nothing(app, db_session):
    """Previewing a reset is not a reset."""
    from oneirodex.models import Library
    from oneirodex.platform import LibraryPlatform

    with app.app_context():
        library = Library(name='PlanOnly', platform=LibraryPlatform.PCWIN)
        db_session.add(library)
        db_session.commit()
        uuid = library.uuid

        plan_reset(['catalog', 'libraries', 'users', 'settings'])

        assert db_session.get(Library, uuid) is not None


class TestResetApi:
    @pytest.fixture
    def admin_user(self, db_session):
        unique = uuid4().hex[:8]
        admin = User(
            user_id=str(uuid4()),
            name=f'ResetAdmin_{unique}',
            email=f'reset_admin_{unique}@test.com',
            role='admin',
            is_email_verified=True,
        )
        admin.set_password('testpass123')
        db_session.add(admin)
        db_session.commit()
        return admin

    @pytest.fixture
    def regular_user(self, db_session):
        unique = uuid4().hex[:8]
        user = User(
            user_id=str(uuid4()),
            name=f'ResetUser_{unique}',
            email=f'reset_user_{unique}@test.com',
            role='user',
            is_email_verified=True,
        )
        user.set_password('testpass123')
        db_session.add(user)
        db_session.commit()
        return user

    @pytest.fixture
    def admin_client(self, client, admin_user):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(admin_user.id)
            sess['_fresh'] = True
        return client

    def test_reset_requires_a_scope(self, admin_client):
        response = admin_client.post('/admin/api/system/reset', json={})
        assert response.status_code == 400
        assert response.get_json()['error_code'] == 'bad_request'

    def test_unknown_scope_rejected(self, admin_client):
        response = admin_client.post(
            '/admin/api/system/reset', json={'scopes': ['everything']}
        )
        assert response.status_code == 400
        assert 'everything' in response.get_json()['error']

    def test_without_confirm_it_only_previews(self, admin_client, db_session):
        """The default for a destructive endpoint must be to describe, not do."""
        from oneirodex.models import Library
        from oneirodex.platform import LibraryPlatform

        library = Library(name='SurvivesPreview', platform=LibraryPlatform.PCWIN)
        db_session.add(library)
        db_session.commit()
        uuid = library.uuid

        response = admin_client.post(
            '/admin/api/system/reset', json={'scopes': ['libraries']}
        )
        body = response.get_json()

        assert response.status_code == 200
        assert body['ok'] is True
        assert body['performed'] is False
        assert body['touches_files'] is False
        assert db_session.get(Library, uuid) is not None

    def test_wrong_confirmation_phrase_rejected(self, admin_client, db_session):
        from oneirodex.models import Library
        from oneirodex.platform import LibraryPlatform

        library = Library(name='SurvivesBadPhrase', platform=LibraryPlatform.PCWIN)
        db_session.add(library)
        db_session.commit()
        uuid = library.uuid

        response = admin_client.post(
            '/admin/api/system/reset',
            json={'scopes': ['libraries'], 'confirm': 'yes'},
        )

        assert response.status_code == 422
        assert db_session.get(Library, uuid) is not None

    def test_catalog_reset_clears_games_but_keeps_the_library(
        self, admin_client, db_session
    ):
        """The point of the catalog scope: rescan immediately, no re-setup."""
        from oneirodex.models import Game, Library
        from oneirodex.platform import LibraryPlatform

        library = Library(name='KeptLibrary', platform=LibraryPlatform.PCWIN)
        db_session.add(library)
        db_session.commit()
        uuid = library.uuid

        game = Game(name='Doomed', library_uuid=uuid)
        db_session.add(game)
        db_session.commit()

        response = admin_client.post(
            '/admin/api/system/reset',
            json={'scopes': ['catalog'], 'confirm': 'RESET ONEIRODEX'},
        )
        assert response.status_code == 200
        assert response.get_json()['performed'] is True

        db_session.expire_all()
        assert db_session.query(Game).count() == 0
        assert db_session.get(Library, uuid) is not None

    def test_user_reset_keeps_the_acting_admin(self, admin_client, db_session, admin_user):
        """Never lock the operator out of the install they just reset."""
        from datetime import datetime, timezone
        from oneirodex.models import User, SupportTicket, SupportDeliveryAttempt, SupportDeliveryCheckBudget

        admin_id = admin_user.id
        admin_name = admin_user.name
        ticket = SupportTicket(user_id=admin_id, title='Synthetic support receipt', body='Kept locally')
        db_session.add(ticket)
        db_session.flush()
        db_session.add_all([
            SupportDeliveryAttempt(id=str(uuid4()), user_id=admin_id, ticket_id=ticket.id,
                                   created_at=datetime.now(timezone.utc), repository='example/repo',
                                   payload_sha256='a' * 64, outcome='unknown'),
            SupportDeliveryCheckBudget(user_id=admin_id, window_started_at=datetime.now(timezone.utc), count=1),
        ])
        db_session.commit()

        response = admin_client.post(
            '/admin/api/system/reset',
            json={'scopes': ['users'], 'confirm': 'RESET ONEIRODEX'},
        )
        assert response.status_code == 200
        body = response.get_json()
        assert body['performed'] is True
        assert body['actor_restored'] is True

        db_session.expire_all()
        survivor = db_session.get(User, admin_id)
        assert survivor is not None
        assert survivor.name == admin_name
        assert db_session.query(User).count() == 1
        assert db_session.query(SupportTicket).count() == 0
        assert db_session.query(SupportDeliveryAttempt).count() == 0
        assert db_session.query(SupportDeliveryCheckBudget).count() == 0

    def test_user_reset_preserves_previously_committed_file_cleanup(
        self, admin_client, db_session, tmp_path,
    ):
        import hashlib
        from oneirodex.models import UserDeletionFileJob
        from oneirodex.utils.user_deletion import process_pending_file_jobs

        target = tmp_path / 'deleted-account-avatar.png'
        target.write_bytes(b'previously committed account deletion')
        root, relative = str(tmp_path.resolve()), target.name
        job = UserDeletionFileJob(
            path_key=hashlib.sha256(f'{root}\0{relative}'.encode()).hexdigest(),
            root_path=root, relative_path=relative, state='failed', attempts=1,
        )
        db_session.add(job)
        db_session.commit()
        job_id = job.id

        response = admin_client.post('/admin/api/system/reset', json={
            'scopes': list(RESET_SCOPES), 'confirm': 'RESET ONEIRODEX',
        })
        assert response.status_code == 200
        assert response.get_json()['touches_files'] is False
        assert target.exists()
        db_session.expire_all()
        retained = db_session.get(UserDeletionFileJob, job_id)
        assert retained is not None
        assert retained.state == 'failed' and retained.attempts == 1

        assert process_pending_file_jobs(db_session) == 0
        assert not target.exists()
        assert db_session.get(UserDeletionFileJob, job_id) is None

    def test_non_admin_forbidden(self, client, regular_user):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(regular_user.id)
            sess['_fresh'] = True
        response = client.post(
            '/admin/api/system/reset',
            json={'scopes': ['catalog'], 'confirm': 'RESET ONEIRODEX'},
        )
        assert response.status_code in (302, 403)
