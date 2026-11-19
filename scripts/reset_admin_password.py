#!/usr/bin/env python3
"""Reset an administrator's password when email recovery is unavailable.

Run inside the app container (or a native install) on the server itself:

    python scripts/reset_admin_password.py            # the only admin
    python scripts/reset_admin_password.py --user NAME
    python scripts/reset_admin_password.py --list     # admin usernames

The new password is read from a hidden prompt, entered twice, or from one line
on standard input with ``--password-stdin``. It must meet the app's 8-character
minimum. The script stores it with the app's Argon2 hasher, clears any pending
reset link and signs out remembered browser sessions, as a normal password
change does. API tokens are left alone.

Like the other operator scripts it never loads ``.env``, never falls back to
TEST_DATABASE_URL, and never prints the password, its hash, a database URL or
a filesystem path. Single-container installs resolve the embedded database
from ONEIRODEX_CONFIG_DIR; external databases need DATABASE_URL.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import getpass
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from argon2 import PasswordHasher
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

from oneirodex.models import PersistentLoginSession, User
from scripts.migrate_store_credentials import resolve_database_url

MIN_PASSWORD_LENGTH = 8  # matches the account password form


class ResetRefused(Exception):
    """A reset that cannot proceed; the message is safe to print."""


def admin_names(session: Session) -> list[str]:
    return list(session.execute(
        select(User.name).where(User.role == 'admin').order_by(User.name)
    ).scalars())


def choose_admin(session: Session, requested: str | None) -> User:
    if requested:
        user = session.execute(select(User).filter_by(name=requested)).scalar_one_or_none()
        if user is None:
            raise ResetRefused(f'No account is named {requested!r}. Usernames are case-sensitive; try --list.')
        if user.role != 'admin':
            raise ResetRefused(f'{requested!r} is not an administrator. Reset member passwords from the admin app.')
        return user
    names = admin_names(session)
    if not names:
        raise ResetRefused('This server has no administrator account.')
    if len(names) > 1:
        raise ResetRefused('More than one administrator exists; choose one with --user (see --list).')
    return session.execute(select(User).filter_by(name=names[0])).scalar_one()


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ResetRefused(f'The password must be at least {MIN_PASSWORD_LENGTH} characters.')
    if password != password.strip('\r\n') or '\x00' in password:
        raise ResetRefused('The password contains characters that cannot be typed at the sign-in page.')


def reset_password(session: Session, user: User, password: str) -> int:
    """Store ``password`` for ``user``; return how many remembered sessions were revoked."""
    validate_password(password)
    user.password_hash = PasswordHasher().hash(password)
    user.password_reset_token = None
    revoked = session.execute(
        update(PersistentLoginSession)
        .where(
            PersistentLoginSession.user_id == user.id,
            PersistentLoginSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(timezone.utc))
    ).rowcount
    session.commit()
    return int(revoked or 0)


def read_password(from_stdin: bool, username: str) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip('\r\n')
    if not sys.stdin.isatty():
        raise ResetRefused(
            'No terminal for a hidden prompt. Run with an interactive terminal '
            '(docker exec -it) or pass --password-stdin.'
        )
    for _ in range(3):
        first = getpass.getpass(f'New password for {username}: ')
        try:
            validate_password(first)
        except ResetRefused as exc:
            print(exc, file=sys.stderr)
            continue
        if getpass.getpass('Repeat it: ') == first:
            return first
        print('The two entries did not match.', file=sys.stderr)
    raise ResetRefused('No change made.')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n', 1)[0])
    parser.add_argument('--user', help='administrator username (case-sensitive)')
    parser.add_argument('--list', action='store_true', help='list administrator usernames and exit')
    parser.add_argument('--password-stdin', action='store_true', help='read the new password from one line of stdin')
    args = parser.parse_args(argv)

    try:
        engine = create_engine(resolve_database_url(), pool_pre_ping=True)
    except ValueError as exc:
        print(f'{exc}; no change made.', file=sys.stderr)
        return 2
    try:
        with Session(engine) as session:
            if args.list:
                for name in admin_names(session):
                    print(name)
                return 0
            user = choose_admin(session, args.user)
            username = user.name
            password = read_password(args.password_stdin, username)
            revoked = reset_password(session, user, password)
    except ResetRefused as exc:
        print(exc, file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - never print URLs, paths or bound values
        print(f'Password reset could not complete ({type(exc).__name__}); no change was confirmed.', file=sys.stderr)
        return 1
    finally:
        engine.dispose()

    print(f'Password updated for {username}. Remembered browser sign-ins revoked: {revoked}.')
    print('Sign in with the username exactly as shown; usernames are case-sensitive.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
