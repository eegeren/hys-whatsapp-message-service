"""Add isolated staff announcement records; retain all existing tables and data."""
from alembic import op
import sqlalchemy as sa
revision='004'
down_revision='003'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('staff_announcements',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('owner_id',sa.Integer(),sa.ForeignKey('users.id'),nullable=False),sa.Column('name',sa.String(200),nullable=False),sa.Column('status',sa.String(30),nullable=False),sa.Column('config',sa.Text(),nullable=False),sa.Column('preview_token',sa.String(64),nullable=False),sa.Column('preview_expires',sa.DateTime(),nullable=True),sa.Column('simulation',sa.Boolean(),nullable=False),sa.Column('sender_id',sa.String(40),nullable=False),sa.Column('created',sa.DateTime(),nullable=False))
    op.create_table('staff_assets',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('announcement_id',sa.Integer(),sa.ForeignKey('staff_announcements.id'),nullable=False),sa.Column('position',sa.Integer(),nullable=False),sa.Column('filename',sa.String(200),nullable=False),sa.Column('kind',sa.String(20),nullable=False),sa.Column('content_type',sa.String(40),nullable=False),sa.Column('content',sa.LargeBinary(),nullable=True),sa.Column('size',sa.Integer(),nullable=False),sa.Column('digest',sa.String(64),nullable=False),sa.Column('media_id',sa.String(100),nullable=False),sa.Column('expires',sa.DateTime(),nullable=False),sa.UniqueConstraint('announcement_id','position'))
    op.create_table('staff_deliveries',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('announcement_id',sa.Integer(),sa.ForeignKey('staff_announcements.id'),nullable=False),sa.Column('contact_id',sa.Integer(),sa.ForeignKey('contacts.id'),nullable=False),sa.Column('asset_id',sa.Integer(),sa.ForeignKey('staff_assets.id'),nullable=False),sa.Column('phone',sa.String(20),nullable=False),sa.Column('name',sa.String(200),nullable=False),sa.Column('store',sa.String(160),nullable=False),sa.Column('status',sa.String(30),nullable=False),sa.Column('meta_id',sa.String(200),unique=True,nullable=True),sa.Column('error',sa.Text(),nullable=False),sa.Column('attempted',sa.DateTime(),nullable=True),sa.UniqueConstraint('announcement_id','contact_id','asset_id'))

    op.create_index('ix_staff_delivery_queue','staff_deliveries',['status','announcement_id'])

def downgrade():
    op.drop_table('staff_deliveries');op.drop_table('staff_assets');op.drop_table('staff_announcements')
