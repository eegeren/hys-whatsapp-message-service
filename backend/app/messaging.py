import json, hmac, hashlib, io, time
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, Request, File, Form, UploadFile
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field, ValidationError
import hashlib, re
from pydantic import BaseModel, Field
from sqlalchemy import select,func
from sqlalchemy.exc import IntegrityError
from app.core import *
from app.main import app, actor, admin, db_session, serial, require, connection_ok
from app.meta import graph,upload_media
from app.template_components import build_template,definitions,MEDIA_TYPES,MediaUpload,validate_upload
from app.contacts import safe_cell

def conversation_key(value:str):return hashlib.sha256(value.encode()).hexdigest()

@app.get('/api/conversations')
def conversations(user=Depends(actor),db=Depends(db_session)):
    rows=db.scalars(select(Message).order_by(Message.created.desc(),Message.id.desc()).limit(10000)).all()
    grouped={}
    for m in rows:
        item=grouped.get(m.phone)
        if item is None:
            item={'key':conversation_key(m.phone),'phone':m.phone,'last_body':m.body,'last_direction':m.direction,'last_status':m.status,'last_at':m.created.isoformat(),'unread':0}
            grouped[m.phone]=item
        if m.unread:item['unread']+=1
    return sorted(grouped.values(),key=lambda x:x['last_at'],reverse=True)

def verified_whatsapp_consent(contacts):
    return any(c.active and c.preference=='whatsapp' and c.consent=='verified' and
               bool(c.evidence and c.evidence.strip()) and bool(c.source and c.source.strip()) and
               bool(c.consent_date and c.consent_date.strip()) and not c.opted_out for c in contacts)

@app.get('/api/conversations/eligibility')
def conversation_eligibility(phone_number:str,user=Depends(actor),db=Depends(db_session)):
    try: recipient=phone(phone_number)
    except ValueError as e: raise HTTPException(422,str(e))
    contacts=db.scalars(select(Contact).where(Contact.phone==recipient)).all()
    opted_out=any(c.opted_out for c in contacts)
    last_in=db.scalar(select(func.max(Message.created)).where(Message.phone==recipient,Message.direction=='in'))
    age=(now()-last_in) if last_in else None
    service_window=bool(age and timedelta(0)<=age<timedelta(hours=24))
    sender_ready=bool(not settings.dry_run and settings.live_send_enabled and settings.meta_waba_id and connection_ok(db))
    if opted_out: reason='Bu numara iletişim reddi verdi; engelleme listesinde ve gönderim kapalı.'
    elif not sender_ready: reason='Meta canlı gönderimi şu anda kapalı veya bağlantı doğrulanmamış.'
    elif not service_window: reason='İlk mesaj için onaylı Meta şablonu seçin. Serbest metin için son 24 saatte gelen mesaj gerekir.'
    else: reason=''
    audit(db,user.username,'direct_message_eligibility',mask(recipient));db.commit()
    return {'phone':recipient,'contact_found':bool(contacts),
            'opted_out':opted_out,'service_window_open':service_window,
            'template_required':not service_window,'template_allowed':bool(not opted_out and sender_ready),
            'text_allowed':bool(not opted_out and sender_ready and service_window),
            'sender_ready':sender_ready,
            'allowed':bool(not opted_out and sender_ready and service_window),
            'blocked_reason':reason}

@app.get('/api/conversations/{key}')
def conversation_detail(key:str,page:int=1,user=Depends(actor),db=Depends(db_session)):
    if not re.fullmatch(r'[a-f0-9]{64}',key):raise HTTPException(404,'Konuşma bulunamadı')
    rows=db.scalars(select(Message).order_by(Message.created.desc(),Message.id.desc()).limit(10000)).all()
    phone_value=next((m.phone for m in rows if conversation_key(m.phone)==key),None)
    if phone_value is None:raise HTTPException(404,'Konuşma bulunamadı')
    items=db.scalars(select(Message).where(Message.phone==phone_value).order_by(Message.created.desc(),Message.id.desc()).offset((max(1,page)-1)*100).limit(100)).all()
    items=list(reversed(items));audit(db,user.username,'conversation_access',key[:12]);db.commit()
    return {'key':key,'phone':phone_value,'items':[{**serial(m),'phone':phone_value} for m in items]}

