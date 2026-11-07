"""preserve prior emulator save generations

Revision ID: a42c7b10d8e1
Revises: c0f6e9a2d1b4
Create Date: 2026-11-07 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a42c7b10d8e1'
down_revision: Union[str, Sequence[str], None] = 'c0f6e9a2d1b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'emulator_saves',
        sa.Column('revision', sa.Integer(), nullable=True),
    )
    op.execute('UPDATE emulator_saves SET revision = 1 WHERE revision IS NULL')
    op.alter_column(
        'emulator_saves', 'revision',
        existing_type=sa.Integer(), nullable=False,
    )
    op.create_table(
        'emulator_save_generations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column(
            'save_id', sa.Integer(),
            sa.ForeignKey('emulator_saves.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('storage_path', sa.String(1024), nullable=False),
        sa.Column('encrypted', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index(
        'ix_emulator_save_generations_save_id',
        'emulator_save_generations', ['save_id'],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text('SELECT 1 FROM emulator_save_generations LIMIT 1')).first():
        raise RuntimeError(
            'Refusing to drop retained emulator save history; export or explicitly clear it first'
        )
    op.drop_index('ix_emulator_save_generations_save_id', table_name='emulator_save_generations')
    op.drop_table('emulator_save_generations')
    op.drop_column('emulator_saves', 'revision')
