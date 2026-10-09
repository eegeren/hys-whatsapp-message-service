import hashlib,json,re,secrets,uuid,threading
from pathlib import Path
from dotenv import set_key
from datetime import datetime,timedelta
from fastapi import Depends,HTTPException
from pydantic import BaseModel,Field,field_validator
from sqlalchemy import select,update,func
from sqlalchemy.exc import IntegrityError
from app.core import settings,TestMessage,SystemValue,Session,now,audit,mask
from app.main import app,admin,db_session,require
from app.meta import graph

TEMPLATE='hello_world'
LANGUAGE='en_US'
LOCAL_ENV_PATH=Path(__file__).resolve().parents[2]/'.env'
RECIPIENT_CONFIG_LOCK=threading.Lock()
def recipients():
    values=set(x.strip() for x in settings.meta_test_recipients.split(',') if x.strip())
    if any(not re.fullmatch(r'\+[1-9]\d{7,14}',x) for x in values):raise HTTPException(422,'Sunucu test alıcı listesinde geçersiz E.164 numarası var. .env ayarlarını kontrol edin.')
    return values
def config_hash():return hashlib.sha256(json.dumps([settings.meta_access_token,settings.meta_phone_number_id,settings.meta_waba_id,settings.meta_graph_api_version,settings.meta_test_phone_number_id,sorted(recipients())]).encode()).hexdigest()
def gates(recipient=None):
    if not(settings.dry_run and not settings.live_send_enabled):raise HTTPException(403,'Test gönderimi yalnızca DRY_RUN açık ve canlı toplu gönderim kapalıyken kullanılabilir.')
    if settings.meta_environment!='test' or not settings.meta_test_message_enabled:raise HTTPException(403,'Test mesajı sunucuda etkin değil. META_TEST_MESSAGE_ENABLED ve test ortamı ayarlarını kontrol edin.')
    pinned=settings.meta_test_phone_number_id
    if not re.fullmatch(r'\d+',pinned) or pinned!=settings.meta_phone_number_id:raise HTTPException(403,'Bağımsız test Phone Number ID tanımlı değil veya bağlantıdaki ID ile eşleşmiyor.')
    if not recipients():raise HTTPException(403,'Meta panelinde doğrulanmış test alıcıları sunucu izin listesine eklenmemiş.')
    if recipient is not None and recipient not in recipients():raise HTTPException(403,'Bu alıcı sunucunun test izin listesinde yok. Yalnızca Meta panelinde doğrulanmış test alıcılarını kullanın.')
def sender_hash():return hashlib.sha256(json.dumps([settings.meta_access_token,settings.meta_phone_number_id,settings.meta_waba_id,settings.meta_graph_api_version]).encode()).hexdigest()
def identity_policy():
    if settings.meta_phone_number_id in {x.strip() for x in settings.meta_production_phone_number_ids.split(',') if x.strip()}:
        raise HTTPException(403,'Bu kimlik üretim numarası olarak tanımlı; test uç noktasını kullanamaz.')
def require_attestation(db):
    identity_policy()
    row=db.get(SystemValue,'test_sender_attestation')
    saved=json.loads(row.value) if row else {}
    if saved.get('fingerprint')!=sender_hash() or saved.get('phone_number_id')!=settings.meta_test_phone_number_id or saved.get('waba_id')!=settings.meta_test_waba_id:
        raise HTTPException(403,'Meta Test Numarasını Doğrula adımında bu Phone Number ID ve WABA ID için açık yönetici onayı gerekiyor.')
