"""Actual PostgreSQL reservation races and committed acknowledgement failures."""
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
from threading import Barrier, Event, Lock, Thread
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, select, text, delete, func
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from alembic.migration import MigrationContext
from alembic.operations import Operations

from oneirodex import db
from oneirodex.models import SupportTicket, SupportDeliveryAttempt, SupportDeliveryCheckBudget, User
from oneirodex.utils.support_delivery import (
    deliver_support_request, find_support_request, persist_support_request,
    support_reconciliation_candidate, finish_support_reconciliation,
)


@pytest.fixture
def delivery_account(app, no_savepoint_db):
    # Independent connections, actual commits, bounded locks; never db_session's
    # shared SAVEPOINT connection. This engine is disposed before fixture cleanup.
    engine = create_engine(db.engine.url, connect_args={
        'options': '-c lock_timeout=3000 -c statement_timeout=5000',
    })
    with Session(engine) as session:
        user = User(name='support-' + uuid4().hex[:8], email=uuid4().hex + '@example.invalid',
                    password_hash='unused', role='user', user_id=str(uuid4()), invite_quota=0)
        session.add(user)
        session.commit()
        owner = SimpleNamespace(id=user.id, role='user', name=user.name)
    try:
        yield engine, owner
    finally:
        engine.dispose()


def report():
    return {'title': 'One committed report', 'body': 'Synthetic body',
            'request_id': str(uuid4()), 'sync_to_github': True}


def receipt():
    return {'ok': True, 'number': 701, 'url': 'https://github.com/example/repo/issues/701'}


def test_provider_cooldown_applies_to_other_reports_and_survives_a_new_session(delivery_account, monkeypatch):
    engine, owner = delivery_account
    clock = datetime.now(timezone.utc)
    monkeypatch.setattr('oneirodex.utils.support_delivery.delivery_now', lambda: clock)
    calls = []
    def limited(**payload):
        calls.append(payload)
        return {'ok': False, 'outcome': 'rejected', 'http_status': 429, 'retry_after_seconds': 120}
    with Session(engine) as session:
        ticket, _ = persist_support_request(session, owner, report(), clock)
        deliver_support_request(session, ticket, {'title': 'Report', 'body': 'Report'}, limited)
    with Session(engine) as session:
        other, _ = persist_support_request(session, owner, report(), clock)
        other = deliver_support_request(session, other, {'title': 'Another', 'body': 'Report'}, limited)
        assert len(calls) == 1, 'A different report must not bypass a persisted provider cooldown'
        assert other.github_sync == 'pending'
        assert other.github_retry_after_at == clock + timedelta(seconds=120)
        clock += timedelta(seconds=120)
        deliver_support_request(session, other, {'title': 'Another', 'body': 'Report'}, lambda **p: calls.append(p) or receipt())
        assert len(calls) == 2


def test_forwarding_budget_expires_without_sleeping_or_losing_the_receipt(delivery_account, monkeypatch):
    engine, owner = delivery_account
    clock = datetime.now(timezone.utc)
    monkeypatch.setattr('oneirodex.utils.support_delivery.delivery_now', lambda: clock)
    calls = []
    def reject(**payload):
        calls.append(payload)
        return {'ok': False, 'outcome': 'rejected', 'http_status': 422}
    with Session(engine) as session:
        ticket, _ = persist_support_request(session, owner, report(), clock)
        payload = {'title': 'Report', 'body': 'Report'}
        for index in range(5):
            ticket = deliver_support_request(session, ticket, payload, reject, retry_id=str(uuid4()) if index else None)
        nonce = str(uuid4())
        ticket = deliver_support_request(session, ticket, payload, reject, retry_id=nonce)
        assert len(calls) == 5
        assert ticket.github_sync == 'rejected' and ticket.github_retry_after_at == clock + timedelta(hours=1)
        assert session.get(SupportDeliveryAttempt, {'id': nonce, 'user_id': owner.id}) is None
        clock += timedelta(hours=1)
        ticket = deliver_support_request(session, ticket, payload, reject, retry_id=nonce)
        assert len(calls) == 6, 'The hour window must end at its advertised retry time'


