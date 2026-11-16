"""retain household chat messages when deleting their author

Revision ID: d6e7f8a9b0c1
Revises: a2b3c4d5e6f7
Create Date: 2026-11-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd6e7f8a9b0c1'
down_revision: Union[str, Sequence[str], None] = 'a2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_USER_FK_NAME = 'fk_chat_messages_user_id_users'


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if 'chat_messages' not in inspector.get_table_names():
        return

    user_foreign_keys = [
        fk for fk in inspector.get_foreign_keys('chat_messages')
        if fk.get('constrained_columns') == ['user_id']
    ]
    for foreign_key in user_foreign_keys:
        if foreign_key.get('name'):
            op.drop_constraint(foreign_key['name'], 'chat_messages', type_='foreignkey')

    user_column = next(
        (column for column in inspector.get_columns('chat_messages') if column['name'] == 'user_id'),
        None,
    )
    if user_column is None:
        return
    if not user_column['nullable']:
        op.alter_column(
            'chat_messages', 'user_id',
            existing_type=user_column['type'],
            existing_nullable=False,
            nullable=True,
        )
    op.create_foreign_key(
        _USER_FK_NAME,
        'chat_messages',
        'users',
        ['user_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'chat_messages' not in inspector.get_table_names():
        return
    if bind.execute(sa.text('SELECT 1 FROM chat_messages WHERE user_id IS NULL LIMIT 1')).first():
        raise RuntimeError(
            'Refusing to remove retained anonymized chat messages during downgrade'
        )

    foreign_keys = {
        foreign_key.get('name')
        for foreign_key in inspector.get_foreign_keys('chat_messages')
        if foreign_key.get('constrained_columns') == ['user_id']
    }
    for name in foreign_keys:
        if name:
            op.drop_constraint(name, 'chat_messages', type_='foreignkey')
    user_column = next(
        (column for column in inspector.get_columns('chat_messages') if column['name'] == 'user_id'),
        None,
    )
    if user_column is None:
        return
    op.alter_column(
        'chat_messages', 'user_id',
        existing_type=user_column['type'],
        existing_nullable=True,
        nullable=False,
    )
    op.create_foreign_key(
        _USER_FK_NAME,
        'chat_messages',
        'users',
        ['user_id'],
        ['id'],
        ondelete='CASCADE',
    )
