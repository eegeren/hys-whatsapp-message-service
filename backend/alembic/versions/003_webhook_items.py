"""Durable, independently deduplicated webhook message/status records."""
from alembic import op
import sqlalchemy as sa
revision='003'
down_revision='002'
branch_labels=None
depends_on=None
def upgrade():
    op.create_table('webhook_items',sa.Column('id',sa.String(64),primary_key=True),sa.Column('kind',sa.String(20),nullable=False),sa.Column('phone_number_id',sa.String(40),nullable=False),sa.Column('meta_id',sa.String(200),nullable=False),sa.Column('payload',sa.Text(),nullable=False),sa.Column('created',sa.DateTime(),nullable=False))
    op.create_index('ix_webhook_items_meta_id','webhook_items',['meta_id'])
def downgrade():
    op.drop_index('ix_webhook_items_meta_id',table_name='webhook_items')
    op.drop_table('webhook_items')
