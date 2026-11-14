"""Opt-in P0-02 fixtures; never select an operator database or service."""
from __future__ import annotations

import asyncio
from ipaddress import ip_address
import socket
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.engine import make_url

from database_test_guard import validate_test_database_url


def _loopback(host) -> bool:
    if host == 'localhost':
        return True
    try:
        return ip_address(host).is_loopback
    except (TypeError, ValueError):
        return False


def review_database_endpoint(value) -> tuple[str, int]:
    """Validate before creating fixture rows; keep diagnostics credential-free."""
    try:
        validate_test_database_url(value)
        url = make_url(value)
        port = 5432 if url.port is None else url.port
        if _loopback(url.host) and 1 <= port <= 65535:
            return url.host, port
    except (RuntimeError, ValueError, TypeError):
        pass
    raise RuntimeError('Household fixtures require an explicit loopback PostgreSQL test database') from None


def allow_database_sockets_only(monkeypatch, endpoint: tuple[str, int]) -> None:
    """Block DNS and TCP for providers/SMTP, including loopback SMTP servers.

    Install only for tests using this fixture, never globally. An in-process
    ASGI transport needs no listening socket. The database is the sole TCP
    exception; separate process tools need their runner's own network guard.
    """
    database_port = endpoint[1]
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_getaddrinfo = socket.getaddrinfo

    def permitted(host, port):
        try:
            return _loopback(host) and int(port) == database_port
        except (TypeError, ValueError):
            return False

    def check(address):
        if not isinstance(address, tuple) or len(address) < 2 or not permitted(*address[:2]):
            raise RuntimeError('Blocked by household fixture network boundary')

    def connect(sock, address):
        check(address)
        return real_connect(sock, address)

    def connect_ex(sock, address):
        check(address)
        return real_connect_ex(sock, address)

    def getaddrinfo(host, port, *args, **kwargs):
        if not permitted(host, port):
            raise RuntimeError('Blocked by household fixture network boundary')
        return real_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket.socket, 'connect', connect)
    monkeypatch.setattr(socket.socket, 'connect_ex', connect_ex)
    monkeypatch.setattr(socket, 'getaddrinfo', getaddrinfo)


@dataclass
class Household:
    users: dict
    games: dict
    root: Path
    legacy_path: Path
    unrelated_path: Path
    identities: dict[str, str] = field(repr=False)
    bearers: dict[str, str] = field(repr=False)


def seed_household(app, session, tmp_path: Path, monkeypatch) -> Household:
    """Seed real rows under the caller's rolled-back PostgreSQL test session.

    The fixture owns only its child directory. Pytest owns temporary-directory
    retention and the caller owns transaction rollback; this helper never
    performs a broad filesystem delete or a schema operation.
    """
    endpoint = review_database_endpoint(app.config.get('SQLALCHEMY_DATABASE_URI'))
    allow_database_sockets_only(monkeypatch, endpoint)
    from oneirodex.models import EmulatorSave, Game, Library, User, UserLibraryAccess
    from oneirodex.platform import LibraryPlatform
    from oneirodex.utils.api_tokens import VALID_SCOPES, generate_api_token
    from oneirodex.utils.global_settings import global_settings_row_or_create
    from oneirodex.utils.persistent_sessions import issue_login_identity

    root = tmp_path / 'household-safety'
    root.mkdir()
    unrelated = tmp_path / 'unrelated-fixture.bin'
    unrelated.write_bytes(b'unrelated-fixture')
    monkeypatch.setitem(app.config, 'EMULATOR_SAVES_PATH', str(root))
    settings = global_settings_row_or_create()
    settings.enable_emulator_save_sync = True
    settings.encrypt_emulator_saves = False
    tag = uuid4().hex
    roles = {
        'member': 'user', 'disabled': 'user', 'child_none': 'child',
        'child_some': 'child', 'librarian': 'librarian', 'admin': 'admin',
    }
    users = {
        name: User(
            name=f'fixture-{name}-{tag[:12]}', email=f'{name}-{tag}@example.test',
            user_id=str(uuid4()), role=role, state=True, is_email_verified=True,
            password_hash=f'synthetic-unused-password-hash-{tag}-{name}',
        )
        for name, role in roles.items()
    }
    libraries = {
        name: Library(name=f'fixture-{name}-{tag[:12]}', platform=LibraryPlatform.NES)
        for name in ('allowed', 'denied')
    }
    session.add_all([*users.values(), *libraries.values()])
    session.flush()
    games = {
        name: Game(
            uuid=str(uuid4()), name=f'fixture-{name}', library_uuid=library.uuid,
            full_disk_path=None, size=0,
        )
        for name, library in libraries.items()
    }
    session.add_all(games.values())
    session.add(UserLibraryAccess(
        user_id=users['child_some'].id, library_uuid=libraries['allowed'].uuid,
    ))
    session.commit()
    identities = {name: issue_login_identity(user) for name, user in users.items()}
    users['disabled'].state = False
    bearers = {}
    for scope in sorted(VALID_SCOPES):
        owner = users['admin'] if scope == 'admin' else users['member']
        _, bearers[scope] = generate_api_token(owner, f'fixture-{scope}', [scope])
    _, bearers['child_save'] = generate_api_token(
        users['child_some'], 'fixture-child-save', ['read:library', 'write:saves'],
    )
    legacy = root / 'legacy-collision.state'
    legacy.write_bytes(b'legacy-fixture')
    session.add_all([
        EmulatorSave(
            user_id=users['member'].id, game_uuid=games['allowed'].uuid,
            slot_name=slot, filename='legacy.state', size_bytes=len(b'legacy-fixture'),
            storage_path=str(legacy), encrypted=False,
        )
        for slot in ('alpha beta', 'alpha_beta')
    ])
    session.commit()
    return Household(users, games, root, legacy, unrelated, identities, bearers)


@pytest.fixture
def household_loop():
    # Windows creates a private loopback socket pair for its event loop. Build
    # it before the fixture network boundary; no general loopback exception.
    with asyncio.Runner() as runner:
        runner.get_loop()
        yield runner


@pytest.fixture
def household(app, db_session, tmp_path, monkeypatch, household_loop):
    return seed_household(app, db_session, tmp_path, monkeypatch)
