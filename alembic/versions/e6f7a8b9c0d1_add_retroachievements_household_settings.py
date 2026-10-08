"""Add household RetroAchievements credentials.

Revision ID: e6f7a8b9c0d1
Revises: c4e5f6a7b8c9
Create Date: 2026-10-08
"""

from alembic import op
import sqlalchemy as sa


revision = 'e6f7a8b9c0d1'
down_revision = 'c4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {column['name'] for column in sa.inspect(bind).get_columns('global_settings')}
    if 'retroachievements_username' not in columns:
        op.add_column(
            'global_settings',
            sa.Column('retroachievements_username', sa.String(length=64), nullable=True),
        )
    if 'retroachievements_api_key' not in columns:
        op.add_column(
            'global_settings',
            sa.Column('retroachievements_api_key', sa.String(length=512), nullable=True),
        )


def downgrade():
    bind = op.get_bind()
    columns = {column['name'] for column in sa.inspect(bind).get_columns('global_settings')}
    if 'retroachievements_api_key' in columns:
        op.drop_column('global_settings', 'retroachievements_api_key')
    if 'retroachievements_username' in columns:
        op.drop_column('global_settings', 'retroachievements_username')
