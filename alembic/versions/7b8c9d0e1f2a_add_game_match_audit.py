"""add games.match_locked and games.match_checked_at

Revision ID: 7b8c9d0e1f2a
Revises: 6a7b8c9d0e1f
Create Date: 2026-11-26 19:00:00.000000

Scans now re-check games whose folder name disagrees with the title they were
matched to, and re-match them on their own (match_audit). ``match_locked`` marks
a title a person chose in manual identify, which a scan never changes.
``match_checked_at`` records when a scan last re-checked a game and kept its
match, so it is not searched again on every scan.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '7b8c9d0e1f2a'
down_revision: Union[str, Sequence[str], None] = '6a7b8c9d0e1f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {col['name'] for col in inspector.get_columns('games')}
    if 'match_locked' not in existing:
        op.add_column(
            'games',
            sa.Column('match_locked', sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if 'match_checked_at' not in existing:
        op.add_column('games', sa.Column('match_checked_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {col['name'] for col in inspector.get_columns('games')}
    if 'match_checked_at' in existing:
        op.drop_column('games', 'match_checked_at')
    if 'match_locked' in existing:
        op.drop_column('games', 'match_locked')
