"""tasmota locked relays

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-18 14:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('tasmota_devices') as batch_op:
        batch_op.add_column(sa.Column('locked_relays', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('tasmota_devices') as batch_op:
        batch_op.drop_column('locked_relays')
