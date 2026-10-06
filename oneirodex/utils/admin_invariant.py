"""Serialize mutations that could change the active-admin count."""

from sqlalchemy import text


# One transaction-scoped lock across the admin editor and optional OIDC role sync.
# PostgreSQL releases it on commit or rollback, including error paths.
_ADMIN_MUTATION_LOCK_KEY = 0x4F4E4549


def lock_admin_mutation(session) -> None:
    session.execute(
        text('SELECT pg_advisory_xact_lock(:lock_key)'),
        {'lock_key': _ADMIN_MUTATION_LOCK_KEY},
    )