def verify_remote(sender_id=None):
    sender_id=sender_id or settings.meta_test_phone_number_id
    number=graph('GET',sender_id,params={'fields':'id,account_mode'})
    identity_policy()
    if number.get('id')!=sender_id:raise HTTPException(403,'Meta numara kimliği bağlantıdaki kimlikle eşleşmiyor.')
    waba=graph('GET',settings.meta_waba_id,params={'fields':'id'})
    if waba.get('id')!=settings.meta_waba_id:raise HTTPException(403,'Meta WABA kimliği eşleşmiyor.')
    data=graph('GET',settings.meta_waba_id+'/phone_numbers',params={'fields':'id,account_mode','limit':100})
    seen=set();matched=False
    while True:
        matched=any(x.get('id')==sender_id for x in data.get('data',[]))
        if matched:break
        cursor=data.get('paging',{}).get('cursors',{}).get('after')
        if not data.get('paging',{}).get('next') or not cursor or cursor in seen or len(seen)>=100:break
        seen.add(cursor);data=graph('GET',settings.meta_waba_id+'/phone_numbers',params={'fields':'id,account_mode','limit':100,'after':cursor})
    if not matched:raise HTTPException(403,'Numara bu WABA hesabının numaralarıyla eşleşmiyor.')
    templates=graph('GET',settings.meta_waba_id+'/message_templates',params={'name':TEMPLATE,'fields':'name,status,language','limit':100})
    if not any(x.get('name')==TEMPLATE and x.get('language')==LANGUAGE and x.get('status')=='APPROVED' for x in templates.get('data',[])):
        raise HTTPException(403,'hello_world / en_US şablonu Meta tarafından APPROVED olarak doğrulanmadı.')
    return number.get('account_mode') if number.get('account_mode') in ('LIVE','SANDBOX') else 'unknown'

def result(row):
    return {'id':row.id,'recipient':mask(row.recipient),'template':TEMPLATE,'language':LANGUAGE,'status':row.status,'delivery_status':row.delivery_status,'message_id':row.meta_id,'error_code':row.error_code,'error':row.error,'api_response':json.loads(row.api_response),'created':row.created.isoformat(),'notice':'API kabulü teslimat değildir. İmzalı webhook gelene kadar teslimat durumu bilinmiyor.'}
def sanitize(value):
    text=json.dumps(value,ensure_ascii=False)
    for secret in (settings.meta_access_token,settings.meta_app_secret,settings.meta_verify_token):
        if secret:text=text.replace(secret,'[gizli]')
    return json.loads(text)
def safe_response(data):
    # Persist only documented operational fields; do not persist echoed credentials.
    return sanitize({'messaging_product':data.get('messaging_product','whatsapp'),'messages':[{'id':x.get('id'),'message_status':x.get('message_status')} for x in data.get('messages',[]) if isinstance(x,dict)]})
@app.get('/api/settings/test-message')
def test_state(user=Depends(admin),db=Depends(db_session)):
    reason='';count=0
    try:gates();require_attestation(db)
    except HTTPException as e:reason=str(e.detail)
    try:count=len(recipients())
    except HTTPException as e:reason=str(e.detail)
    for row in db.scalars(select(TestMessage).where(TestMessage.status=='sending',TestMessage.attempted<now()-timedelta(minutes=5))):
        row.status='uncertain';row.error='İşleyici kesintisi veya yanıt zaman aşımı; tekrar gönderilmez.'
    db.commit()
    rows=db.scalars(select(TestMessage).order_by(TestMessage.created.desc()).limit(20)).all()
    check=db.get(SystemValue,'test_number_check');cached=json.loads(check.value) if check else {}
    sender_mode=cached.get('mode','unknown') if cached.get('fingerprint')==sender_hash() else 'unknown'
    return {'enabled':not reason,'blocked_reason':reason,'sender_mode':sender_mode,'sender_verified':attested(db),'phone_number_id':settings.meta_test_phone_number_id,'waba_id':settings.meta_test_waba_id,'feature_enabled':settings.meta_test_message_enabled,'recipient_count':count,'template':TEMPLATE,'language':LANGUAGE,'records':[result(r) for r in rows],'rate_limit':'En fazla dakikada 1, günde 10 gerçek test denemesi. Hazırlık dakikada 5.'}
def attested(db):
    try:require_attestation(db);return True
    except HTTPException:return False

