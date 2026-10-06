"""Scope OIDC subject bindings to the issuer that issued them.

Existing subject-only bindings deliberately keep a NULL issuer. Their original
issuer cannot be recovered reliably from mutable global settings.
"""

from alembic import op
import sqlalchemy as sa


revision = 'c4e5f6a7b8c9'
down_revision = 'b3f9d2c7e1a5'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {column['name'] for column in sa.inspect(bind).get_columns('users')}
    if 'oidc_issuer_url' not in columns:
        op.add_column('users', sa.Column('oidc_issuer_url', sa.String(length=512), nullable=True))

    indexes = {index['name'] for index in sa.inspect(bind).get_indexes('users')}
    if 'ix_users_oidc_subject' in indexes:
        op.drop_index('ix_users_oidc_subject', table_name='users')
    if 'ux_users_oidc_issuer_subject' not in indexes:
        op.create_index(
            'ux_users_oidc_issuer_subject', 'users',
            ['oidc_issuer_url', 'oidc_subject'], unique=True,
        )


def downgrade():
    bind = op.get_bind()
    indexes = {index['name'] for index in sa.inspect(bind).get_indexes('users')}
    if 'ux_users_oidc_issuer_subject' in indexes:
        op.drop_index('ux_users_oidc_issuer_subject', table_name='users')
    if 'ix_users_oidc_subject' not in indexes:
        op.create_index('ix_users_oidc_subject', 'users', ['oidc_subject'], unique=True)
    if 'oidc_issuer_url' in {column['name'] for column in sa.inspect(bind).get_columns('users')}:
        op.drop_column('users', 'oidc_issuer_url')
