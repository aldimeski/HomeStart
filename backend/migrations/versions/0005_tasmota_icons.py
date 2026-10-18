"""tasmota device and relay icons

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-18 17:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('tasmota_devices') as batch_op:
        batch_op.add_column(sa.Column('icon', sa.String(length=160), nullable=True))
        batch_op.add_column(sa.Column('relay_icons', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('tasmota_devices') as batch_op:
        batch_op.drop_column('relay_icons')
        batch_op.drop_column('icon')