def reserve_request(db,user_id,action):
    key=f'test_request_rate:{user_id}:{action}'
    row=db.get(SystemValue,key)
    if not row:
        try:
            with db.begin_nested():db.add(SystemValue(key=key,value='{}'));db.flush()
        except IntegrityError:pass
        row=db.get(SystemValue,key)
    old=row.value;saved=json.loads(old)
    stamp=datetime.fromisoformat(saved['start']) if saved.get('start') else now()
    count=saved.get('count',0) if now()-stamp<timedelta(minutes=1) else 0
    if count>=5:raise HTTPException(429,'Test işlemi için dakikalık 5 istek sınırına ulaşıldı. Bir dakika bekleyin.')
    if count==0:stamp=now()
    value=json.dumps({'start':stamp.isoformat(),'count':count+1})
    changed=db.execute(update(SystemValue).where(SystemValue.key==key,SystemValue.value==old).values(value=value))
    if changed.rowcount!=1:db.rollback();raise HTTPException(429,'Eşzamanlı test isteği engellendi. Yeniden deneyin.')
    db.commit()
@app.post('/api/settings/test-message/check')
def readiness(user=Depends(admin),db=Depends(db_session)):
    if not(settings.dry_run and not settings.live_send_enabled and settings.meta_environment=='test'):raise HTTPException(403,'Test numarası kontrolü için DRY_RUN açık, canlı gönderim kapalı ve ortam test olmalıdır.')
    reserve_request(db,user.id,'check')
    mode='unknown';error='';code=None
    try:mode=verify_remote(settings.meta_phone_number_id)
    except HTTPException as e:
        detail=e.detail
        error=sanitize(detail.get('message','Kontrol tamamlanamadı.') if isinstance(detail,dict) else str(detail))
        if isinstance(detail,dict):code=detail.get('code') if isinstance(detail.get('code'),int) else None
    db.merge(SystemValue(key='test_number_check',value=json.dumps({'fingerprint':sender_hash(),'mode':mode,'checked':now().isoformat()})))
    audit(db,user.username,'test_sender_readonly_check',mode);db.commit()
    return {'ready':not error,'mode':mode,'error':error,'code':code,'notice':'Yalnızca salt okunur test numarası ve şablon kontrolü yapıldı. Mesaj gönderilmedi.'}
class SenderConfirmation(BaseModel):
    phone_number_id:str=Field(pattern=r'^\d+$',max_length=40)
    waba_id:str=Field(pattern=r'^\d+$',max_length=40)
    compared_in_meta:bool=False
    meta_development_number:bool=False

@app.post('/api/settings/test-message/verify-sender')
def confirm_sender(data:SenderConfirmation,user=Depends(admin),db=Depends(db_session)):
    if not(settings.dry_run and not settings.live_send_enabled and settings.meta_environment=='test'):raise HTTPException(403,'DRY_RUN açık ve canlı gönderim kapalı olmalıdır.')
    identity_policy()
    if not data.compared_in_meta or not data.meta_development_number:raise HTTPException(403,'Meta test ekranında elle karşılaştırma ve geliştirme test numarası için açık yönetici onayı gerekir.')
    if data.phone_number_id!=settings.meta_phone_number_id or data.phone_number_id!=settings.meta_test_phone_number_id or data.waba_id!=settings.meta_waba_id or data.waba_id!=settings.meta_test_waba_id:
        raise HTTPException(403,'Girilen test ekranı kimlikleri sunucunun bağlantı ve sabit test kimlikleriyle eşleşmiyor.')
    reserve_request(db,user.id,'verify-sender')
    mode=verify_remote(data.phone_number_id)
    saved={'fingerprint':sender_hash(),'phone_number_id':data.phone_number_id,'waba_id':data.waba_id,'actor':user.username,'confirmed_at':now().isoformat(),'basis':'Meta Developers test ekranında manuel yönetici karşılaştırması; API test niteliğini kesin kanıtlamaz','account_mode':mode}
    db.merge(SystemValue(key='test_sender_attestation',value=json.dumps(saved)))
    db.merge(SystemValue(key='test_number_check',value=json.dumps({'fingerprint':sender_hash(),'mode':mode,'checked':now().isoformat()})))
    audit(db,user.username,'test_sender_manual_confirmation',json.dumps({k:v for k,v in saved.items() if k!='fingerprint'},ensure_ascii=False));db.commit()
    return {'verified':True,'mode':mode,'notice':'Kimlik ilişkisi ve şablon API ile kontrol edildi; test numarası niteliği yönetici beyanına dayanır. Mesaj gönderilmedi.'}

