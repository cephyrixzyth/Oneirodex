"""Keep a reversible librarian decision on a scan result."""
from alembic import op
import sqlalchemy as sa

revision = 'c32e745ddc12'
down_revision = 'b8d2ae5c6113'
branch_labels = None
depends_on = None


def upgrade():
    if not sa.inspect(op.get_bind()).has_table('catalog_match_reviews'):
        op.create_table('catalog_match_reviews',
            sa.Column('library_uuid', sa.String(36), sa.ForeignKey('libraries.uuid', ondelete='CASCADE'), primary_key=True),
            sa.Column('source_key', sa.String(64), primary_key=True),
            sa.Column('decision', sa.JSON(), nullable=False))
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('unmatched_folders')}
    if 'review_decision' not in columns:
        op.add_column('unmatched_folders', sa.Column('review_decision', sa.JSON(), nullable=True))


def downgrade():
    op.drop_table('catalog_match_reviews')
    op.drop_column('unmatched_folders', 'review_decision')
