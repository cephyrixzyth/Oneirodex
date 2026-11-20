"""Record when a scan run finished."""
from alembic import op
import sqlalchemy as sa

revision = '25b9de680b91'
down_revision = 'c32e745ddc12'
branch_labels = None
depends_on = None


def upgrade():
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('scan_jobs')}
    if 'finished_at' not in columns:
        op.add_column('scan_jobs', sa.Column('finished_at', sa.DateTime(), nullable=True))
        # Finished runs before this column: their last progress update is the best record.
        op.execute(
            "UPDATE scan_jobs SET finished_at = last_progress_update "
            "WHERE status IN ('Completed', 'Failed', 'Cancelled')"
        )


def downgrade():
    op.drop_column('scan_jobs', 'finished_at')
