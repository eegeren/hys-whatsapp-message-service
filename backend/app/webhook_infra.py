"""Receive only; never register a number or send a message."""
import hashlib,hmac,json,re,secrets
from datetime import datetime,timezone
from urllib.parse import urlsplit
from fastapi import Depends,HTTPException,Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.core import settings,Event,WebhookItem,Message,TestMessage,Contact,now,phone,audit
from app.main import app,admin,db_session

def scrub(value):
    text=json.dumps(value,ensure_ascii=False)
    for secret in (settings.meta_access_token,settings.meta_app_secret,settings.meta_verify_token):
        if secret:text=text.replace(secret,'[gizli]')
    return json.loads(text)

def accepts(number,waba):
    if number==settings.meta_phone_number_id:
        return not waba or waba==settings.meta_waba_id
    if not settings.webhook_production_enabled:return False
    production=settings.webhook_production_phone_number_id
    account=settings.webhook_production_waba_id
    return bool(re.fullmatch(r'\d+',production) and re.fullmatch(r'\d+',account) and production!=settings.meta_test_phone_number_id and number==production and waba==account)

@app.get('/api/settings/webhook')
def webhook_state(user=Depends(admin),db=Depends(db_session)):
    url=settings.webhook_public_url
    try:parsed=urlsplit(url)
    except ValueError:parsed=urlsplit('')
    valid=parsed.scheme=='https' and bool(parsed.hostname) and parsed.hostname not in ('localhost','127.0.0.1','::1') and parsed.path=='/api/webhook' and not(parsed.username or parsed.password or parsed.query or parsed.fragment)
    latest=db.scalar(select(WebhookItem).order_by(WebhookItem.created.desc()).limit(1))
    return {'callback_url':url if valid else '', 'https_configured':valid,'public_reachability_verified':False,'verify_token_configured':bool(settings.meta_verify_token),'app_secret_configured':bool(settings.meta_app_secret),'production_reception_enabled':settings.webhook_production_enabled,'production_phone_number_id':settings.webhook_production_phone_number_id,'production_waba_id':settings.webhook_production_waba_id,'last_event_at':latest.created.isoformat() if latest else None,'notice':'HTTPS adresi yapılandırılmış olsa bile dış erişim ve Meta aboneliği ayrıca doğrulanmalıdır.' if valid else 'Gerçek HTTPS Callback URL henüz yapılandırılmadı. Alan adı veya HTTPS tüneli gerekiyor.'}

@app.get('/api/webhook')
def verify_webhook(request:Request):
    p=request.query_params
    if settings.meta_verify_token and p.get('hub.mode')=='subscribe' and p.get('hub.challenge') and secrets.compare_digest(p.get('hub.verify_token','').encode(),settings.meta_verify_token.encode()):
        return PlainTextResponse(p['hub.challenge'])
    raise HTTPException(403,'Webhook doğrulaması başarısız')

def record(db,kind,number,item):
    identity=[kind,number,item['id']]
    if kind=='status':identity += [item.get('status'),str(item.get('timestamp',''))]
    key=hashlib.sha256(json.dumps(identity).encode()).hexdigest()
    if db.get(WebhookItem,key):return False
    try:
        with db.begin_nested():
            db.add(WebhookItem(id=key,kind=kind,phone_number_id=number,meta_id=item['id'],payload=json.dumps(scrub(item),ensure_ascii=False)))
            db.flush()
    except IntegrityError:return False
    return True

def incoming(db,item):
    if db.scalar(select(Message.id).where(Message.meta_id==item['id'])):return
    try:n=phone(item['from'])
    except (ValueError,KeyError,TypeError):return
    text=item.get('text',{})
    if not isinstance(text,dict):raise HTTPException(422,'Geçersiz webhook mesaj yapısı')
    body=text.get('body',f'[{item.get("type","unknown")}]')
    if item.get('type')=='button' and isinstance(item.get('button'),dict):
        body=item['button'].get('text',body)
    if not isinstance(body,str):return
    body=scrub(body)
    matches=db.scalars(select(Contact).where(Contact.phone==n)).all()
    normalized=body.casefold().strip().strip('.! ')
    stop=normalized in ('ret','iptal','stop','abonelikten çık','mesaj istemiyorum','ileti istemiyorum')
    review=not stop and any(word in normalized for word in ('istemiyorum','göndermeyin','iptal','rahatsız'))
    for contact in matches:
        if stop or review:
            contact.opted_out=True;contact.consent='revoked' if stop else 'review'
            audit(db,'webhook','opt_out' if stop else 'opt_out_review',str(contact.id))
    if (stop or review) and not matches:
        # Ret/çıkış bildirimini kişi HYS'de henüz kayıtlı olmasa da sakla.
        blocked=Contact(kind='customer',first_name='WhatsApp iletişim reddi',phone=n,
                        active=False,opted_out=True,consent='revoked' if stop else 'review')
        db.add(blocked)
        db.flush()
        audit(db,'webhook','opt_out' if stop else 'opt_out_review',str(blocked.id))
    try:created=datetime.fromtimestamp(int(item.get('timestamp')),timezone.utc).replace(tzinfo=None)
    except (ValueError,TypeError,OverflowError,OSError):created=now()
    db.add(Message(contact_id=matches[0].id if len(matches)==1 else None,phone=n,body=body,direction='in',status='received',meta_id=item['id'],unread=True,review=review,created=created))