class ConversationOpen(BaseModel):phone:str=Field(min_length=8,max_length=20)
@app.post('/api/conversations/open')
def open_conversation(data:ConversationOpen,user=Depends(actor),db=Depends(db_session)):
    try:value=phone(data.phone)
    except ValueError as e:raise HTTPException(422,str(e))
    audit(db,user.username,'conversation_open',mask(value));db.commit()
    return {'key':conversation_key(value),'phone':value,'items':[]}

class HeaderMedia(BaseModel):
    link:str=Field(default='',max_length=2048)
    filename:str=Field(default='',max_length=200)

class CarouselCardInput(BaseModel):
    variables:dict[str,str]=Field(default_factory=dict,max_length=20)
    header_variables:dict[str,str]=Field(default_factory=dict,max_length=20)
    button_variables:dict[str,str]=Field(default_factory=dict,max_length=10)
    header_media:HeaderMedia|None=None

class DirectMessage(BaseModel):
    cards:list[CarouselCardInput]=Field(default_factory=list,max_length=10)
    phone:str|None=Field(default=None,min_length=8,max_length=20)
    conversation_key:str|None=Field(default=None,min_length=64,max_length=64)
    body:str=Field(default='',max_length=4096)
    template_id:int|None=None
    parameters:list[str]=Field(default_factory=list,max_length=20)
    variables:dict[str,str]|None=Field(default=None,max_length=20)
    header_variables:dict[str,str]=Field(default_factory=dict,max_length=20)
    button_variables:dict[str,str]=Field(default_factory=dict,max_length=10)
    header_media:HeaderMedia|None=None

@app.post('/api/conversations/send')
def send_conversation_message(data:DirectMessage,user=Depends(actor),db=Depends(db_session)):
    return send_direct_message(data,user,db)

@app.post('/api/conversations/send-with-media')
def send_conversation_media(data:str=Form(...,max_length=100000),file:UploadFile=File(...),user=Depends(actor),db=Depends(db_session)):
    try:
        if settings.dry_run:raise HTTPException(403,'DRY_RUN açık: gerçek WhatsApp gönderimi şu anda kapalı.')
        if not settings.live_send_enabled or not connection_ok(db):raise HTTPException(403,'Canlı Meta bağlantısı doğrulanmamış veya canlı gönderim kapalı.')
        try:message=DirectMessage.model_validate_json(data)
        except ValidationError:raise HTTPException(422,'Mesaj alanları geçersiz; şablon ve değişkenleri kontrol edin.')
        if message.template_id is None:
            kind='IMAGE' if file.content_type in ('image/jpeg','image/png') else 'VIDEO' if file.content_type=='video/mp4' else ''
        else:
            template=require(db,Template,message.template_id)
            kind=str(definitions(template).get('HEADER',{}).get('format','')).upper()
        if kind not in MEDIA_TYPES:raise HTTPException(422,'Bu şablonda medya başlığı bulunmuyor.')
        limit=MEDIA_TYPES[kind][1]
        content=file.file.read(limit+1)
        asset=MediaUpload(filename=(file.filename or 'dosya').replace('\\','/').rsplit('/',1)[-1],content_type=file.content_type or '',content=content)
        return send_direct_message(message,user,db,asset)
    finally:file.file.close()

