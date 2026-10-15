"""Shared authorization for operations and existing customer entry points."""
import hashlib,json
from fastapi import Depends,HTTPException,Request
from sqlalchemy import select,exists,and_,or_,not_,true,literal
from sqlalchemy.orm import aliased
from app.core import Message,Contact,Store,ConversationOps,OperatorScope
from app.main import actor,db_session

def key_for(phone):return hashlib.sha256(phone.encode()).hexdigest()
def scope_for(db,user):return None if user.role=='admin' else db.get(OperatorScope,user.id)
def phone_clause(db,user,column):
    scope=scope_for(db,user)
    if scope is None or scope.unrestricted:return true()
    ids=json.loads(scope.store_ids);op=aliased(ConversationOps);c=aliased(Contact);s=aliased(Store)
    explicit=exists(select(op.key).where(op.phone==column,op.store_linked==True))
    override=exists(select(op.key).where(op.phone==column,op.store_linked==True,or_(op.store_id.in_(ids),and_(op.store_id.is_(None),literal(scope.include_unassigned)))))
    recognized=exists(select(c.id).join(s,c.store==s.name).where(c.phone==column,c.kind=='customer'))
    inherited=exists(select(c.id).join(s,c.store==s.name).where(c.phone==column,c.kind=='customer',s.id.in_(ids)))
    return or_(override,and_(not_(explicit),or_(inherited,and_(not_(recognized),literal(scope.include_unassigned)))))
def store_for(db,phone):
    op=db.scalar(select(ConversationOps).where(ConversationOps.phone==phone))
    if op and op.store_linked:return op.store_id
    return db.scalar(select(Store.id).join(Contact,Contact.store==Store.name).where(Contact.phone==phone,Contact.kind=='customer').order_by(Contact.id).limit(1))
def allowed_store(db,user,store_id):
    scope=scope_for(db,user)
    return scope is None or scope.unrestricted or (store_id in json.loads(scope.store_ids) if store_id is not None else scope.include_unassigned)
def authorize_phone(db,user,phone,manage=False):
    if not allowed_store(db,user,store_for(db,phone)):raise HTTPException(403,'Bu mağazanın gelen kutusuna erişim yetkiniz yok.')
    case=db.scalar(select(ConversationOps).where(ConversationOps.phone==phone))
    if manage and case and case.assignee_id not in (None,user.id) and user.role!='admin':raise HTTPException(403,'Bu sohbet başka personele atanmış. Yalnızca sorumlu personel veya yönetici işlem yapabilir.')
    return case
def phone_for_key(db,key):
    case=db.get(ConversationOps,key)
    if case:return case.phone
    # Keep the existing normalized-phone hash identity; never invent historical cases.
    for phone in db.scalars(select(Message.phone).distinct()):
        if key_for(phone)==key:return phone
    raise HTTPException(404,'Konuşma bulunamadı.')
async def guard_direct(request:Request,user=Depends(actor),db=Depends(db_session)):
    from app.core import phone as normalize
    try:
        if request.url.path.endswith('send-with-media'):data=json.loads((await request.form()).get('data','{}'))
        else:data=await request.json()
        if not isinstance(data,dict):return
        # Match the existing sender's resolution exactly. Metadata can outlive messages;
        # never authorize a stale metadata key and then let the sender fall back to another phone.
        recipient=next((p for p in db.scalars(select(Message.phone).distinct()) if key_for(p)==data.get('conversation_key')),None) if data.get('conversation_key') else None
        if recipient is None:recipient=normalize(data.get('phone',''))
    except (ValueError,TypeError,KeyError):return # Existing validation owns malformed payload errors.
    authorize_phone(db,user,recipient,True)
    db.info['ops_actor_id']=user.id;db.info['ops_store_id']=store_for(db,recipient)
def guard_message(request:Request,id:int,user=Depends(actor),db=Depends(db_session)):
    row=db.get(Message,id)
    if row:authorize_phone(db,user,row.phone,request.url.path.endswith('/reply'));db.info.update(ops_actor_id=user.id,ops_store_id=store_for(db,row.phone))
def guard_media(message_id:int,user=Depends(actor),db=Depends(db_session)):
    row=db.get(Message,message_id)
    if row:authorize_phone(db,user,row.phone)
