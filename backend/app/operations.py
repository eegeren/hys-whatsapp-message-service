"""Optional conversation ownership, internal-only notes, store access and real reports."""
import json
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from fastapi import Depends,HTTPException
from pydantic import BaseModel,Field,field_validator
from sqlalchemy import select,update,func,event
from sqlalchemy.orm import Session as SASession
from sqlalchemy.exc import IntegrityError
from app.core import ConversationOps,InternalNote,OperationEvent,OperatorScope,Message,Contact,Store,User,SystemValue,now
from app.main import app,actor,admin,db_session
from app.operations_access import key_for,phone_for_key,authorize_phone,store_for,allowed_store,phone_clause

STATUSES={'new','in_progress','waiting_customer','resolved'}
def record(db,user,action,key=None,store=None,old=None,new=None):
    db.add(OperationEvent(actor_id=user.id if user else None,action=action,conversation_key=key,store_id=store,old_value=json.dumps(old or {},ensure_ascii=False),new_value=json.dumps(new or {},ensure_ascii=False)))
def user_name(db,id):
    u=db.get(User,id) if id else None
    return (u.display_name or u.username) if u else None

def case_row(db,key,create=False):
    row=db.scalar(select(ConversationOps).where(ConversationOps.key==key).with_for_update())
    if row or not create:return row
    phone=phone_for_key(db,key)
    try:
        with db.begin_nested():
            row=ConversationOps(key=key,phone=phone);db.add(row);db.flush()
    except IntegrityError:row=db.scalar(select(ConversationOps).where(ConversationOps.key==key).with_for_update())
    return row

def summary(db,user,phone,row=None):
    row=row or db.scalar(select(ConversationOps).where(ConversationOps.phone==phone));store_id=store_for(db,phone)
    return {'assignee_id':row.assignee_id if row else None,'assignee_name':user_name(db,row.assignee_id) if row else None,'status':row.status if row else None,'store_id':store_id,'store_name':db.get(Store,store_id).name if store_id else None,'version':row.version if row else 0,'can_manage':user.role=='admin' or not row or row.assignee_id in (None,user.id)}

def eligible_people(db,store_id):
    return [{'id':u.id,'name':u.display_name or u.username} for u in db.scalars(select(User).where(User.active==True).order_by(User.username)) if allowed_store(db,u,store_id)]

@app.get('/api/operations/options')
def options(user=Depends(actor),db=Depends(db_session)):
    stores=[{'id':s.id,'name':s.name} for s in db.scalars(select(Store).order_by(Store.name)) if allowed_store(db,user,s.id)]
    # Names only: permissions and private credentials never leave this endpoint.
    people=[{'id':u.id,'name':u.display_name or u.username} for u in db.scalars(select(User).where(User.active==True))]
    return {'stores':stores,'people':people,'statuses':sorted(STATUSES),'user_id':user.id,'admin':user.role=='admin','include_unassigned':allowed_store(db,user,None)}

@app.get('/api/operations/conversations/{key}')
def get_operation(key:str,user=Depends(actor),db=Depends(db_session)):
    phone=phone_for_key(db,key);row=authorize_phone(db,user,phone);data=summary(db,user,phone,row)
    customer=db.scalar(select(Contact).where(Contact.kind=='customer',Contact.phone==phone).order_by(Contact.id))
    stats=db.execute(select(func.count(Message.id),func.max(Message.created)).where(Message.phone==phone)).one()
    notes=[]
    if data['can_manage']:
        notes=[{'id':n.id,'body':n.body,'author_id':n.author_id,'author':user_name(db,n.author_id),'created':n.created.isoformat(),'can_delete':user.role=='admin' or n.author_id==user.id} for n in db.scalars(select(InternalNote).where(InternalNote.conversation_key==key,InternalNote.deleted==False).order_by(InternalNote.id.desc()).limit(200))]
    history=[]
    if data['can_manage']:
        history=[{'id':e.id,'actor':user_name(db,e.actor_id) or 'Sistem','action':e.action,'created':e.created.isoformat(),'old':json.loads(e.old_value),'new':json.loads(e.new_value)} for e in db.scalars(select(OperationEvent).where(OperationEvent.conversation_key==key,OperationEvent.action.in_(['assignment','status','store_change','auto_reopen'])).order_by(OperationEvent.id.desc()).limit(100))]
    return {**data,'history':history,'key':key,'phone':phone,'customer_id':customer.id if customer else None,'customer_name':row.customer_name if row and row.customer_name is not None else (' '.join([customer.first_name,customer.last_name]).strip() if customer else ''),'tags':json.loads(row.tags) if row else [],'message_count':stats[0],'conversation_count':1,'last_contact':stats[1].isoformat() if stats[1] else None,'notes':notes,'people':eligible_people(db,data['store_id']) if data['can_manage'] else []}

