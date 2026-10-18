"""tasmota relay names

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-18 13:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('tasmota_devices') as batch_op:
        batch_op.add_column(sa.Column('relay_names', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('tasmota_devices') as batch_op:
        batch_op.drop_column('relay_names')