def send_direct_message(data,user,db,upload=None):
    # This endpoint never reports a simulated message as a real send.
    if settings.dry_run:raise HTTPException(403,'DRY_RUN açık: gerçek WhatsApp gönderimi şu anda kapalı.')
    if not settings.live_send_enabled or not connection_ok(db):raise HTTPException(403,'Canlı Meta bağlantısı doğrulanmamış veya canlı gönderim kapalı.')
    if data.conversation_key:
        if not re.fullmatch(r'[a-f0-9]{64}',data.conversation_key):raise HTTPException(422,'Konuşma anahtarı geçersiz.')
        existing=db.scalars(select(Message.phone).distinct()).all()
        recipient=next((value for value in existing if conversation_key(value)==data.conversation_key),None)
        if recipient is None and data.phone:
            try:recipient=phone(data.phone)
            except ValueError as e:raise HTTPException(422,str(e))
    else:
        try:recipient=phone(data.phone or '')
        except ValueError as e:raise HTTPException(422,str(e))
    if recipient is None:raise HTTPException(404,'Konuşma bulunamadı.')
    contacts=db.scalars(select(Contact).where(Contact.phone==recipient)).all()
    if any(c.opted_out for c in contacts):raise HTTPException(403,'İletişim reddi bulunan numaraya gönderim engellendi.')
    last_in=db.scalar(select(func.max(Message.created)).where(Message.phone==recipient,Message.direction=='in'))
    service_age=(now()-last_in) if last_in else None
    service_window=bool(service_age and timedelta(0)<=service_age<timedelta(hours=24))
    template=None
    if data.template_id is not None:
        template=require(db,Template,data.template_id)
        if template.status!='APPROVED' or template.category not in ('MARKETING','UTILITY','AUTHENTICATION'):raise HTTPException(403,'Gönderim için Meta tarafından onaylanmış şablon gerekli.')
        if str(definitions(template).get('HEADER',{}).get('format','')).upper() in ('IMAGE','VIDEO') and not service_window and template.category!='MARKETING':raise HTTPException(403,'İlk medya mesajı için onaylı Marketing şablonu gerekli.')
        # Permission records are managed by HYS's external sales system. Keep the
        # local opt-out blocklist, but do not require local consent evidence here.
        template_payload,display,media_kind=build_template(template,data,upload)
        payload={'messaging_product':'whatsapp','recipient_type':'individual','to':recipient.lstrip('+'),'type':'template','template':template_payload}
    else:
        if data.header_media or data.header_variables or data.button_variables:raise HTTPException(422,'Şablon alanları için onaylı şablon seçin.')
        if not service_window:raise HTTPException(403,'24 saatlik müşteri hizmeti penceresi kapalı. Meta onaylı şablon seçin.')
        if upload:
            kind='IMAGE' if upload.content_type in ('image/jpeg','image/png') else 'VIDEO' if upload.content_type=='video/mp4' else ''
            if not kind:raise HTTPException(422,'JPG, PNG veya MP4 dosyası seçin.')
            validate_upload(kind,upload)
            if len(data.body)>1024:raise HTTPException(422,'Medya açıklaması en fazla 1024 karakter olabilir.')
            media_kind=kind.lower();media={'id':'pending-upload'}
            if data.body.strip():media['caption']=data.body.strip()
            payload={'messaging_product':'whatsapp','recipient_type':'individual','to':recipient.lstrip('+'),'type':media_kind,media_kind:media}
            display=('[Görsel]' if kind=='IMAGE' else '[Video]')+(' '+data.body if data.body else '')
        else:
            if not data.body.strip():raise HTTPException(422,'Mesaj metni boş olamaz.')
            payload={'messaging_product':'whatsapp','recipient_type':'individual','to':recipient.lstrip('+'),'type':'text','text':{'body':data.body}}
            display=data.body
    row=Message(contact_id=next((c.id for c in contacts if c.kind=='customer'),None),phone=recipient,body=display,direction='out',status='sending')
    db.add(row);db.commit()
    message_attempted=False
    try:
        if upload:
            media_id=upload_media(upload.filename,upload.content,upload.content_type)
            if template:
                header=next(c for c in payload['template']['components'] if c['type']=='header')
                header['parameters'][0][media_kind]['id']=media_id
            else:payload[media_kind]['id']=media_id
        message_attempted=True
        result=graph('POST',f'{settings.meta_phone_number_id}/messages',payload)
        message_id=result.get('messages',[{}])[0].get('id')
        if not isinstance(message_id,str) or not message_id or any(secret and secret in message_id for secret in (settings.meta_access_token,settings.meta_app_secret,settings.meta_verify_token)):raise ValueError()
        row.meta_id=message_id;row.status='accepted'
    except HTTPException as e:
        detail=e.detail if isinstance(e.detail,dict) else {'message':str(e.detail),'ambiguous':message_attempted}
        code=detail.get('code')
        row.error=(f"Meta hata {code}: " if isinstance(code,int) else '')+str(detail.get('message','Meta gönderimi başarısız.'))
        row.status='uncertain' if message_attempted and detail.get('ambiguous') else 'failed'
    except Exception:row.status='uncertain' if message_attempted else 'failed';row.error='Gönderim sonucu doğrulanamadı; otomatik tekrar yapılmaz.'
    for secret in (settings.meta_access_token,settings.meta_app_secret,settings.meta_verify_token):
        if secret:row.error=row.error.replace(secret,'[gizli]')
    audit(db,user.username,'direct_message',row.status);db.commit();db.refresh(row)
    return {**serial(row),'phone':recipient,'conversation_key':conversation_key(recipient),'delivery_status':'unknown' if row.status=='accepted' else row.status}