def test_concurrent_explicit_retry_claims_and_lost_reply_allow_one_attempt(delivery_account):
    engine, owner = delivery_account
    values, payload = report(), {'title': 'Report', 'body': 'Report'}
    with Session(engine) as session:
        ticket, _ = persist_support_request(session, owner, values, datetime.now(timezone.utc))
        deliver_support_request(session, ticket, payload, lambda **_: {'ok': False, 'outcome': 'rejected'})
    barrier, release, sending, returned = Barrier(2), Event(), Event(), Event()
    nonce, sends, errors = str(uuid4()), [], []
    def sender(**p):
        sends.append(p)
        sending.set()
        assert release.wait(8)
        return receipt()
    def worker():
        try:
            with Session(engine) as session:
                ticket = find_support_request(session, owner.id, values)
                barrier.wait(timeout=5)
                deliver_support_request(session, ticket, payload, sender, retry_id=nonce)
        except Exception as exc:
            errors.append(type(exc).__name__)
        finally:
            returned.set()
    threads = [Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    try:
        assert sending.wait(5) and returned.wait(5)
        assert len(sends) == 1
    finally:
        release.set()
        for thread in threads:
            thread.join(8)
    assert not any(thread.is_alive() for thread in threads)
    assert errors == []
    with Session(engine) as session:
        ticket = find_support_request(session, owner.id, values)
        assert ticket.github_sync == 'synced'
        deliver_support_request(session, ticket, payload, sender, retry_id=nonce)
        assert len(sends) == 1
        assert session.scalar(select(func.count()).select_from(SupportDeliveryAttempt).where(SupportDeliveryAttempt.user_id == owner.id)) == 2


def test_late_provider_callback_cannot_overwrite_reconciliation(delivery_account):
    engine, owner = delivery_account
    values, payload = report(), {'title': 'Exact title', 'body': 'Exact body'}
    with Session(engine) as session:
        ticket, _ = persist_support_request(session, owner, values, datetime.now(timezone.utc))
        ticket_id = ticket.id
    release, sending, errors = Event(), Event(), []
    def sender(**_):
        sending.set()
        assert release.wait(8)
        return {'ok': False, 'outcome': 'rejected'}
    def worker():
        try:
            with Session(engine) as session:
                deliver_support_request(session, session.get(SupportTicket, ticket_id), payload, sender)
        except Exception as exc:
            errors.append(type(exc).__name__)
    thread = Thread(target=worker)
    thread.start()
    try:
        assert sending.wait(5)
        with Session(engine) as session:
            candidate = support_reconciliation_candidate(session, owner.id, ticket_id)
            assert not session.in_transaction(), 'No transaction may remain open during provider lookup'
            linked = finish_support_reconciliation(session, candidate, {**payload, 'number': 701, 'html_url': receipt()['url']})
            assert linked['github_sync'] == 'reconciled'
    finally:
        release.set()
        thread.join(8)
    assert not thread.is_alive() and errors == []
    with Session(engine) as session:
        saved = session.get(SupportTicket, ticket_id)
        assert saved.github_sync == 'reconciled'
        assert session.get(SupportDeliveryAttempt, {'id': saved.github_attempt_id, 'user_id': owner.id}).outcome == 'reconciled'


@pytest.mark.parametrize('startup_tables_already_present', [False, True])
def test_attempt_migration_preserves_historical_rows_and_account_deletion_cascades(
    delivery_account, startup_tables_already_present,
):
    engine, _owner = delivery_account
    root = Path(__file__).resolve().parents[1]
    schema = 'support_migration_test_' + uuid4().hex
    spec = importlib.util.spec_from_file_location('support_attempt_revision', root / 'alembic/versions/a4b5c6d7e8f9_support_delivery_attempts.py')
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    try:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            connection.execute(text('CREATE TABLE users (id INTEGER PRIMARY KEY)'))
            connection.execute(text('INSERT INTO users VALUES (1),(2)'))
            connection.execute(text('CREATE TABLE support_tickets (id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id) ON DELETE CASCADE, title TEXT NOT NULL)'))
            connection.execute(text("INSERT INTO support_tickets VALUES (1,1,'Historical uncertain report'),(2,2,'Unrelated report')"))
            if startup_tables_already_present:
                startup = (root / 'oneirodex/updateschema.py').read_text(encoding='utf-8')
                fragment = startup.split('ALTER TABLE support_tickets ADD COLUMN IF NOT EXISTS github_repository', 1)[1].split('ALTER TABLE user_preferences', 1)[0]
                connection.execute(text('ALTER TABLE support_tickets ADD COLUMN IF NOT EXISTS github_repository' + fragment))
            with Operations.context(MigrationContext.configure(connection)):
                revision.upgrade()
                revision.upgrade()
                assert connection.execute(text('SELECT id,title,github_repository FROM support_tickets ORDER BY id')).all() == [
                    (1, 'Historical uncertain report', None), (2, 'Unrelated report', None),
                ]
                connection.execute(text("INSERT INTO support_delivery_attempts(id,user_id,ticket_id,created_at,repository,payload_sha256,outcome) VALUES ('old-attempt',1,1,now(),'example/repo',:digest,'unknown')"), {'digest': 'a' * 64})
                connection.execute(text('INSERT INTO support_delivery_check_budgets VALUES (1,now(),1)'))
                with pytest.raises(RuntimeError, match='receipt'):
                    revision.downgrade()
                assert connection.execute(text('SELECT count(*) FROM support_delivery_attempts')).scalar_one() == 1
                connection.execute(text('DELETE FROM users WHERE id=1'))
                assert connection.execute(text('SELECT count(*) FROM support_delivery_attempts')).scalar_one() == 0
                assert connection.execute(text('SELECT count(*) FROM support_delivery_check_budgets')).scalar_one() == 0
                assert connection.execute(text('SELECT title FROM support_tickets')).scalars().all() == ['Unrelated report']
                revision.downgrade()
                assert connection.execute(text('SELECT count(*) FROM support_tickets')).scalar_one() == 1
    finally:
        assert schema.startswith('support_migration_test_') and len(schema.rsplit('_', 1)[-1]) == 32
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))


