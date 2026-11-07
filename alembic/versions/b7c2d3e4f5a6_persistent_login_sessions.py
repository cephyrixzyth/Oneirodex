"""add server-side persistent login sessions

Revision ID: b7c2d3e4f5a6
Revises: a42c7b10d8e1
Create Date: 2026-11-07 00:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7c2d3e4f5a6'
down_revision: Union[str, Sequence[str], None] = 'a42c7b10d8e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if 'persistent_login_sessions' in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        'persistent_login_sessions',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('secret_hash', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_persistent_login_sessions_user_active',
        'persistent_login_sessions', ['user_id', 'revoked_at'],
    )
    op.create_index(
        'ix_persistent_login_sessions_expiry',
        'persistent_login_sessions', ['expires_at'],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if 'persistent_login_sessions' not in sa.inspect(bind).get_table_names():
        return
    op.drop_index(
        'ix_persistent_login_sessions_expiry', table_name='persistent_login_sessions'
    )
    op.drop_index(
        'ix_persistent_login_sessions_user_active', table_name='persistent_login_sessions'
    )
    op.drop_table('persistent_login_sessions')
