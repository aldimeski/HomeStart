"""skoda accounts and vehicle cache

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-20 10:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'skoda_accounts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('username_enc', sa.Text(), nullable=False),
        sa.Column('password_enc', sa.Text(), nullable=False),
        sa.Column('refresh_token_enc', sa.Text(), nullable=True),
        sa.Column('last_sync', sa.DateTime(), nullable=True),
        sa.Column('last_attempt', sa.DateTime(), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id'),
    )
    op.create_table(
        'vehicles_cache',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('vin', sa.String(length=17), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=True),
        sa.Column('data_json', sa.Text(), nullable=False),
        sa.Column('image_file', sa.String(length=80), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['skoda_accounts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('account_id', 'vin'),
    )


def downgrade() -> None:
    op.drop_table('vehicles_cache')
    op.drop_table('skoda_accounts')