def delivery(db,item):
    m=db.scalar(select(Message).where(Message.meta_id==item['id'],Message.direction=='out'))
    test=None if m else db.scalar(select(TestMessage).where(TestMessage.meta_id==item['id']))
    if not m and not test:return # Durable WebhookItem retains unmatched status.
    row=m or test;field='status' if m else 'delivery_status'
    previous=getattr(row,field);new=item.get('status');rank={'unknown':0,'accepted':0,'sent':1,'delivered':2,'read':3}
    if new in rank and rank[new]>rank.get(previous,-1) and (previous!='failed' or new in ('delivered','read')):
        setattr(row,field,new)
        if new in ('delivered','read'):row.error=''
    elif new=='failed' and previous not in ('delivered','read'):
        setattr(row,field,'failed')
        errors=item.get('errors',[]);code=errors[0].get('code') if errors and isinstance(errors[0],dict) else None
        from app.meta import delivery_error_message
        row.error=delivery_error_message(code)+(f' (kod {code})' if isinstance(code,int) else '')
        if test:test.error_code=str(code) if isinstance(code,int) else ''

@app.post('/api/webhook')
async def receive_webhook(request:Request,db=Depends(db_session)):
    raw=bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw)>2*1024*1024:raise HTTPException(413,'Olay çok büyük')
    if not settings.meta_app_secret:raise HTTPException(503,'Webhook imza anahtarı tanımlı değil')
    signature=request.headers.get('X-Hub-Signature-256','')
    expected='sha256='+hmac.new(settings.meta_app_secret.encode(),raw,hashlib.sha256).hexdigest()
    if not re.fullmatch(r'sha256=[0-9a-f]{64}',signature) or not hmac.compare_digest(expected,signature):raise HTTPException(403,'Geçersiz webhook imzası')
    try:payload=json.loads(raw)
    except (ValueError,UnicodeError):raise HTTPException(422,'Geçersiz JSON')
    if not isinstance(payload,dict) or payload.get('object','whatsapp_business_account')!='whatsapp_business_account' or not isinstance(payload.get('entry'),list):raise HTTPException(422,'Geçersiz webhook olay yapısı')
    digest=hashlib.sha256(raw).hexdigest()
    if db.get(Event,digest):return {'ok':True,'duplicate':True}
    try:db.add(Event(id=digest));db.flush()
    except IntegrityError:db.rollback();return {'ok':True,'duplicate':True}
    for entry in payload['entry']:
        if not isinstance(entry,dict) or not isinstance(entry.get('changes'),list):raise HTTPException(422,'Geçersiz webhook olay yapısı')
        for change in entry['changes']:
            if not isinstance(change,dict):raise HTTPException(422,'Geçersiz webhook olay yapısı')
            if change.get('field','messages')!='messages':continue
            value=change.get('value',{})
            if not isinstance(value,dict) or not isinstance(value.get('metadata',{}),dict):raise HTTPException(422,'Geçersiz webhook olay yapısı')
            number=value.get('metadata',{}).get('phone_number_id')
            if not accepts(number,entry.get('id')):continue
            for field,kind in [('messages','message'),('statuses','status')]:
                items=value.get(field,[])
                if not isinstance(items,list):raise HTTPException(422,'Geçersiz webhook olay yapısı')
                for item in items:
                    if not isinstance(item,dict) or not isinstance(item.get('id'),str) or not 0<len(item['id'])<=200:raise HTTPException(422,'Geçersiz webhook olay kimliği')
                    # Persist only operational fields, never arbitrary echoed credentials.
                    safe={k:item[k] for k in ('id','from','type','text','timestamp','status','recipient_id') if k in item}
                    if item.get('type')=='button':
                        button=item.get('button',{})
                        if not isinstance(button,dict):raise HTTPException(422,'Geçersiz webhook buton yanıtı')
                        safe['button']={k:button[k] for k in ('text','payload') if isinstance(button.get(k),str)}
                    if 'errors' in item:safe['errors']=[{'code':e.get('code')} for e in item['errors'] if isinstance(e,dict)] if isinstance(item['errors'],list) else []
                    safe=scrub(safe)
                    if record(db,kind,number,safe):
                        if kind=='message':incoming(db,safe)
                        else:delivery(db,safe)
    db.commit()
    return {'ok':True}
