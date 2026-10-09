import json, re
from datetime import datetime, timezone
from pydantic import BaseModel, Field
from fastapi import Depends, HTTPException
from sqlalchemy import select
from app.core import *
from app.main import app, actor, admin, db_session, serial, require, connection_ok
from app.meta import graph

class TemplateInput(BaseModel):
    name:str=Field(pattern=r'^[a-z0-9_]{1,150}$')
    body:str=Field(min_length=1,max_length=1024)
    category:str='MARKETING'
    language:str='tr'
    components:list[dict]=Field(default_factory=list)
@app.get('/api/templates')
def templates(user=Depends(actor),db=Depends(db_session)):return [serial(t) for t in db.scalars(select(Template))]
@app.post('/api/templates')
def template_add(data:TemplateInput,user=Depends(admin),db=Depends(db_session)):
    if data.category not in ('MARKETING','UTILITY','AUTHENTICATION'):raise HTTPException(422,'Geçersiz kategori')
    if db.scalar(select(Template.id).where(Template.name==data.name)):raise HTTPException(409,'Şablon mevcut')
    t=Template(**{**data.model_dump(exclude={'components'}),'components':json.dumps(data.components)});db.add(t);db.commit();return serial(t)
@app.post('/api/templates/sync')
def template_sync(user=Depends(actor),db=Depends(db_session)):
    result=graph('GET',f'{settings.meta_waba_id}/message_templates',params={'limit':100});items=list(result.get('data',[]))
    while result.get('paging',{}).get('cursors',{}).get('after') and result.get('paging',{}).get('next'):
        result=graph('GET',f'{settings.meta_waba_id}/message_templates',params={'limit':100,'after':result['paging']['cursors']['after']});items+=result.get('data',[])
    # Removed remote templates cannot retain an old APPROVED status.
    for t in db.scalars(select(Template).where(Template.meta_id!='')):t.status='NOT_FOUND'
    for item in items:
        t=db.scalar(select(Template).where(Template.name==item['name']))
        if not t:t=Template(name=item['name'],body='');db.add(t)
        t.meta_id=item['id'];t.language=item['language'];t.category=item['category'];t.status=item['status'];t.components=json.dumps(item.get('components',[]))
        t.body=next((c.get('text','') for c in item.get('components',[]) if c['type']=='BODY'),'')
    audit(db,user.username,'template_sync',str(len(items)));db.commit();return {'synced':len(items)}
@app.post('/api/templates/{id}/submit')
def template_submit(id:int,user=Depends(admin),db=Depends(db_session)):
    t=require(db,Template,id)
    result=graph('POST',f'{settings.meta_waba_id}/message_templates',{'name':t.name,'language':t.language,'category':t.category,'components':json.loads(t.components) or [{'type':'BODY','text':t.body}]})
    t.meta_id=result['id'];t.status=result.get('status','PENDING');audit(db,user.username,'template_submit',t.name);db.commit();return serial(t)
class CampaignInput(BaseModel):
    kind:str
    name:str=Field(min_length=1,max_length=200)
    description:str=''
    template_id:int
    filters:dict=Field(default_factory=dict)
    variables:dict=Field(default_factory=dict)
    scheduled:datetime|None=None
    max_count:int=Field(default=1000,ge=1,le=10000)
    budget:str=''
@app.get('/api/campaigns')
def campaigns(user=Depends(actor),db=Depends(db_session)):return [serial(c) for c in db.scalars(select(Campaign).order_by(Campaign.id.desc()))]
@app.post('/api/campaigns')
def campaign_add(data:CampaignInput,user=Depends(actor),db=Depends(db_session)):
    if data.kind not in ('customer','staff'):raise HTTPException(422,'Geçersiz tür')
    require(db,Template,data.template_id)
    values=data.model_dump();values['filters']=json.dumps(data.filters);values['variables']=json.dumps(data.variables)
    if data.scheduled:values['scheduled']=data.scheduled.astimezone(timezone.utc).replace(tzinfo=None) if data.scheduled.tzinfo else data.scheduled
    c=Campaign(**values);db.add(c);audit(db,user.username,'campaign_create',data.name);db.commit();return serial(c)
