"""allow versioned encrypted reusable integration credentials

Revision ID: c1d2e3f4a5b6
Revises: b7c2d3e4f5a6
Create Date: 2026-11-07 00:00:00

Plaintext conversion is an explicit, separately rerunnable operator command.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, Sequence[str], None] = 'b7c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SECRET_COLUMNS = (
    'smtp_password', 'igdb_client_secret', 'oidc_client_secret',
    'steam_web_api_key', 'steamgriddb_api_key', 'giantbomb_api_key',
    'mobygames_api_key', 'thegamesdb_api_key', 'retroachievements_api_key',
)
_LEGACY_LENGTHS = {
    'smtp_password': 255,
    'igdb_client_secret': 255,
    'oidc_client_secret': 512,
    'steam_web_api_key': 255,
    'steamgriddb_api_key': 255,
    'giantbomb_api_key': 255,
    'mobygames_api_key': 255,
    'thegamesdb_api_key': 255,
    'retroachievements_api_key': 512,
}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if 'global_settings' not in inspector.get_table_names():
        return
    existing = {column['name']: column['type'] for column in inspector.get_columns('global_settings')}
    with op.batch_alter_table('global_settings') as batch:
        for name in _SECRET_COLUMNS:
            if name in existing:
                batch.alter_column(name, existing_type=existing[name], type_=sa.Text(), nullable=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'global_settings' not in inspector.get_table_names():
        return
    rows = bind.execute(sa.text(
        "SELECT 1 FROM global_settings WHERE " + " OR ".join(
            f"{name} LIKE 'odrc:%'" for name in _SECRET_COLUMNS
        ) + ' LIMIT 1'
    )).first()
    if rows:
        raise RuntimeError('Refusing to narrow reusable credential columns while encrypted values remain')
    existing = {column['name']: column['type'] for column in inspector.get_columns('global_settings')}
    with op.batch_alter_table('global_settings') as batch:
        for name in _SECRET_COLUMNS:
            if name in existing:
                batch.alter_column(
                    name,
                    existing_type=existing[name],
                    type_=sa.String(length=_LEGACY_LENGTHS[name]),
                    nullable=True,
                )
