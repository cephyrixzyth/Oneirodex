"""add retryable post-commit user file cleanup jobs

Revision ID: a2b3c4d5e6f7
Revises: c1d2e3f4a5b6
Create Date: 2026-11-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a2b3c4d5e6f7'
down_revision: Union[str, Sequence[str], None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if 'user_deletion_file_jobs' in inspector.get_table_names():
        return
    op.create_table(
        'user_deletion_file_jobs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('path_key', sa.String(length=64), nullable=False),
        sa.Column('root_path', sa.String(length=1024), nullable=False),
        sa.Column('relative_path', sa.String(length=1024), nullable=False),
        sa.Column('state', sa.String(length=16), nullable=False, server_default='pending'),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_error_code', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('path_key', name='uq_user_delete_file_job_path'),
    )
    op.create_index(
        'ix_user_deletion_file_jobs_state', 'user_deletion_file_jobs', ['state', 'updated_at'],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'user_deletion_file_jobs' not in inspector.get_table_names():
        return
    pending = bind.execute(sa.text(
        "SELECT 1 FROM user_deletion_file_jobs WHERE state != 'complete' LIMIT 1"
    )).first()
    if pending:
        raise RuntimeError('Refusing to drop pending account-deletion file jobs')
    op.drop_index('ix_user_deletion_file_jobs_state', table_name='user_deletion_file_jobs')
    op.drop_table('user_deletion_file_jobs')
