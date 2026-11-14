"""hash persisted email-verification tokens

Revision ID: c0f6e9a2d1b4
Revises: f9a04c1d7e32
Create Date: 2026-11-06 12:00:00.000000

The existing column is wide enough for a SHA-256 hex digest. This data-only
migration preserves the confirmation links already sent to mailbox owners.
"""
from typing import Sequence, Union
import hashlib
import re

from alembic import op
import sqlalchemy as sa


revision: str = 'c0f6e9a2d1b4'
down_revision: Union[str, Sequence[str], None] = 'f9a04c1d7e32'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SHA256_HEX = re.compile(r'^[0-9a-f]{64}$')


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'users' not in inspector.get_table_names():
        return
    columns = {column['name'] for column in inspector.get_columns('users')}
    if not {'id', 'email_verification_token'} <= columns:
        return

    rows = bind.execute(sa.text(
        'SELECT id, email_verification_token FROM users '
        'WHERE email_verification_token IS NOT NULL '
        "AND email_verification_token <> ''"
    )).all()
    for user_id, token in rows:
        if _SHA256_HEX.fullmatch(token):
            continue
        digest = hashlib.sha256(token.encode('utf-8')).hexdigest()
        bind.execute(sa.text(
            'UPDATE users SET email_verification_token = :digest '
            'WHERE id = :user_id AND email_verification_token = :token'
        ), {'digest': digest, 'user_id': user_id, 'token': token})


def downgrade() -> None:
    # The column and schema do not change. Digests remain usable by older
    # confirmation routes, which validate the signed link and age directly.
    pass
