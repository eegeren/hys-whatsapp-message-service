"""Optional conversation management; no historical attribution or data replacement."""
from alembic import op
import sqlalchemy as sa
revision='008'
down_revision='007'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('conversation_ops',sa.Column('key',sa.String(64),primary_key=True),sa.Column('phone',sa.String(20),nullable=False,unique=True),sa.Column('assignee_id',sa.Integer(),sa.ForeignKey('users.id'),nullable=True),sa.Column('status',sa.String(30),nullable=True),sa.Column('store_id',sa.Integer(),sa.ForeignKey('stores.id'),nullable=True),sa.Column('store_linked',sa.Boolean(),nullable=False,server_default=sa.false()),sa.Column('customer_name',sa.String(200),nullable=True),sa.Column('tags',sa.Text(),nullable=False,server_default='[]'),sa.Column('version',sa.Integer(),nullable=False,server_default='0'),sa.Column('updated',sa.DateTime(),nullable=False))
    for field in ['assignee_id','status','store_id']:op.create_index('ix_conversation_ops_'+field,'conversation_ops',[field])
    op.create_table('internal_notes',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('conversation_key',sa.String(64),sa.ForeignKey('conversation_ops.key'),nullable=False),sa.Column('author_id',sa.Integer(),sa.ForeignKey('users.id'),nullable=False),sa.Column('body',sa.Text(),nullable=False),sa.Column('created',sa.DateTime(),nullable=False),sa.Column('deleted',sa.Boolean(),nullable=False,server_default=sa.false()))
    op.create_index('ix_internal_notes_conversation_key','internal_notes',['conversation_key'])
    op.create_table('operation_events',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('actor_id',sa.Integer(),sa.ForeignKey('users.id'),nullable=True),sa.Column('action',sa.String(60),nullable=False),sa.Column('conversation_key',sa.String(64),nullable=True),sa.Column('store_id',sa.Integer(),sa.ForeignKey('stores.id'),nullable=True),sa.Column('old_value',sa.Text(),nullable=False,server_default='{}'),sa.Column('new_value',sa.Text(),nullable=False,server_default='{}'),sa.Column('created',sa.DateTime(),nullable=False))
    for field in ['actor_id','action','conversation_key','created']:op.create_index('ix_operation_events_'+field,'operation_events',[field])
    op.create_table('operator_scopes',sa.Column('user_id',sa.Integer(),sa.ForeignKey('users.id'),primary_key=True),sa.Column('store_ids',sa.Text(),nullable=False,server_default='[]'),sa.Column('include_unassigned',sa.Boolean(),nullable=False,server_default=sa.false()),sa.Column('unrestricted',sa.Boolean(),nullable=False,server_default=sa.false()))
    # Batch mode also works on SQLite; existing rows retain NULL attribution.
    with op.batch_alter_table('messages') as batch:
        batch.add_column(sa.Column('sender_user_id',sa.Integer(),nullable=True))
        batch.add_column(sa.Column('operation_store_id',sa.Integer(),nullable=True))
        batch.create_foreign_key('fk_messages_sender_user_id','users',['sender_user_id'],['id'])
        batch.create_foreign_key('fk_messages_operation_store_id','stores',['operation_store_id'],['id'])
        batch.create_index('ix_messages_sender_user_id',['sender_user_id'])

def downgrade():
    raise RuntimeError('Operations history is retained. Restore from a verified backup for rollback; no destructive automatic downgrade.')
