"""Persistent quick replies and staff display names; preserve all existing data."""
from alembic import op
import sqlalchemy as sa
revision='006'
down_revision='005'
branch_labels=None
depends_on=None

# Fixed seed data, independent of future application code.
DEFAULTS=[('Karşılama','Merhaba, ben HYS müşteri temsilciniz {{personel_adi}}. 😊 Size nasıl yardımcı olabilirim?'),('Konum Sorma','Hangi il ve ilçede yaşıyorsunuz? 📍 Size en yakın HYS mağazasını birlikte belirleyelim.'),('Mağaza Bilgilendirme','Size en yakın HYS mağazamızın adresini ve iletişim bilgilerini paylaşmaktan memnuniyet duyarız.'),('Ürün Bilgilendirme','İlgilendiğiniz ürünün marka veya modelini paylaşabilir misiniz? Size yardımcı olalım. 😊'),('Stok Bilgilendirme','İlgilendiğiniz ürünün stok durumunu ilgili mağazamızdan kontrol ederek size bilgi verebiliriz.'),('Teşekkür',"HYS'yi tercih ettiğiniz için teşekkür ederiz. İyi günler dileriz! 🧡")]
def upgrade():
    op.add_column('users',sa.Column('display_name',sa.String(100),nullable=False,server_default=''))
    op.execute(sa.text("UPDATE users SET display_name = username WHERE display_name = ''"))
    op.create_table('quick_replies',sa.Column('id',sa.Integer(),primary_key=True),sa.Column('title',sa.String(100),nullable=False),sa.Column('category',sa.String(80),nullable=False),sa.Column('body',sa.Text(),nullable=False),sa.Column('owner_id',sa.Integer(),sa.ForeignKey('users.id'),nullable=True),sa.Column('sort_order',sa.Integer(),nullable=False,server_default='0'),sa.Column('category_order',sa.Integer(),nullable=False,server_default='0'))
    op.create_index('ix_quick_replies_owner_id','quick_replies',['owner_id'])
    table=sa.table('quick_replies',sa.column('title',sa.String),sa.column('category',sa.String),sa.column('body',sa.Text),sa.column('sort_order',sa.Integer),sa.column('category_order',sa.Integer))
    op.bulk_insert(table,[{'title':title,'category':title,'body':body,'sort_order':0,'category_order':i} for i,(title,body) in enumerate(DEFAULTS)])
def downgrade():
    op.drop_table('quick_replies')
    op.drop_column('users','display_name')
