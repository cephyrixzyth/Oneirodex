"""Add per-member store sync jobs and a reconnect timestamp (LIB-04).

Additive only: existing accounts, entitlements and review decisions are not
rewritten. ``store_accounts.updated_at`` starts NULL (no reconnect recorded).
``user_owned_titles.external_app_id`` widens from 32 to 128 characters, which
Xbox package family names and Amazon product IDs need; existing values are
untouched.
"""
from alembic import op
import sqlalchemy as sa

revision = 'a7c1d9e2f3b4'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def _widen_external_app_id(bind, length):
    # SQLite does not enforce VARCHAR length and cannot ALTER a column type.
    if bind.dialect.name == 'sqlite' or not sa.inspect(bind).has_table('user_owned_titles'):
        return
    current = {c['name']: c['type'] for c in sa.inspect(bind).get_columns('user_owned_titles')}.get('external_app_id')
    if current is None or getattr(current, 'length', None) == length:
        return
    op.alter_column('user_owned_titles', 'external_app_id', type_=sa.String(length),
                    existing_type=current, existing_nullable=False)


def upgrade():
    bind = op.get_bind()
    _widen_external_app_id(bind, 128)
    columns = {c['name'] for c in sa.inspect(bind).get_columns('store_accounts')}
    if 'updated_at' not in columns:
        op.add_column('store_accounts', sa.Column('updated_at', sa.DateTime(), nullable=True))
    if not sa.inspect(bind).has_table('store_sync_jobs'):
        op.create_table('store_sync_jobs',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('store', sa.String(16), nullable=False),
            sa.Column('trigger', sa.String(16), nullable=False),
            sa.Column('actor_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
            sa.Column('status', sa.String(16), nullable=False),
            sa.Column('reason', sa.String(32), nullable=True),
            sa.Column('cancellable', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('cancel_requested', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('pages', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('items_seen', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('synced', sa.Integer(), nullable=True),
            sa.Column('matched', sa.Integer(), nullable=True),
            sa.Column('started_at', sa.DateTime(), nullable=False),
            sa.Column('heartbeat_at', sa.DateTime(), nullable=False),
            sa.Column('finished_at', sa.DateTime(), nullable=True))
        op.create_index('ix_store_sync_jobs_user_store', 'store_sync_jobs', ['user_id', 'store', 'id'])
        op.create_index('uq_store_sync_jobs_running', 'store_sync_jobs', ['user_id', 'store'], unique=True,
                        postgresql_where=sa.text("status = 'running'"),
                        sqlite_where=sa.text("status = 'running'"))


def downgrade():
    # Job history is diagnostic only; downgrading discards it.
    if sa.inspect(op.get_bind()).has_table('store_sync_jobs'):
        op.drop_table('store_sync_jobs')
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('store_accounts')}
    if 'updated_at' in columns:
        op.drop_column('store_accounts', 'updated_at')
    # Narrow back only when no recorded ID needs the extra width; otherwise the
    # column stays at 128 rather than truncating a member's entitlement IDs.
    bind = op.get_bind()
    if bind.dialect.name != 'sqlite' and sa.inspect(bind).has_table('user_owned_titles'):
        longest = bind.execute(sa.text('SELECT MAX(LENGTH(external_app_id)) FROM user_owned_titles')).scalar()
        if (longest or 0) <= 32:
            _widen_external_app_id(bind, 32)
