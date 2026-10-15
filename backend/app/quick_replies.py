"""Local quick replies: editable drafts, never Meta templates or automatic sends."""
import re
from fastapi import Depends,HTTPException
from pydantic import BaseModel,Field,field_validator
from sqlalchemy import select,or_,update
from app.core import QuickReply,User,audit
from app.main import app,actor,admin,db_session

DEFAULT_REPLIES=[
 ('Karşılama','Merhaba, ben HYS müşteri temsilciniz {{personel_adi}}. 😊 Size nasıl yardımcı olabilirim?'),
 ('Konum Sorma','Hangi il ve ilçede yaşıyorsunuz? 📍 Size en yakın HYS mağazasını birlikte belirleyelim.'),
 ('Mağaza Bilgilendirme','Size en yakın HYS mağazamızın adresini ve iletişim bilgilerini paylaşmaktan memnuniyet duyarız.'),
 ('Ürün Bilgilendirme','İlgilendiğiniz ürünün marka veya modelini paylaşabilir misiniz? Size yardımcı olalım. 😊'),
 ('Stok Bilgilendirme','İlgilendiğiniz ürünün stok durumunu ilgili mağazamızdan kontrol ederek size bilgi verebiliriz.'),
 ('Teşekkür',"HYS'yi tercih ettiğiniz için teşekkür ederiz. İyi günler dileriz! 🧡"),
]
TOKEN='{{personel_adi}}'
def profile(user):return {'id':user.id,'username':user.username,'display_name':user.display_name or user.username,'role':user.role}
class ProfileInput(BaseModel):
    display_name:str=Field(min_length=1,max_length=100)
    @field_validator('display_name')
    @classmethod
    def name(cls,value):
        value=value.strip()
        if not value or any(ord(c)<32 for c in value) or '{{' in value or '}}' in value:raise ValueError('Geçerli bir görünen ad yazın.')
        return value
@app.patch('/api/profile')
def update_profile(data:ProfileInput,user=Depends(actor),db=Depends(db_session)):
    user.display_name=data.display_name;audit(db,user.username,'profile_update',str(user.id));db.commit()
    return profile(user)
@app.get('/api/quick-replies/users')
def reply_users(user=Depends(admin),db=Depends(db_session)):
    return [profile(u) for u in db.scalars(select(User).order_by(User.username)).all()]

class ReplyInput(BaseModel):
    title:str=Field(min_length=1,max_length=100)
    category:str=Field(min_length=1,max_length=80)
    body:str=Field(min_length=1,max_length=4096)
    owner_id:int|None=Field(default=None,gt=0)
    sort_order:int=Field(default=0,ge=0,le=100000)
    category_order:int=Field(default=0,ge=0,le=100000)
    @field_validator('title','category','body')
    @classmethod
    def clean(cls,value,info):
        value=value.strip()
        if not value:raise ValueError('Bu alan boş bırakılamaz.')
        if info.field_name=='body':
            rest=value.replace(TOKEN,'')
            if '{{' in rest or '}}' in rest:raise ValueError('Yalnızca {{personel_adi}} değişkeni kullanılabilir.')
            if len(value.replace(TOKEN,'x'*100))>4096:raise ValueError('Ad değişkenleri eklendiğinde mesaj 4096 karakteri aşamaz.')
        return value

def employee_name(user):
    # Account creation stores the staff member's name; use its first part in greetings.
    name=(user.display_name or '').strip()
    if name:return name.split()[0]
    return re.split(r'[._\s-]+',user.username.strip())[0]

def describe(row,user):
    return {'id':row.id,'title':row.title,'category':row.category,'body':row.body,'rendered_body':row.body.replace(TOKEN,employee_name(user)),'owner_id':row.owner_id,'sort_order':row.sort_order,'category_order':row.category_order}
def ordered():return select(QuickReply).order_by(QuickReply.category_order,QuickReply.category,QuickReply.sort_order,QuickReply.id)
@app.get('/api/quick-replies')
def replies(manage:bool=False,user=Depends(actor),db=Depends(db_session)):
    if manage and user.role!='admin':raise HTTPException(403,'Hazır yanıt yönetimi için yönetici yetkisi gerekiyor.')
    stmt=ordered()
    if not manage:stmt=stmt.where(or_(QuickReply.owner_id.is_(None),QuickReply.owner_id==user.id))
    return [describe(r,user) for r in db.scalars(stmt).all()]

def check_owner(db,owner_id):
    if owner_id is not None and not db.get(User,owner_id):raise HTTPException(422,'Seçilen personel bulunamadı.')
@app.post('/api/quick-replies',status_code=201)
def create_reply(data:ReplyInput,user=Depends(admin),db=Depends(db_session)):
    check_owner(db,data.owner_id);row=QuickReply(**data.model_dump());db.add(row);db.flush();db.execute(update(QuickReply).where(QuickReply.category==data.category).values(category_order=data.category_order));audit(db,user.username,'quick_reply_create',str(row.id));db.commit()
    return describe(row,user)
@app.put('/api/quick-replies/{reply_id}')
def update_reply(reply_id:int,data:ReplyInput,user=Depends(admin),db=Depends(db_session)):
    row=db.get(QuickReply,reply_id)
    if not row:raise HTTPException(404,'Hazır yanıt bulunamadı.')
    check_owner(db,data.owner_id)
    for key,value in data.model_dump().items():setattr(row,key,value)
    db.execute(update(QuickReply).where(QuickReply.category==data.category).values(category_order=data.category_order))
    audit(db,user.username,'quick_reply_update',str(row.id));db.commit()
    return describe(row,user)
@app.delete('/api/quick-replies/{reply_id}')
def delete_reply(reply_id:int,user=Depends(admin),db=Depends(db_session)):
    row=db.get(QuickReply,reply_id)
    if not row:raise HTTPException(404,'Hazır yanıt bulunamadı.')
    db.delete(row);audit(db,user.username,'quick_reply_delete',str(reply_id));db.commit();return {'ok':True}
class ReplyOrder(BaseModel):ids:list[int]=Field(min_length=1,max_length=1000)
@app.post('/api/quick-replies/reorder')
def reorder_replies(data:ReplyOrder,user=Depends(admin),db=Depends(db_session)):
    if len(set(data.ids))!=len(data.ids):raise HTTPException(422,'Sıralamada yinelenen yanıt var.')
    rows=db.scalars(select(QuickReply).where(QuickReply.id.in_(data.ids)).with_for_update()).all()
    if len(rows)!=len(data.ids):raise HTTPException(409,'Yanıt listesi değişmiş. Listeyi yenileyin.')
    lookup={r.id:r for r in rows}
    for position,id in enumerate(data.ids):lookup[id].sort_order=position
    audit(db,user.username,'quick_reply_reorder',str(len(rows)));db.commit();return {'ok':True}
