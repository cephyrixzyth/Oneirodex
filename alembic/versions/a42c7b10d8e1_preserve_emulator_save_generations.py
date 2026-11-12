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
    # Native boot creates current metadata before adopting the baseline. A
    # legacy database can also contain only some of these objects after repair.
    inspector = sa.inspect(op.get_bind())
    columns = {column['name']: column for column in inspector.get_columns('emulator_saves')}
    if 'revision' not in columns:
        op.add_column('emulator_saves', sa.Column('revision', sa.Integer(), nullable=True))
    elif not isinstance(columns['revision']['type'], sa.Integer):
        raise RuntimeError('Incompatible emulator save revision column; schema repair required')
    op.execute('UPDATE emulator_saves SET revision = 1 WHERE revision IS NULL')
    op.alter_column(
        'emulator_saves', 'revision',
        existing_type=sa.Integer(), nullable=False,
    )
    table = 'emulator_save_generations'
    if not inspector.has_table(table):
        op.create_table(
            table,
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
    else:
        _validate_existing_history(inspector, table)

    index_name = 'ix_emulator_save_generations_save_id'
    indexes = {index['name']: index for index in inspector.get_indexes(table)}
    if index_name not in indexes:
        op.create_index(index_name, table, ['save_id'])
    else:
        index = indexes[index_name]
        if (index['column_names'] != ['save_id'] or index['unique']
                or index.get('dialect_options', {}).get('postgresql_where') is not None):
            raise RuntimeError('Incompatible emulator save history index; schema repair required')


def _validate_existing_history(inspector, table) -> None:
    """Adopt compatible metadata without dropping or rewriting retained history."""
    columns = {column['name']: column for column in inspector.get_columns(table)}
    expected = {
        'id': (sa.Integer, None), 'save_id': (sa.Integer, None),
        'filename': (sa.String, 255), 'size_bytes': (sa.Integer, None),
        'storage_path': (sa.String, 1024), 'encrypted': (sa.Boolean, None),
        'created_at': (sa.DateTime, None),
    }
    for name, (kind, length) in expected.items():
        column = columns.get(name)
        if (column is None or column['nullable']
                or not isinstance(column['type'], kind)
                or (length is not None and getattr(column['type'], 'length', 0) != length)):
            raise RuntimeError('Incompatible emulator save history columns; schema repair required')
    if inspector.get_pk_constraint(table)['constrained_columns'] != ['id']:
        raise RuntimeError('Incompatible emulator save history primary key; schema repair required')
    if not any(
        fk['constrained_columns'] == ['save_id']
        and fk['referred_table'] == 'emulator_saves'
        and fk['referred_columns'] == ['id']
        and fk.get('options', {}).get('ondelete', '').upper() == 'CASCADE'
        for fk in inspector.get_foreign_keys(table)
    ):
        raise RuntimeError('Incompatible emulator save history foreign key; schema repair required')


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text('SELECT 1 FROM emulator_save_generations LIMIT 1')).first():
        raise RuntimeError(
            'Refusing to drop retained emulator save history; export or explicitly clear it first'
        )
    op.drop_index('ix_emulator_save_generations_save_id', table_name='emulator_save_generations')
    op.drop_table('emulator_save_generations')
    op.drop_column('emulator_saves', 'revision')
