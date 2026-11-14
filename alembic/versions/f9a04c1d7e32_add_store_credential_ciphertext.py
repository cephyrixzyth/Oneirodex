"""add encrypted StoreAccount credential column

Revision ID: f9a04c1d7e32
Revises: e6f7a8b9c0d1
Create Date: 2026-11-04 00:00:00.000000

Credential conversion is a separate, explicit operator command. This additive
revision never rewrites or drops the legacy plaintext field.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f9a04c1d7e32'
down_revision: Union[str, Sequence[str], None] = 'e6f7a8b9c0d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'store_accounts' not in inspector.get_table_names():
        return
    existing = {column['name'] for column in inspector.get_columns('store_accounts')}
    if 'credential_ciphertext' not in existing:
        op.add_column(
            'store_accounts',
            sa.Column('credential_ciphertext', sa.Text(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'store_accounts' not in inspector.get_table_names():
        return
    existing = {column['name'] for column in inspector.get_columns('store_accounts')}
    if 'credential_ciphertext' in existing:
        # Do not discard credentials during downgrade. The operator must first
        # re-encrypt them into the legacy representation via an approved tool.
        rows = bind.execute(sa.text(
            'SELECT 1 FROM store_accounts '
            'WHERE credential_ciphertext IS NOT NULL LIMIT 1'
        )).first()
        if rows:
            raise RuntimeError(
                'Refusing to drop encrypted store credentials during downgrade'
            )
        op.drop_column('store_accounts', 'credential_ciphertext')
