"""Disable staff access without deleting historical records."""
from alembic import op
import sqlalchemy as sa
revision='007'
down_revision='006'
branch_labels=None
depends_on=None
def upgrade():op.add_column('users',sa.Column('active',sa.Boolean(),nullable=False,server_default=sa.true()))
def downgrade():op.drop_column('users','active')