class OperationEdit(BaseModel):
    version:int=Field(ge=0)
    assignee_id:int|None=Field(default=None,gt=0)
    status:str|None=None
    customer_name:str|None=Field(default=None,max_length=200)
    store_id:int|None=Field(default=None,gt=0)
    tags:list[str]=Field(default_factory=list,max_length=20)
    @field_validator('status')
    @classmethod
    def status_valid(cls,value):
        if value is not None and value not in STATUSES:raise ValueError('Geçersiz sohbet durumu.')
        return value
    @field_validator('tags')
    @classmethod
    def tag_values(cls,value):
        cleaned=list(dict.fromkeys(t.strip() for t in value if t.strip()))
        if any(len(t)>40 for t in cleaned):raise ValueError('Etiket en fazla 40 karakter olabilir.')
        return cleaned

@app.patch('/api/operations/conversations/{key}')
def edit_operation(key:str,data:OperationEdit,user=Depends(actor),db=Depends(db_session)):
    phone=phone_for_key(db,key);authorize_phone(db,user,phone,True);row=case_row(db,key,True)
    if row.version!=data.version:raise HTTPException(409,'Sohbet başka bir kullanıcı tarafından güncellendi. Bilgileri yenileyin.')
    fields=data.model_fields_set;changes={};old_store=store_for(db,phone);next_store=data.store_id if 'store_id' in fields else old_store
    if 'store_id' in fields:
        if data.store_id is not None and not db.get(Store,data.store_id):raise HTTPException(422,'Mağaza bulunamadı.')
        if not allowed_store(db,user,data.store_id):raise HTTPException(403,'Bu mağazaya müşteri taşıma yetkiniz yok.')
        changes.update(store_id=data.store_id,store_linked=True)
    next_assignee=data.assignee_id if 'assignee_id' in fields else row.assignee_id
    if 'assignee_id' in fields and user.role!='admin' and row.assignee_id is None and data.assignee_id!=user.id:raise HTTPException(403,'Atanmamış sohbeti yalnızca kendi üzerinize alabilirsiniz.')
    if next_assignee is not None:
        target=db.get(User,next_assignee)
        if not target or not target.active:raise HTTPException(422,'Aktif personel bulunamadı.')
        if not allowed_store(db,target,next_store):raise HTTPException(422,'Seçilen personelin bu mağazaya erişimi yok.')
    if 'assignee_id' in fields:changes['assignee_id']=data.assignee_id
    if 'status' in fields:changes['status']=data.status
    if 'customer_name' in fields:changes['customer_name']=data.customer_name.strip() if data.customer_name is not None else None
    if 'tags' in fields:changes['tags']=json.dumps(data.tags,ensure_ascii=False)
    changes.update(version=row.version+1,updated=now())
    original={'assignee_id':row.assignee_id,'status':row.status}
    result=db.execute(update(ConversationOps).where(ConversationOps.key==key,ConversationOps.version==data.version).values(**changes).execution_options(synchronize_session=False))
    if result.rowcount!=1:raise HTTPException(409,'Sohbet değişmiş. Yenileyip tekrar deneyin.')
    if 'assignee_id' in fields and original['assignee_id']!=data.assignee_id:record(db,user,'assignment',key,next_store,{'assignee_id':original['assignee_id']},{'assignee_id':data.assignee_id})
    if 'status' in fields and original['status']!=data.status:record(db,user,'status',key,next_store,{'status':original['status']},{'status':data.status})
    if 'store_id' in fields and old_store!=next_store:record(db,user,'store_change',key,next_store,{'store_id':old_store},{'store_id':next_store})
    if 'customer_name' in fields or 'tags' in fields:record(db,user,'customer_update',key,next_store,new={'fields':sorted(fields&{'customer_name','tags'})})
    db.commit();db.refresh(row)
    return get_operation(key,user,db)