@app.get('/api/messages')
def messages(direction:str='',status:str='',unread:bool=False,review:bool=False,unmatched:bool=False,page:int=1,user=Depends(actor),db=Depends(db_session)):
    stmt=select(Message)
    if direction:stmt=stmt.where(Message.direction==direction)
    if status:stmt=stmt.where(Message.status==status)
    if unread:stmt=stmt.where(Message.unread==True)
    if review:stmt=stmt.where(Message.review==True)
    if unmatched:stmt=stmt.where(Message.contact_id==None)
    count=db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows=db.scalars(stmt.order_by(Message.id.desc()).offset((max(1,page)-1)*50).limit(50)).all()
    audit(db,user.username,'message_access',str(page));db.commit()
    return {'total':count,'items':[{**serial(m),'phone':mask(m.phone)} for m in rows]}
@app.post('/api/messages/{id}/read')
def mark_read(id:int,user=Depends(actor),db=Depends(db_session)):
    m=require(db,Message,id);m.unread=False;db.commit();return {'ok':True}
class ReplyInput(BaseModel):body:str=Field(min_length=1,max_length=4096)
@app.post('/api/messages/{id}/reply')
def reply(id:int,data:ReplyInput,user=Depends(actor),db=Depends(db_session)):
    incoming=require(db,Message,id)
    if incoming.direction!='in':raise HTTPException(422,'Gelen mesaj seçin')
    last=db.scalar(select(func.max(Message.created)).where(Message.phone==incoming.phone,Message.direction=='in'))
    if not last or now()-last>=timedelta(hours=24):raise HTTPException(403,'24 saatlik hizmet penceresi kapalı; onaylı şablon kullanın')
    matches=db.scalars(select(Contact).where(Contact.phone==incoming.phone)).all()
    if any(c.opted_out for c in matches):raise HTTPException(403,'Ret veren alıcıya panelden yanıt engellendi')
    if not settings.dry_run and not(settings.live_send_enabled and connection_ok(db)):raise HTTPException(403,'Canlı bağlantı kapalı')
    m=Message(contact_id=incoming.contact_id,phone=incoming.phone,body=data.body,status='dry_run' if settings.dry_run else 'sending');db.add(m);db.commit()
    if not settings.dry_run:
        try:
            result=graph('POST',f'{settings.meta_phone_number_id}/messages',{'messaging_product':'whatsapp','to':m.phone.lstrip('+'),'type':'text','text':{'body':data.body}})
            m.meta_id=result['messages'][0]['id'];m.status='accepted'
        except Exception:m.status='uncertain';m.error='Gönderim sonucu doğrulanamadı; otomatik tekrar yapılmaz'
    incoming.unread=False;audit(db,user.username,'reply',str(m.id));db.commit();return serial(m)
@app.get('/api/settings')
def api_settings(user=Depends(admin),db=Depends(db_session)):
    return {'dry_run':settings.dry_run,'live_enabled':settings.live_send_enabled,'environment':settings.meta_environment,'phone_number_id':settings.meta_phone_number_id,'waba_id':settings.meta_waba_id,'graph_version':settings.meta_graph_api_version,'webhook_url':settings.webhook_public_url,'token_configured':bool(settings.meta_access_token),'app_secret_configured':bool(settings.meta_app_secret),'verified':connection_ok(db),'coexistence':'Bağlantı manuel tamamlanmalı; sistem numara kaydı/taşıma yapmaz','iys':'Entegrasyon yok; yalnızca manuel belge doğrulaması','pricing':'Güncel tarife bağlı değil; maliyet bilinmiyor'}
@app.get('/api/settings/client-status')
def client_status(user=Depends(actor),db=Depends(db_session)):
    return {'dry_run':settings.dry_run,'live_enabled':settings.live_send_enabled,'verified':connection_ok(db),'environment':settings.meta_environment,'phone_number_id':settings.meta_phone_number_id if user.role=='admin' else mask(settings.meta_phone_number_id) if settings.meta_phone_number_id else ''}
