"""add per-scan options to scan_jobs

Revision ID: 8c9d0e1f2a3b
Revises: 7b8c9d0e1f2a
Create Date: 2026-11-27 21:00:00.000000

The Scan page can now choose, per scan, whether to re-check existing matches,
whether to retry folders an earlier scan left unmatched, and whether to send
every match to review instead of importing it. Defaults keep the old behaviour.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '8c9d0e1f2a3b'
down_revision: Union[str, Sequence[str], None] = '7b8c9d0e1f2a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = (
    ('setting_recheck_matches', sa.true()),
    ('setting_retry_unmatched', sa.true()),
    ('setting_propose_only', sa.false()),
)


def upgrade() -> None:
    existing = {col['name'] for col in sa.inspect(op.get_bind()).get_columns('scan_jobs')}
    for name, default in COLUMNS:
        if name not in existing:
            op.add_column(
                'scan_jobs',
                sa.Column(name, sa.Boolean(), nullable=False, server_default=default),
            )


def downgrade() -> None:
    existing = {col['name'] for col in sa.inspect(op.get_bind()).get_columns('scan_jobs')}
    for name, _default in reversed(COLUMNS):
        if name in existing:
            op.drop_column('scan_jobs', name)