class NoteInput(BaseModel):body:str=Field(min_length=1,max_length=5000)
@app.post('/api/operations/conversations/{key}/notes',status_code=201)
def add_note(key:str,data:NoteInput,user=Depends(actor),db=Depends(db_session)):
    phone=phone_for_key(db,key);authorize_phone(db,user,phone,True)
    if not data.body.strip():raise HTTPException(422,'Not boş olamaz.')
    case_row(db,key,True);note=InternalNote(conversation_key=key,author_id=user.id,body=data.body.strip());db.add(note);db.flush();record(db,user,'note_add',key,store_for(db,phone),new={'note_id':note.id});db.commit()
    return {'id':note.id}
@app.delete('/api/operations/notes/{id}')
def remove_note(id:int,user=Depends(actor),db=Depends(db_session)):
    note=db.get(InternalNote,id)
    if not note or note.deleted:raise HTTPException(404,'Not bulunamadı.')
    phone=phone_for_key(db,note.conversation_key);authorize_phone(db,user,phone,True)
    if user.role!='admin' and note.author_id!=user.id:raise HTTPException(403,'Yalnızca kendi notunuzu silebilirsiniz.')
    note.deleted=True;record(db,user,'note_delete',note.conversation_key,store_for(db,phone),old={'note_id':id});db.commit();return {'ok':True}

class ScopeEdit(BaseModel):
    unrestricted:bool=False
    include_unassigned:bool=False
    store_ids:list[int]=Field(default_factory=list,max_length=500)
@app.get('/api/operations/access')
def get_scopes(user=Depends(admin),db=Depends(db_session)):
    rows=[]
    for u in db.scalars(select(User).where(User.active==True)):
        s=db.get(OperatorScope,u.id)
        rows.append({'id':u.id,'name':u.display_name or u.username,'role':u.role,'unrestricted':not s or s.unrestricted,'include_unassigned':True if not s else s.include_unassigned,'store_ids':json.loads(s.store_ids) if s else []})
    return rows
@app.put('/api/operations/access/{id}')
def change_scope(id:int,data:ScopeEdit,user=Depends(admin),db=Depends(db_session)):
    target=db.get(User,id)
    if not target or not target.active:raise HTTPException(404,'Personel bulunamadı.')
    if target.role=='admin':raise HTTPException(422,'Yöneticilerin mevcut genel erişimi korunur.')
    ids=sorted(set(data.store_ids))
    if len(db.scalars(select(Store.id).where(Store.id.in_(ids))).all())!=len(ids):raise HTTPException(422,'Mağaza bulunamadı.')
    existing=db.get(OperatorScope,id);old={'unrestricted':True} if not existing else {'store_ids':json.loads(existing.store_ids),'unrestricted':existing.unrestricted,'include_unassigned':existing.include_unassigned}
    db.merge(OperatorScope(user_id=id,store_ids=json.dumps(ids),unrestricted=data.unrestricted,include_unassigned=data.include_unassigned));record(db,user,'permission_change',old=old,new={'user_id':id,**data.model_dump()});db.commit();return {'ok':True}

class ReopenInput(BaseModel):auto_reopen:bool=False
@app.get('/api/operations/config')
def ops_config(user=Depends(admin),db=Depends(db_session)):
    r=db.get(SystemValue,'operations_auto_reopen');return {'auto_reopen':bool(r and r.value=='true')}
@app.put('/api/operations/config')
def update_config(data:ReopenInput,user=Depends(admin),db=Depends(db_session)):
    old=ops_config(user,db);db.merge(SystemValue(key='operations_auto_reopen',value='true' if data.auto_reopen else 'false'));record(db,user,'configuration',old=old,new=data.model_dump());db.commit();return data.model_dump()

