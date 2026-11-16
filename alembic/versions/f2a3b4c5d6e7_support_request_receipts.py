"""Add durable per-account support request receipts.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
"""
from alembic import op
import sqlalchemy as sa

revision = 'f2a3b4c5d6e7'
down_revision = 'e1f2a3b4c5d6'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    columns = {c['name'] for c in inspector.get_columns('support_tickets')}
    for name, size in [('request_id', 36), ('request_hash', 64), ('github_attempt_id', 36)]:
        if name not in columns:
            op.add_column('support_tickets', sa.Column(name, sa.String(size), nullable=True))
    indexes = {index['name']: index for index in sa.inspect(op.get_bind()).get_indexes('support_tickets')}
    constraints = {c['name'] for c in sa.inspect(op.get_bind()).get_unique_constraints('support_tickets')}
    if 'uq_support_ticket_user_request' not in constraints:
        index = indexes.get('uq_support_ticket_user_request')
        if index is not None:
            if not index.get('unique') or index.get('column_names') != ['user_id', 'request_id']:
                raise RuntimeError('Support receipt index does not match the expected account/request key.')
            op.execute(sa.text('ALTER TABLE support_tickets ADD CONSTRAINT uq_support_ticket_user_request '
                               'UNIQUE USING INDEX uq_support_ticket_user_request'))
        else:
            op.create_unique_constraint('uq_support_ticket_user_request', 'support_tickets', ['user_id', 'request_id'])


def downgrade():
    receipts = op.get_bind().execute(sa.text(
        'SELECT 1 FROM support_tickets WHERE request_id IS NOT NULL '
        'OR request_hash IS NOT NULL OR github_attempt_id IS NOT NULL LIMIT 1'
    )).first()
    if receipts is not None:
        raise RuntimeError('Support request receipts exist; restore a pre-upgrade backup instead of deleting delivery history.')
    inspector = sa.inspect(op.get_bind())
    indexes = {index['name'] for index in inspector.get_indexes('support_tickets')}
    if 'uq_support_ticket_user_request' in {c['name'] for c in inspector.get_unique_constraints('support_tickets')}:
        op.drop_constraint('uq_support_ticket_user_request', 'support_tickets', type_='unique')
    elif 'uq_support_ticket_user_request' in indexes:
        op.drop_index('uq_support_ticket_user_request', table_name='support_tickets')
    for name in ['github_attempt_id', 'request_hash', 'request_id']:
        op.drop_column('support_tickets', name)
