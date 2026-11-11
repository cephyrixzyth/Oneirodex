"""Retain delivery attempt identity, destination and safe retry metadata.

Revision ID: a4b5c6d7e8f9
Revises: f2a3b4c5d6e7
"""
from alembic import op
import sqlalchemy as sa

revision = 'a4b5c6d7e8f9'
down_revision = 'f2a3b4c5d6e7'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {c['name'] for c in sa.inspect(bind).get_columns('support_tickets')}
    additions = [sa.Column('github_repository', sa.String(140), nullable=True),
                 sa.Column('github_last_status', sa.Integer(), nullable=True),
                 sa.Column('github_retry_after_at', sa.DateTime(timezone=True), nullable=True)]
    for column in additions:
        if column.name not in columns:
            op.add_column('support_tickets', column)
    if 'support_delivery_attempts' not in sa.inspect(bind).get_table_names():
        op.create_table('support_delivery_attempts',
            sa.Column('id', sa.String(36), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('ticket_id', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('repository', sa.String(140), nullable=False),
            sa.Column('payload_sha256', sa.String(64), nullable=False),
            sa.Column('outcome', sa.String(16), nullable=False),
            sa.Column('http_status', sa.Integer(), nullable=True),
            sa.Column('retry_after_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('issue_number', sa.Integer(), nullable=True),
            sa.Column('issue_url', sa.String(512), nullable=True),
            sa.PrimaryKeyConstraint('id', 'user_id'),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['ticket_id'], ['support_tickets.id'], ondelete='CASCADE'),
        )
    indexes = {index['name'] for index in sa.inspect(bind).get_indexes('support_delivery_attempts')}
    for name, fields in [('ix_support_delivery_attempts_user_created', ['user_id', 'created_at']),
                         ('ix_support_delivery_attempts_ticket_id', ['ticket_id'])]:
        if name not in indexes:
            op.create_index(name, 'support_delivery_attempts', fields)
    if 'support_delivery_check_budgets' not in sa.inspect(bind).get_table_names():
        op.create_table('support_delivery_check_budgets',
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('window_started_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('count', sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint('user_id'),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        )


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text('SELECT 1 FROM support_delivery_attempts LIMIT 1')).first() is not None:
        raise RuntimeError('Support delivery receipts exist; restore a pre-upgrade backup instead of deleting history.')
    op.drop_table('support_delivery_attempts')
    op.drop_table('support_delivery_check_budgets')
    for column in ['github_retry_after_at', 'github_last_status', 'github_repository']:
        op.drop_column('support_tickets', column)
