"""Separate, confirmation-bound test sends."""
from alembic import op
import sqlalchemy as sa
revision='002'
down_revision='001'
branch_labels=None
depends_on=None
def upgrade():
    op.create_table('test_messages',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('user_id',sa.Integer(),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('recipient',sa.String(20),nullable=False),
        sa.Column('phone_number_id',sa.String(40),nullable=False),
        sa.Column('confirmation_hash',sa.String(64),nullable=False),
        sa.Column('config_hash',sa.String(64),nullable=False),
        sa.Column('expires',sa.DateTime(),nullable=False),
        sa.Column('status',sa.String(30),nullable=False),
        sa.Column('delivery_status',sa.String(30),nullable=False),
        sa.Column('meta_id',sa.String(200),unique=True,nullable=True),
        sa.Column('api_response',sa.Text(),nullable=False),
        sa.Column('error_code',sa.String(30),nullable=False),
        sa.Column('error',sa.Text(),nullable=False),
        sa.Column('created',sa.DateTime(),nullable=False),
        sa.Column('attempted',sa.DateTime(),nullable=True))
def downgrade():op.drop_table('test_messages')
