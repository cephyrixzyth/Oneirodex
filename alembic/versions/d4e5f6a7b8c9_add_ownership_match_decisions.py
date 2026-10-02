"""Add reversible member ownership decisions without rewriting existing matches."""
from alembic import op
import sqlalchemy as sa

revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {c['name'] for c in sa.inspect(bind).get_columns('user_owned_titles')}
    if 'match_revision' not in columns:
        op.add_column('user_owned_titles', sa.Column('match_revision', sa.Integer(), nullable=False, server_default='0'))
    if 'match_reviewed' not in columns:
        op.add_column('user_owned_titles', sa.Column('match_reviewed', sa.Boolean(), nullable=False, server_default=sa.false()))
    if not sa.inspect(bind).has_table('ownership_match_decisions'):
        op.create_table('ownership_match_decisions',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('title_id', sa.Integer(), sa.ForeignKey('user_owned_titles.id', ondelete='CASCADE'), nullable=False),
            sa.Column('revision', sa.Integer(), nullable=False),
            sa.Column('actor_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('before_uuid', sa.String(36)),
            sa.Column('after_uuid', sa.String(36)),
            sa.Column('before_reviewed', sa.Boolean(), nullable=False),
            sa.Column('action', sa.String(16), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.UniqueConstraint('title_id', 'revision', name='uq_ownership_match_revision'))
        op.create_index('ix_ownership_match_decisions_title_id', 'ownership_match_decisions', ['title_id'])


def downgrade():
    # Explicit rollback discards the journal; export it before downgrading.
    if sa.inspect(op.get_bind()).has_table('ownership_match_decisions'):
        op.drop_table('ownership_match_decisions')
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('user_owned_titles')}
    for name in ('match_reviewed', 'match_revision'):
        if name in columns:
            op.drop_column('user_owned_titles', name)
