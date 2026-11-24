"""player: playlists and the openpanel content

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-25 09:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'playlists',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_playlists_user_id', 'playlists', ['user_id'])
    op.create_table(
        'playlist_tracks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('playlist_id', sa.Integer(), nullable=False),
        sa.Column('track_id', sa.Integer(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['playlist_id'], ['playlists.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['track_id'], ['music_tracks.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_playlist_tracks_playlist_id', 'playlist_tracks', ['playlist_id'])
    op.create_index('ix_playlist_tracks_track_id', 'playlist_tracks', ['track_id'])
    op.create_table(
        'panel_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('section', sa.String(length=12), nullable=False),
        sa.Column('kind', sa.String(length=8), nullable=False),
        sa.Column('ref', sa.String(length=1100), nullable=False),
        sa.Column('title', sa.String(length=64), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('section', 'kind', 'ref'),
    )


def downgrade() -> None:
    op.drop_table('panel_items')
    op.drop_table('playlist_tracks')
    op.drop_table('playlists')
