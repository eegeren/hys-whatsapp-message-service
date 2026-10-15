"""Durable private video preprocessing queue; existing data is preserved."""
from alembic import op
import sqlalchemy as sa
revision='005'
down_revision='004'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('video_jobs',sa.Column('id',sa.String(36),primary_key=True),sa.Column('owner_id',sa.Integer(),sa.ForeignKey('users.id'),nullable=False),sa.Column('filename',sa.String(200),nullable=False),sa.Column('status',sa.String(30),nullable=False),sa.Column('progress',sa.Integer(),nullable=False),sa.Column('ticket_hash',sa.String(64),nullable=False),sa.Column('source_size',sa.Integer(),nullable=False),sa.Column('output_size',sa.Integer(),nullable=False),sa.Column('source',sa.LargeBinary(),nullable=True),sa.Column('output',sa.LargeBinary(),nullable=True),sa.Column('info',sa.Text(),nullable=False),sa.Column('error_code',sa.String(50),nullable=False),sa.Column('error',sa.Text(),nullable=False),sa.Column('created',sa.DateTime(),nullable=False),sa.Column('updated',sa.DateTime(),nullable=False),sa.Column('expires',sa.DateTime(),nullable=False))
    op.add_column('staff_assets',sa.Column('video_job_id',sa.String(36),nullable=True))
    op.create_index('ix_video_jobs_status','video_jobs',['status'])

def downgrade():
    op.drop_column('staff_assets','video_job_id')
    op.drop_table('video_jobs')