class Prepare(BaseModel):
    recipient:str=Field(max_length=20)
    @field_validator('recipient')
    @classmethod
    def e164(cls,value):
        if not re.fullmatch(r'\+[1-9]\d{7,14}',value):raise ValueError('Alıcı E.164 biçiminde olmalı: +905321234567. Boşluk veya yerel numara kabul edilmez.')
        return value
class RecipientSetup(Prepare):
    recipient_verified_in_meta:bool=False

@app.post('/api/settings/test-message/recipient')
def save_recipient(data:RecipientSetup,user=Depends(admin),db=Depends(db_session)):
    if not(settings.dry_run and not settings.live_send_enabled and settings.meta_environment=='test' and settings.meta_test_message_enabled):raise HTTPException(403,'Güvenli test gönderimi sunucuda etkin olmalıdır.')
    require_attestation(db)
    if not data.recipient_verified_in_meta:raise HTTPException(403,'Kendi alıcı numaranızı Meta test ekranında ekleyip doğruladığınızı açıkça onaylayın.')
    reserve_request(db,user.id,'recipient')
    # Only this server's fixed local file and this one non-secret key may be changed.
    with RECIPIENT_CONFIG_LOCK:
        if not LOCAL_ENV_PATH.is_file():raise HTTPException(409,'Yerel .env dosyası bulunamadı; test alıcısı kaydedilemedi.')
        try:
            written,_,_=set_key(str(LOCAL_ENV_PATH),'META_TEST_RECIPIENTS',data.recipient,quote_mode='never',encoding='utf-8')
            if not written:raise OSError()
        except Exception:raise HTTPException(500,'Yerel test alıcısı ayarı kaydedilemedi. Dosya yazma izinlerini kontrol edin.') from None
        settings.meta_test_recipients=data.recipient
    audit(db,user.username,'test_recipient_local_configuration',json.dumps({'recipient':mask(data.recipient),'basis':'Meta alıcı doğrulaması yönetici beyanıdır; API doğrulaması yapılmadı','phone_number_id':settings.meta_test_phone_number_id,'waba_id':settings.meta_test_waba_id},ensure_ascii=False));db.commit()
    return {'saved':True,'recipient_count':1,'notice':'Kendi test numaranız yerel META_TEST_RECIPIENTS izin listesine kaydedildi. Mesaj gönderilmedi; yeniden başlatma gerekmez.'}

@app.post('/api/settings/test-message/prepare')
def prepare(data:Prepare,user=Depends(admin),db=Depends(db_session)):
    gates(data.recipient);require_attestation(db)
    reserve_request(db,user.id,'prepare')
    count=db.scalar(select(func.count(TestMessage.id)).where(TestMessage.user_id==user.id,TestMessage.created>now()-timedelta(minutes=1)))
    if count>=5:raise HTTPException(429,'Çok fazla test hazırlığı. Bir dakika bekleyin.')
    verify_remote()
    token=secrets.token_urlsafe(32)
    row=TestMessage(id=str(uuid.uuid4()),user_id=user.id,recipient=data.recipient,phone_number_id=settings.meta_test_phone_number_id,confirmation_hash=hashlib.sha256(token.encode()).hexdigest(),config_hash=config_hash(),expires=now()+timedelta(minutes=5))
    db.add(row);audit(db,user.username,'test_message_prepare',row.id);db.commit()
    return {**result(row),'confirmation_token':token,'recipient':data.recipient,'expires':row.expires.isoformat(),'warning':'Bu işlem seçili test alıcısına GERÇEK bir hello_world mesajı gönderir. Kampanya ve personel gönderimleri DRY_RUN olarak kalır.'}
class Confirm(BaseModel):
    id:str=Field(min_length=36,max_length=36)
    confirmation_token:str=Field(min_length=20,max_length=100)
    confirmed:bool=False
    recipient_verified:bool=False