@app.get('/api/operations/audit')
def operation_audit(page:int=1,user=Depends(admin),db=Depends(db_session)):
    stmt=select(OperationEvent);total=db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows=db.scalars(stmt.order_by(OperationEvent.id.desc()).offset((max(1,page)-1)*50).limit(50))
    return {'total':total,'items':[{'id':r.id,'actor':user_name(db,r.actor_id) or 'Sistem','action':r.action,'conversation_key':r.conversation_key,'created':r.created.isoformat(),'old':json.loads(r.old_value),'new':json.loads(r.new_value)} for r in rows]}

@event.listens_for(SASession,'before_flush')
def observe_messages(db,context,instances):
    # Independent observer: never changes webhook validation, send payloads or delivery states.
    incoming=[m for m in list(db.new) if isinstance(m,Message) and m.direction=='in']
    pending={}
    for m in incoming:
        key=key_for(m.phone);case=pending.get(key) or db.get(ConversationOps,key)
        if not case:
            legacy=db.scalar(select(Message.id).where(Message.phone==m.phone).limit(1))
            # Use an atomic insert: concurrent webhook requests must not race on this new metadata.
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert
            insert=pg_insert if db.bind.dialect.name=='postgresql' else sqlite_insert
            db.execute(insert(ConversationOps).values(key=key,phone=m.phone,status=None if legacy else 'new',updated=now(),version=0,tags='[]',store_linked=False).on_conflict_do_nothing(index_elements=['key']))
            case=db.get(ConversationOps,key);pending[key]=case
        config=db.get(SystemValue,'operations_auto_reopen')
        if case.status=='resolved' and config and config.value=='true':
            changed=db.execute(update(ConversationOps).where(ConversationOps.key==key,ConversationOps.status=='resolved').values(status='new',version=ConversationOps.version+1,updated=now()).execution_options(synchronize_session=False))
            if changed.rowcount:
                record(db,None,'auto_reopen',key,store_for(db,m.phone),{'status':'resolved'},{'status':'new'})
            db.refresh(case)
    for m in list(db.new):
        if isinstance(m,Message) and m.direction=='out' and m.campaign_id is None and db.info.get('ops_actor_id') and m.sender_user_id is None:
            m.sender_user_id=db.info['ops_actor_id'];m.operation_store_id=db.info.get('ops_store_id')

