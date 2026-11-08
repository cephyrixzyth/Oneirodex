"""preserve public game collections when deleting their creator

Revision ID: e1f2a3b4c5d6
Revises: d6e7f8a9b0c1
Create Date: 2026-11-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, Sequence[str], None] = 'd6e7f8a9b0c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_OWNER_FK_NAME = 'fk_game_collections_owner_user_id_users'


def _owner_foreign_keys(inspector):
    return [
        foreign_key for foreign_key in inspector.get_foreign_keys('game_collections')
        if foreign_key.get('constrained_columns') == ['owner_user_id']
    ]


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if 'game_collections' not in inspector.get_table_names():
        return
    for foreign_key in _owner_foreign_keys(inspector):
        if foreign_key.get('name'):
            op.drop_constraint(
                foreign_key['name'], 'game_collections', type_='foreignkey',
            )
    op.create_foreign_key(
        _OWNER_FK_NAME,
        'game_collections',
        'users',
        ['owner_user_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if 'game_collections' not in inspector.get_table_names():
        return
    for foreign_key in _owner_foreign_keys(inspector):
        if foreign_key.get('name'):
            op.drop_constraint(
                foreign_key['name'], 'game_collections', type_='foreignkey',
            )
    op.create_foreign_key(
        _OWNER_FK_NAME,
        'game_collections',
        'users',
        ['owner_user_id'],
        ['id'],
        ondelete='CASCADE',
    )
