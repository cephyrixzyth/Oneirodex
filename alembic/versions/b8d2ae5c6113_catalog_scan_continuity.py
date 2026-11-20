"""Persist scan intentions, root identity and script-aware catalog title keys."""
from alembic import op
import sqlalchemy as sa

revision = 'b8d2ae5c6113'
down_revision = 'a4b5c6d7e8f9'
branch_labels = None
depends_on = None


def upgrade():
    from oneirodex.utils.title_grouping import normalize_title

    bind = op.get_bind()
    additions = {
        'scan_jobs': [
            sa.Column('setting_fetch_hltb', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('setting_force_hltb_refetch', sa.Boolean(), nullable=False, server_default=sa.false()),
        ],
        'libraries': [sa.Column('last_scan_root_identity', sa.String(96))],
        'games': [sa.Column('browse_title_key', sa.Text())],
        'user_deletion_file_jobs': [sa.Column('image_identity', sa.String(128))],
    }
    for table, columns in additions.items():
        existing = {item['name'] for item in sa.inspect(bind).get_columns(table)}
        for column in columns:
            if column.name not in existing:
                op.add_column(table, column)
    after = 0
    while True:
        rows = bind.execute(sa.text(
            'SELECT id, name FROM games WHERE id > :after AND browse_title_key IS NULL ORDER BY id LIMIT 1000'
        ), {'after': after}).all()
        if not rows:
            break
        bind.execute(sa.text('UPDATE games SET browse_title_key = :key WHERE id = :id'),
                     [{'key': normalize_title(row.name), 'id': row.id} for row in rows])
        after = rows[-1].id
    op.create_index(
        'ix_games_browse_title_key', 'games', ['browse_title_key'],
        if_not_exists=True, postgresql_using='hash',
    )


def downgrade():
    op.drop_index('ix_games_browse_title_key', table_name='games')
    op.drop_column('user_deletion_file_jobs', 'image_identity')
    op.drop_column('games', 'browse_title_key')
    op.drop_column('libraries', 'last_scan_root_identity')
    op.drop_column('scan_jobs', 'setting_force_hltb_refetch')
    op.drop_column('scan_jobs', 'setting_fetch_hltb')