@app.post('/api/settings/test')
def connection_test(user=Depends(actor),db=Depends(db_session)):
    previous=db.get(SystemValue,'meta_verified')
    if previous:db.delete(previous);db.commit()
    result=graph('GET',settings.meta_phone_number_id,params={'fields':'id,display_phone_number,verified_name'})
    numbers=graph('GET',f'{settings.meta_waba_id}/phone_numbers',params={'fields':'id','limit':100})
    matched=any(n.get('id')==settings.meta_phone_number_id for n in numbers.get('data',[]))
    seen=set()
    while not matched and numbers.get('paging',{}).get('next'):
        cursor=numbers.get('paging',{}).get('cursors',{}).get('after')
        if not cursor or cursor in seen:break
        seen.add(cursor)
        if len(seen)>100:raise HTTPException(422,'WABA numara kontrolü tamamlanamadı; hesap numaralarını Meta panelinde kontrol edin.')
        numbers=graph('GET',f'{settings.meta_waba_id}/phone_numbers',params={'fields':'id','limit':100,'after':cursor})
        matched=any(n.get('id')==settings.meta_phone_number_id for n in numbers.get('data',[]))
    if result.get('id')!=settings.meta_phone_number_id or not matched:raise HTTPException(422,'Test numarası ID değeri bu WABA hesabıyla eşleşmiyor. META_PHONE_NUMBER_ID ve META_WABA_ID değerlerini kontrol edin.')
    fingerprint=hashlib.sha256((settings.meta_access_token+settings.meta_phone_number_id+settings.meta_waba_id+settings.meta_environment).encode()).hexdigest()
    db.merge(SystemValue(key='meta_verified',value=json.dumps({'fingerprint':fingerprint,'checked_at':now().isoformat()})));audit(db,user.username,'meta_connection_test','Numara ve WABA erişimi doğrulandı');db.commit()
    return {'ok':True,'name':result.get('verified_name'),'notice':'Meta API erişimi ve numaranın WABA ilişkisi salt okunur isteklerle doğrulandı. Mesaj gönderilmedi; bu sonuç teslimat veya Coexistence doğrulaması değildir.'}
@app.get('/api/audit')
def audit_list(user=Depends(admin),db=Depends(db_session)):return [serial(a) for a in db.scalars(select(Audit).order_by(Audit.id.desc()).limit(200))]
@app.get('/api/reports')
def reports(user=Depends(actor),db=Depends(db_session)):
    rows=[]
    for c in db.scalars(select(Campaign).order_by(Campaign.id.desc())):
        msgs=db.scalars(select(Message).where(Message.campaign_id==c.id)).all()
        rows.append({'id':c.id,'name':c.name,'kind':c.kind,'targeted':len(msgs),'queued':sum(m.status in ('queued','retry') for m in msgs),'accepted':sum(m.meta_id is not None for m in msgs),'delivered':sum(m.status in ('delivered','read') for m in msgs),'read':sum(m.status=='read' for m in msgs),'failed':sum(m.status in ('failed','blocked','uncertain') for m in msgs),'dry_run':sum(m.status=='dry_run' for m in msgs),'responded':sum(bool(db.scalar(select(Message.id).where(Message.direction=='in',Message.phone==m.phone,Message.created>=m.created).limit(1))) for m in msgs),'opted_out':sum(bool(db.get(Contact,m.contact_id) and db.get(Contact,m.contact_id).opted_out) for m in msgs),'estimated_cost':None})
    return rows
@app.get('/api/reports/export')
def report_export(user=Depends(admin),db=Depends(db_session)):
    from openpyxl import Workbook
    data=reports(user,db);wb=Workbook();ws=wb.active
    if data:
        ws.append(list(data[0]))
        for row in data:ws.append([safe_cell(v) for v in row.values()])
    else:ws.append(['Henüz rapor yok'])
    buf=io.BytesIO();wb.save(buf);buf.seek(0);audit(db,user.username,'report_export','Excel');db.commit()
    return StreamingResponse(buf,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':'attachment; filename="rapor.xlsx"'})
from app import webhook_infra
