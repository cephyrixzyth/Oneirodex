"""Add per-member original-room-game progress and optimistic revisions."""
from alembic import op
import sqlalchemy as sa

revision = '6a7b8c9d0e1f'
down_revision = '25b9de680b91'
branch_labels = None
depends_on = None


def upgrade():
    # startweb creates current ORM tables before adopting the Alembic baseline.
    if sa.inspect(op.get_bind()).has_table('room_game_progress'):
        return
    op.create_table(
        'room_game_progress',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('game_id', sa.String(length=64), primary_key=True),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('state', sa.JSON(none_as_null=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table('room_game_progress')