def test_concurrent_reservations_and_send_claims_allow_one_external_attempt(delivery_account):
    engine, owner = delivery_account
    values = report()
    barrier = Barrier(2)
    release, sending, returned = Event(), Event(), Event()
    lock = Lock()
    sends, results, errors = [], [], []

    def sender(**payload):
        with lock:
            sends.append(payload)
        sending.set()
        assert release.wait(8), 'Test must release the intercepted provider'
        return receipt()

    def worker():
        try:
            with Session(engine) as session:
                barrier.wait(timeout=5)
                ticket, created = persist_support_request(session, owner, values, datetime.now(timezone.utc))
                ticket = deliver_support_request(session, ticket, {'title': 'Report', 'body': 'Report'}, sender)
                with lock:
                    results.append((ticket.id, created, ticket.github_sync))
        except Exception as exc:
            errors.append(type(exc).__name__)
        finally:
            returned.set()

    threads = [Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    try:
        assert sending.wait(5)
        assert returned.wait(5), 'Second request must return while provider is still delayed'
        assert len(sends) == 1
    finally:
        release.set()
        for thread in threads:
            thread.join(timeout=8)
    assert not any(thread.is_alive() for thread in threads)
    assert errors == []
    assert len(results) == 2
    assert results[0][0] == results[1][0]
    assert sum(created for _, created, _ in results) == 1
    with Session(engine) as session:
        saved = find_support_request(session, owner.id, values)
        assert saved.github_sync == 'synced'
        assert saved.request_id == values['request_id']


def test_real_local_commit_with_lost_ack_recovers_pending_receipt(delivery_account, monkeypatch):
    engine, owner = delivery_account
    values = report()
    with Session(engine) as session:
        original = session.commit
        def commit_then_lose_ack():
            original()
            raise OperationalError('synthetic-ack-loss', {}, RuntimeError('synthetic'))
        with monkeypatch.context() as patch:
            patch.setattr(session, 'commit', commit_then_lose_ack)
            with pytest.raises(OperationalError):
                persist_support_request(session, owner, values, datetime.now(timezone.utc))
    with Session(engine) as session:
        saved = find_support_request(session, owner.id, values)
        assert saved is not None and saved.github_sync == 'pending'
        original_id = saved.id
        recovered, created = persist_support_request(session, owner, values, datetime.now(timezone.utc))
        assert not created and recovered.id == original_id
        calls = []
        def sender(**payload):
            calls.append(payload)
            return receipt()
        deliver_support_request(session, recovered, {'title': 'Report', 'body': 'Report'}, sender)
        assert len(calls) == 1


@pytest.mark.parametrize('ack_lost_after_commit', [False, True])
def test_provider_result_commit_failure_never_repeats_external_post(
    delivery_account, monkeypatch, ack_lost_after_commit,
):
    engine, owner = delivery_account
    values, calls = report(), []
    def sender(**payload):
        calls.append(payload)
        return receipt()
    with Session(engine) as session:
        ticket, _ = persist_support_request(session, owner, values, datetime.now(timezone.utc))
        original, commits = session.commit, 0
        def fail_result_commit():
            nonlocal commits
            commits += 1
            if commits == 2:
                if ack_lost_after_commit:
                    original()
                raise OperationalError('synthetic-result-commit', {}, RuntimeError('synthetic'))
            return original()
        with monkeypatch.context() as patch:
            patch.setattr(session, 'commit', fail_result_commit)
            result = deliver_support_request(session, ticket, {'title': 'Report', 'body': 'Report'}, sender)
        assert result.github_sync == ('synced' if ack_lost_after_commit else 'sending')
    with Session(engine) as session:
        saved = find_support_request(session, owner.id, values)
        deliver_support_request(session, saved, {'title': 'Report', 'body': 'Report'}, sender)
        assert len(calls) == 1
        assert len(session.scalars(select(SupportTicket).where(SupportTicket.user_id == owner.id)).all()) == 1


@pytest.mark.parametrize('startup_columns_already_present', [False, True])
def test_populated_migration_preserves_reports_and_refuses_to_erase_receipts(
    delivery_account, startup_columns_already_present,
):
    engine, _owner = delivery_account
    schema = 'support_migration_test_' + uuid4().hex
    path = Path(__file__).resolve().parents[1] / 'alembic/versions/f2a3b4c5d6e7_support_request_receipts.py'
    spec = importlib.util.spec_from_file_location('support_receipt_revision', path)
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    try:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
            connection.execute(text('CREATE TABLE support_tickets (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, title TEXT NOT NULL)'))
            connection.execute(text("INSERT INTO support_tickets VALUES (1,1,'Original report'),(2,1,'Another historical report')"))
            if startup_columns_already_present:
                connection.execute(text('ALTER TABLE support_tickets ADD COLUMN request_id VARCHAR(36), ADD COLUMN request_hash VARCHAR(64), ADD COLUMN github_attempt_id VARCHAR(36)'))
                connection.execute(text('CREATE UNIQUE INDEX uq_support_ticket_user_request ON support_tickets(user_id,request_id)'))
            with Operations.context(MigrationContext.configure(connection)):
                revision.upgrade()
                revision.upgrade()
                assert connection.execute(text('SELECT id,title FROM support_tickets ORDER BY id')).all() == [
                    (1, 'Original report'), (2, 'Another historical report'),
                ]
                assert {c['name'] for c in inspect(connection).get_columns('support_tickets')} >= {
                    'request_id', 'request_hash', 'github_attempt_id',
                }
                assert 'uq_support_ticket_user_request' in {
                    c['name'] for c in inspect(connection).get_unique_constraints('support_tickets')
                }
                connection.execute(text('UPDATE support_tickets SET request_id=:id WHERE id=1'), {'id': str(uuid4())})
                with pytest.raises(RuntimeError, match='receipt'):
                    revision.downgrade()
                assert 'request_id' in {c['name'] for c in inspect(connection).get_columns('support_tickets')}
                connection.execute(text('UPDATE support_tickets SET request_id=NULL'))
                revision.downgrade()
                assert connection.execute(text('SELECT count(*) FROM support_tickets')).scalar_one() == 2
    finally:
        # The schema is generated here, never accepted from config or a user.
        assert schema.startswith('support_migration_test_') and len(schema.rsplit('_', 1)[-1]) == 32
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