def audience(db,c):
    filters=json.loads(c.filters);stmt=select(Contact).where(Contact.kind==c.kind)
    for k in ('store','city','group'):
        if filters.get(k):stmt=stmt.where(getattr(Contact,k)==filters[k])
    if filters.get('ids'):stmt=stmt.where(Contact.id.in_(filters['ids']))
    all_rows=db.scalars(stmt.order_by(Contact.id)).all();rows=[r for r in all_rows if eligible(r)][:c.max_count]
    return rows,len(all_rows)-len(rows)
def render_message(t,c,variables):
    values={'personel_adi':c.first_name,'musteri_adi':c.first_name,'magaza_adi':c.store,**variables};body=t.body
    for k,v in values.items():body=re.sub(r'{{\s*'+re.escape(str(k))+r'\s*}}',lambda _:str(v),body)
    return body
@app.get('/api/campaigns/{id}/preview')
def campaign_preview(id:int,user=Depends(actor),db=Depends(db_session)):
    c=require(db,Campaign,id);t=require(db,Template,c.template_id);rows,excluded=audience(db,c)
    return {'count':len(rows),'excluded':excluded,'cost':None,'cost_notice':'Güncel tarife bağlı değil; maliyet bilinmiyor. Bütçeli canlı gönderim kapalı.','template_status':t.status,'category':t.category,'sample':render_message(t,rows[0],json.loads(c.variables)) if rows else t.body,'dry_run':settings.dry_run}
@app.post('/api/campaigns/{id}/{action}')
def campaign_action(id:int,action:str,user=Depends(admin),db=Depends(db_session)):
    c=db.scalar(select(Campaign).where(Campaign.id==id).with_for_update())
    if not c:raise HTTPException(404,'Kampanya bulunamadı')
    if action=='approve':
        if c.status!='draft':raise HTTPException(409,'Yalnızca taslak onaylanır')
        c.first_approval=user.id;c.second_approval=None
    elif action=='confirm':
        if c.status!='draft' or not c.first_approval:raise HTTPException(409,'Önce ilk yönetici onayı gerekir')
        if c.first_approval==user.id:raise HTTPException(403,'İkinci onay farklı yönetici tarafından verilmeli')
        c.second_approval=user.id
    elif action=='start':
        if c.status!='draft':raise HTTPException(409,'Kampanya zaten başlatılmış')
        t=require(db,Template,c.template_id)
        if not settings.dry_run:
            if not(settings.live_send_enabled and connection_ok(db) and c.first_approval and c.second_approval):raise HTTPException(403,'Canlı bağlantı ve iki farklı yönetici onayı zorunlu')
            if c.budget:raise HTTPException(403,'Doğrulanmış fiyat kaynağı olmadan bütçeli canlı gönderim yapılamaz')
            if t.status!='APPROVED' or (c.kind=='customer' and t.category!='MARKETING'):raise HTTPException(403,'Uygun onaylı Meta şablonu gerekli')
        rows,_=audience(db,c)
        if not rows:raise HTTPException(422,'Gönderime uygun alıcı yok')
        for contact in rows:db.add(Message(campaign_id=c.id,contact_id=contact.id,phone=contact.phone,body=render_message(t,contact,json.loads(c.variables))))
        c.status='scheduled' if c.scheduled and c.scheduled>now() else 'running'
    elif action=='pause':
        if c.status not in ('running','scheduled'):raise HTTPException(409,'Aktif kampanya duraklatılabilir')
        c.status='paused'
    elif action=='resume':
        if c.status!='paused':raise HTTPException(409,'Kampanya duraklatılmış değil')
        c.status='scheduled' if c.scheduled and c.scheduled>now() else 'running'
    elif action=='cancel':
        c.status='cancelled'
        for m in db.scalars(select(Message).where(Message.campaign_id==id,Message.status.in_(['queued','retry']))):m.status='cancelled'
    else:raise HTTPException(404,'İşlem bulunamadı')
    audit(db,user.username,'campaign_'+action,str(id));db.commit();return serial(c)
