"""player: album covers and online metadata

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-24 23:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None

# Plain ADD COLUMN, not batch mode: batch mode rebuilds the table, and dropping the old music_albums would set the
# album_id of every track to NULL (ON DELETE SET NULL) when foreign keys are enforced.


def upgrade() -> None:
    op.add_column('music_albums', sa.Column('cover_file', sa.String(length=64), nullable=True))
    op.add_column('music_albums', sa.Column('cover_source', sa.String(length=16), nullable=True))
    op.add_column('music_albums', sa.Column('cover_checked', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('music_albums', sa.Column('meta_status', sa.String(length=12), nullable=False, server_default='pending'))
    op.add_column('music_albums', sa.Column('meta_checked_at', sa.DateTime(), nullable=True))
    op.add_column('music_albums', sa.Column('mb_release_id', sa.String(length=36), nullable=True))


def downgrade() -> None:
    for column in ('mb_release_id', 'meta_checked_at', 'meta_status', 'cover_checked', 'cover_source', 'cover_file'):
        op.drop_column('music_albums', column)