def reserve_rate(db):
    row=db.get(SystemValue,'test_message_rate')
    if not row:
        try:
            with db.begin_nested():db.add(SystemValue(key='test_message_rate',value='{}'));db.flush()
        except IntegrityError:pass
        row=db.get(SystemValue,'test_message_rate')
    old=row.value;saved=json.loads(old);day=now().date().isoformat()
    if saved.get('last') and now()-datetime.fromisoformat(saved['last'])<timedelta(minutes=1):raise HTTPException(429,'Test gönderim sınırı: bir dakika bekleyin.')
    count=saved.get('count',0) if saved.get('day')==day else 0
    if count>=10:raise HTTPException(429,'Günlük 10 test gönderimi denemesi sınırına ulaşıldı.')
    value=json.dumps({'day':day,'count':count+1,'last':now().isoformat()})
    updated=db.execute(update(SystemValue).where(SystemValue.key=='test_message_rate',SystemValue.value==old).values(value=value))
    if updated.rowcount!=1:raise HTTPException(429,'Başka bir test gönderimi işleniyor. Bir dakika bekleyin.')
@app.post('/api/settings/test-message/send')
def send(data:Confirm,user=Depends(admin),db=Depends(db_session)):
    row=require(db,TestMessage,data.id)
    if row.user_id!=user.id or not secrets.compare_digest(row.confirmation_hash,hashlib.sha256(data.confirmation_token.encode()).hexdigest()):raise HTTPException(403,'Test onayı bu kullanıcıya veya hazırlığa ait değil.')
    if not data.confirmed or not data.recipient_verified:raise HTTPException(403,'Gerçek test mesajı ve Meta panelindeki alıcı doğrulaması için açık onay gerekir.')
    if row.status!='prepared':return result(row)
    gates(row.recipient);require_attestation(db)
    if row.expires<now() or row.config_hash!=config_hash():raise HTTPException(409,'Test hazırlığının süresi dolmuş veya ayarlar değişmiş. Yeniden hazırlayın.')
    reserve_request(db,user.id,'send')
    db.refresh(row)
    if row.status!='prepared':return result(row)
    verify_remote()
    changed=db.execute(update(TestMessage).where(TestMessage.id==row.id,TestMessage.status=='prepared').values(status='sending',attempted=now()))
    if changed.rowcount!=1:db.rollback();raise HTTPException(409,'Bu test zaten işlenmiş; tekrar gönderilmedi.')
    reserve_rate(db);audit(db,user.username,'test_message_send',row.id);db.commit();db.refresh(row)
    payload={'messaging_product':'whatsapp','recipient_type':'individual','to':row.recipient.lstrip('+'),'type':'template','template':{'name':TEMPLATE,'language':{'code':LANGUAGE}}}
    try:
        response=graph('POST',row.phone_number_id+'/messages',payload)
        message_id=response.get('messages',[{}])[0].get('id')
        if not isinstance(message_id,str) or not message_id:raise ValueError()
        if any(secret and secret in message_id for secret in (settings.meta_access_token,settings.meta_app_secret,settings.meta_verify_token)):raise ValueError()
        row.meta_id=message_id;row.status='accepted';row.api_response=json.dumps(safe_response(response),ensure_ascii=False)
    except HTTPException as e:
        detail=e.detail if isinstance(e.detail,dict) else {'message':str(e.detail)}
        code=detail.get('code');row.error_code=str(code) if isinstance(code,int) else ''
        row.error=sanitize(detail.get('message','Meta test isteği tamamlanamadı.'))
        row.status='uncertain' if detail.get('ambiguous') or not isinstance(e.detail,dict) else 'failed'
        row.api_response=json.dumps(sanitize({'error':{'code':row.error_code,'message':row.error}}),ensure_ascii=False)
    except Exception:row.status='uncertain';row.error='API sonucu doğrulanamadı. Otomatik tekrar gönderim yapılmaz.'
    db.commit()
    if row.status!='accepted':raise HTTPException(502,{'message':row.error,'code':int(row.error_code) if row.error_code else None,'test_message_id':row.id})
    return result(row)
