"""Remember which OIDC identity a user signed in with (users.oidc_subject).

Single sign-on used to link an identity-provider login to a local account by
email without checking the provider verified it, or failing that by username,
so an IdP account named like a local admin could sign in as that admin. The
link is now the provider's stable subject, stored on first sign-in.

Additive only: NULL for every existing user until their next OIDC sign-in.
"""
from alembic import op
import sqlalchemy as sa

revision = 'b3f9d2c7e1a5'
down_revision = 'a7c1d9e2f3b4'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {c['name'] for c in sa.inspect(bind).get_columns('users')}
    if 'oidc_subject' not in columns:
        op.add_column('users', sa.Column('oidc_subject', sa.String(length=255), nullable=True))
        op.create_index('ix_users_oidc_subject', 'users', ['oidc_subject'], unique=True)


def downgrade():
    bind = op.get_bind()
    columns = {c['name'] for c in sa.inspect(bind).get_columns('users')}
    if 'oidc_subject' in columns:
        op.drop_index('ix_users_oidc_subject', table_name='users')
        op.drop_column('users', 'oidc_subject')
