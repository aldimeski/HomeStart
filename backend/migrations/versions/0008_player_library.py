"""player library: locations, albums, tracks and scans

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-24 21:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'music_sources',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('kind', sa.String(length=8), nullable=False),
        sa.Column('path', sa.Text(), nullable=True),
        sa.Column('host', sa.String(length=255), nullable=True),
        sa.Column('share', sa.String(length=255), nullable=True),
        sa.Column('subpath', sa.Text(), nullable=True),
        sa.Column('domain', sa.String(length=255), nullable=True),
        sa.Column('username_enc', sa.Text(), nullable=True),
        sa.Column('password_enc', sa.Text(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('last_scan_at', sa.DateTime(), nullable=True),
        sa.Column('last_scan_status', sa.String(length=16), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_table(
        'music_albums',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('album_key', sa.String(length=600), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('artist', sa.String(length=255), nullable=False),
        sa.Column('year', sa.Integer(), nullable=True),
        sa.Column('genre', sa.String(length=128), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('album_key'),
    )
    op.create_table(
        'music_tracks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source_id', sa.Integer(), nullable=False),
        sa.Column('rel_path', sa.Text(), nullable=False),
        sa.Column('folder', sa.Text(), nullable=False),
        sa.Column('size', sa.Integer(), nullable=False),
        sa.Column('mtime', sa.Integer(), nullable=False),
        sa.Column('format', sa.String(length=8), nullable=False),
        sa.Column('duration_s', sa.Float(), nullable=True),
        sa.Column('bitrate', sa.Integer(), nullable=True),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('artist', sa.String(length=255), nullable=False),
        sa.Column('album_artist', sa.String(length=255), nullable=True),
        sa.Column('album_id', sa.Integer(), nullable=True),
        sa.Column('track_no', sa.Integer(), nullable=True),
        sa.Column('disc_no', sa.Integer(), nullable=True),
        sa.Column('year', sa.Integer(), nullable=True),
        sa.Column('genre', sa.String(length=128), nullable=True),
        sa.Column('tags_derived', sa.Boolean(), nullable=False),
        sa.Column('available', sa.Boolean(), nullable=False),
        sa.Column('missing_since', sa.DateTime(), nullable=True),
        sa.Column('search_text', sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(['source_id'], ['music_sources.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['album_id'], ['music_albums.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source_id', 'rel_path'),
    )
    op.create_index('ix_music_tracks_folder', 'music_tracks', ['source_id', 'folder'])
    op.create_index('ix_music_tracks_album_id', 'music_tracks', ['album_id'])
    op.create_index('ix_music_tracks_genre', 'music_tracks', ['genre'])
    op.create_table(
        'music_scans',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source_id', sa.Integer(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('started_by', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('added', sa.Integer(), nullable=False),
        sa.Column('changed', sa.Integer(), nullable=False),
        sa.Column('removed', sa.Integer(), nullable=False),
        sa.Column('errors', sa.Integer(), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('details_json', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['source_id'], ['music_sources.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['started_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_music_scans_source_id', 'music_scans', ['source_id'])


def downgrade() -> None:
    op.drop_table('music_scans')
    op.drop_table('music_tracks')
    op.drop_table('music_albums')
    op.drop_table('music_sources')