@app.get('/api/operations/reports')
def reports(period:str='7',start:str='',end:str='',person_id:int|None=None,store_id:int|None=None,user=Depends(admin),db=Depends(db_session)):
    tz=ZoneInfo('Europe/Istanbul');today=datetime.now(tz).date()
    if period not in ('today','7','30','custom'):raise HTTPException(422,'Geçersiz rapor dönemi.')
    if period=='custom' and (not start or not end):raise HTTPException(422,'Özel dönem için başlangıç ve bitiş tarihini seçin.')
    try:
        first=datetime.fromisoformat(start).date() if start else today-timedelta(days={'today':0,'7':6,'30':29}.get(period,6))
        last=datetime.fromisoformat(end).date() if end else today
        begin=datetime.combine(first,datetime.min.time(),tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)
        finish=datetime.combine(last+timedelta(days=1),datetime.min.time(),tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:raise HTTPException(422,'Geçerli tarih aralığı seçin.')
    if first>last or (last-first).days>366:raise HTTPException(422,'Tarih aralığı en fazla 366 gün olabilir.')
    messages=db.scalars(select(Message).where(Message.created<finish).order_by(Message.created,Message.id)).all()
    accepted={'accepted','sent','delivered','read'};pending={};stats={};responded=set()
    def bucket(id):return stats.setdefault(id,{'sent_messages':0,'answered_conversations':set(),'first_response':[],'response':[],'resolved':0,'assignments':0,'open':0})
    unattributed=0
    for m in messages:
        if m.direction=='in':
            p=pending.setdefault(m.phone,[m.created,m.created]);p[1]=m.created
        elif m.direction=='out' and m.status in accepted:
            wait=pending.pop(m.phone,None);first_reply=m.phone not in responded
            if wait:responded.add(m.phone)
            if not begin<=m.created<finish:continue
            if store_id is not None and m.operation_store_id!=store_id:continue
            if m.sender_user_id is None:
                unattributed+=1;continue
            b=bucket(m.sender_user_id);b['sent_messages']+=1
            if wait:
                b['answered_conversations'].add(key_for(m.phone))
                if first_reply:b['first_response'].append(max(0,(m.created-wait[0]).total_seconds()))
                b['response'].append(max(0,(m.created-wait[1]).total_seconds()))
    for e in db.scalars(select(OperationEvent).where(OperationEvent.created>=begin,OperationEvent.created<finish)):
        if store_id is not None and e.store_id!=store_id:continue
        value=json.loads(e.new_value)
        if e.action=='assignment' and value.get('assignee_id'):bucket(value['assignee_id'])['assignments']+=1
        if e.action=='status' and value.get('status')=='resolved' and e.actor_id:bucket(e.actor_id)['resolved']+=1
    for c in db.scalars(select(ConversationOps).where(ConversationOps.assignee_id.is_not(None))):
        if c.status is not None and c.status!='resolved' and (store_id is None or store_for(db,c.phone)==store_id):bucket(c.assignee_id)['open']+=1
    people=db.scalars(select(User).where(User.id==person_id) if person_id else select(User)).all();result=[]
    for p in people:
        b=bucket(p.id);result.append({'id':p.id,'name':p.display_name or p.username,'active':p.active,'sent_messages':b['sent_messages'],'answered_conversations':len(b['answered_conversations']),'first_response_seconds':sum(b['first_response'])/len(b['first_response']) if b['first_response'] else None,'average_response_seconds':sum(b['response'])/len(b['response']) if b['response'] else None,'resolved_conversations':b['resolved'],'assigned_conversations':b['assignments'],'open_conversations':b['open']})
    store_stats=[]
    for s in db.scalars(select(Store)):
        if store_id is not None and s.id!=store_id:continue
        cases=[c for c in db.scalars(select(ConversationOps)) if store_for(db,c.phone)==s.id and (person_id is None or c.assignee_id==person_id)]
        store_stats.append({'id':s.id,'name':s.name,'tracked_conversations':len(cases),'open':sum(c.status in ('new','in_progress','waiting_customer') for c in cases),'resolved':sum(c.status=='resolved' for c in cases)})
    return {'start':first.isoformat(),'end':last.isoformat(),'people':result,'stores':store_stats,'legacy_unattributed_messages':unattributed,'notice':'Yalnızca göndericisi kayıtlı, API kabulü alınmış mesajlar ölçülür. Açık görüşmeler güncel durumdur. Yanıt süreleri müşteri mesajı ile gerçek yanıt arasındadır; atama öncesi bekleme dahildir. Personeli bilinmeyen geçmiş mesajlar tahmin edilmez.'}

def decorate_conversations(db,user,items):
    phones=[r['phone'] for r in items]
    cases={c.phone:c for c in db.scalars(select(ConversationOps).where(ConversationOps.phone.in_(phones)))}
    stores={s.id:s.name for s in db.scalars(select(Store))};by_name={name:id for id,name in stores.items()}
    owners={u.id:u.display_name or u.username for u in db.scalars(select(User))}
    inherited={}
    for c in db.scalars(select(Contact).where(Contact.kind=='customer',Contact.phone.in_(phones)).order_by(Contact.id)):
        if c.store in by_name:inherited.setdefault(c.phone,by_name[c.store])
    for r in items:
        c=cases.get(r['phone']);store=c.store_id if c and c.store_linked else inherited.get(r['phone']);owner=c.assignee_id if c else None
        r['operations']={'assignee_id':owner,'assignee_name':owners.get(owner),'status':c.status if c else None,'store_id':store,'store_name':stores.get(store),'can_manage':user.role=='admin' or owner in (None,user.id),'version':c.version if c else 0}
    return items
