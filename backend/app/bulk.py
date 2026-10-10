"""Permission-matched bulk campaigns. No automatic real sends."""
import hashlib,io,json,secrets,re
from datetime import datetime,timedelta
from pathlib import Path
from fastapi import Depends,File,Form,HTTPException,UploadFile,Request,Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel,Field
from sqlalchemy import select,update
from app.core import settings,Contact,Template,Campaign,Message,SystemValue,now,audit,eligible,mask
from app.main import app,actor,admin,db_session,require,connection_ok
from app.meta import graph,upload_media
from app.recipient_files import read_rows,parse_recipients,cell_phone
from app.contacts import safe_cell
from app.messaging import DirectMessage,HeaderMedia,CarouselCardInput
from app.template_components import build_template,definitions,MediaUpload,validate_upload
from app.queue_health import worker_health

MEDIA_DIR=Path(settings.bulk_media_dir) if settings.bulk_media_dir else Path(__file__).resolve().parents[2]/'.bulk-media'

def bulk_eligible(db,c):
    return eligible(c) and not any(r.opted_out or r.consent=='revoked' for r in db.scalars(select(Contact).where(Contact.phone==c.phone)))

@app.post('/api/bulk/preview')
async def bulk_preview(file:UploadFile=File(...),phone_column:int|None=Form(None),recipient_kind:str=Form("customer"),user=Depends(actor),db=Depends(db_session)):
    if recipient_kind not in ('customer','staff'):raise HTTPException(422,'Alıcı türü geçersiz.')
    raw=await file.read(5*1024*1024+1);p=parse_recipients(read_rows(raw,file.filename),phone_column)
    numbers=p['numbers'];contacts=db.scalars(select(Contact).where(Contact.kind==recipient_kind,Contact.phone.in_(numbers))).all() if numbers else []
    by_phone={c.phone:c for c in contacts};allowed=[];excluded=[]
    for n in numbers:
        c=by_phone.get(n)
        if c and bulk_eligible(db,c):allowed.append(c.id)
        else:
            blocked=any(r.opted_out or r.consent=='revoked' for r in db.scalars(select(Contact).where(Contact.phone==n)))
            excluded.append({'phone':n if user.role=='admin' else mask(n),'reason':'Ret / İPTAL / engelleme kaydı' if blocked else 'Doğrulanmış personel iletişim izni bulunamadı veya alıcı pasif' if recipient_kind=='staff' else 'Doğrulanmış WhatsApp pazarlama izni bulunamadı veya alıcı pasif'})
    token=secrets.token_urlsafe(32)
    db.add(SystemValue(key='bulk_preview:'+token,value=json.dumps({'user':user.id,'ids':allowed,'kind':recipient_kind,'expires':(now()+timedelta(minutes=30)).isoformat()})))
    audit(db,user.username,'bulk_file_preview',json.dumps({'unique':len(numbers),'eligible':len(allowed),'invalid':len(p['invalid'])}));db.commit()
    return {'token':token,'columns':p['columns'],'phone_column':p['phone_column'],'needs_column':p['needs_column'],'unique_count':len(numbers),'duplicate_count':p['duplicate_count'],'invalid_count':len(p['invalid']),'skipped_count':p['skipped_count'],'eligible_count':len(allowed),'excluded_count':len(excluded),'invalid_rows':p['invalid'][:200],'excluded_rows':excluded[:200],'eligible_preview':[{'phone':c.phone if user.role=='admin' else mask(c.phone)} for c in contacts if c.id in allowed][:200],'cost':None,'cost_notice':'Etkin Meta tarife kaynağı yok; yaklaşık ücret bilinmiyor. Gönderim ücretli olabilir.','permission_notice':('Personel listesi, kayıtlı ve iletişim izni doğrulanmış personellerle eşleştirilir; Excel dosyası izin yerine geçmez.' if recipient_kind=='staff' else 'Alıcı dosyası tek başına izin sayılmaz. Mevcut izinlerle veya yönetici tarafından doğrulanmış satış programı dışa aktarımıyla eşleştirilir.')}

@app.post('/api/bulk/permissions/import')
async def import_external_permissions(file:UploadFile=File(...),confirmed:bool=Form(False),phone_column:int|None=Form(None),user=Depends(admin),db=Depends(db_session)):
    if not confirmed:raise HTTPException(422,'Dosyanın satış programındaki doğrulanmış WhatsApp pazarlama ve ticari ileti izinli müşterilerin dışa aktarımı olduğunu onaylayın.')
    raw=await file.read(5*1024*1024+1);p=parse_recipients(read_rows(raw,file.filename),phone_column)
    if p['needs_column']:return {'needs_column':True,'columns':p['columns'],'imported':0}
    imported=blocked=0;digest=hashlib.sha256(raw).hexdigest()
    for n in p['numbers']:
        matches=db.scalars(select(Contact).where(Contact.phone==n)).all()
        if any(c.opted_out or c.consent=='revoked' for c in matches):blocked+=1;continue
        c=next((c for c in matches if c.kind=='customer'),None)
        if not c:c=Contact(kind='customer',phone=n,first_name='');db.add(c)
        # New objects have column defaults applied at flush.
        db.flush()
        if not c.active or c.preference!='whatsapp':blocked+=1;continue
        if not eligible(c):
            c.consent='verified';c.scope='marketing';c.source='HYS harici satış programı'
            c.evidence=f'external_marketing_export:{digest}:admin:{user.id}:imported:{now().isoformat()}';c.iys_status='external_verified'
        imported+=1
    audit(db,user.username,'external_permission_import',json.dumps({'sha256':digest,'matched':imported,'blocked':blocked,'verified_by':user.id}));db.commit()
    return {'imported':imported,'blocked':blocked,'invalid_count':len(p['invalid']),'duplicate_count':p['duplicate_count'],'notice':'Yönetici tarafından doğrulanan harici izinli liste eşleştirildi. Satış programına veya İYS API’sine bağlanılmadı. Ret kayıtları korunuyor.'}

class BulkCampaignInput(BaseModel):
    cards:list[CarouselCardInput]=Field(default_factory=list,max_length=10)
    token:str=Field(min_length=30,max_length=100)
    template_id:int
    variables:dict[str,str]=Field(default_factory=dict,max_length=20)
    header_variables:dict[str,str]=Field(default_factory=dict,max_length=20)
    button_variables:dict[str,str]=Field(default_factory=dict,max_length=10)
    header_media:HeaderMedia|None=None

def draft_result(db,c):
    cfg=json.loads(require(db,SystemValue,f'bulk_config:{c.id}').value)
    rows=[require(db,Contact,i) for i in json.loads(c.filters)['ids']]
    return {'campaign':{'id':c.id,'name':c.name,'status':c.status,'count':len(rows)},'recipients':[r.phone for r in rows][:200],'count':len(rows),'preview':cfg['preview'],'cost':None,'cost_notice':'Etkin tarife kaynağı yok; ücret bilinmiyor.','recipient_kind':c.kind,'dry_run':settings.dry_run,'live_send_enabled':settings.live_send_enabled}

@app.post('/api/bulk/campaign')
def create_bulk_campaign(data:BulkCampaignInput,user=Depends(admin),db=Depends(db_session)):
    return prepare_bulk(data,user,db)

@app.post('/api/bulk/campaign-with-media')
def create_bulk_media(data:str=Form(...,max_length=100000),file:UploadFile=File(...),user=Depends(admin),db=Depends(db_session)):
    from pydantic import ValidationError
    try:
        try:inputs=BulkCampaignInput.model_validate_json(data)
        except ValidationError:raise HTTPException(422,'Şablon alanlarını kontrol edin.')
        t=require(db,Template,inputs.template_id)
        kind=definitions(t).get('HEADER',{}).get('format','')
        if kind not in ('IMAGE','VIDEO'):raise HTTPException(422,'Dosya için IMAGE veya VIDEO başlıklı Marketing şablonu seçin.')
        asset=MediaUpload((file.filename or 'medya').replace('\\','/').rsplit('/',1)[-1],file.content_type or '',file.file.read(16*1024*1024+1))
        if asset.content_type not in ('image/jpeg','image/png','video/mp4'):raise HTTPException(422,'JPG, PNG veya MP4 dosyası seçin.')
        validate_upload(kind,asset)
        return prepare_bulk(inputs,user,db,asset)
    finally:file.file.close()

@app.post('/api/bulk/campaign-with-carousel')
def create_bulk_carousel(data:str=Form(...,max_length=100000),files:list[UploadFile]=File(...),card_indexes:str=Form(...,max_length=100),user=Depends(admin),db=Depends(db_session)):
    from pydantic import ValidationError
    try:
        try:
            inputs=BulkCampaignInput.model_validate_json(data);indexes=json.loads(card_indexes)
        except (ValidationError,ValueError):raise HTTPException(422,'Görsel kartlarını kontrol edin.')
        if not isinstance(indexes,list) or len(files)!=len(indexes) or not 1<=len(files)<=10 or any(type(i)!=int for i in indexes) or len(set(indexes))!=len(indexes):raise HTTPException(422,'Görsel kartları geçersiz.')
        assets={}
        for index,file in zip(indexes,files):
            asset=MediaUpload((file.filename or 'medya').replace('\\','/').rsplit('/',1)[-1],file.content_type or '',file.file.read(16*1024*1024+1))
            if asset.content_type not in ('image/jpeg','image/png','video/mp4'):raise HTTPException(422,'JPG, PNG veya MP4 dosyası seçin.')
            assets[index]=asset
        return prepare_bulk(inputs,user,db,card_uploads=assets)
    finally:
        for file in files:file.file.close()

def prepare_bulk(data,user,db,upload=None,card_uploads=None):
    p=json.loads(require(db,SystemValue,'bulk_preview:'+data.token).value)
    if p['user']!=user.id or datetime.fromisoformat(p['expires'])<now():raise HTTPException(403,'Önizleme süresi doldu; dosyayı yeniden yükleyin.')
    if not p['ids']:raise HTTPException(422,'Doğrulanmış izinli alıcı bulunamadı.')
    t=require(db,Template,data.template_id)
    if t.status!='APPROVED' or t.category!='MARKETING':raise HTTPException(403,'Meta onaylı Marketing şablonu zorunludur.')
    if any(not bulk_eligible(db,require(db,Contact,i)) for i in p['ids']):raise HTTPException(403,'İzinler değişti; dosyayı yeniden yükleyin.')
    inputs=data.model_dump(exclude={'token'});compiled,preview,media_kind=build_template(t,DirectMessage(**inputs),upload,card_uploads)
    if card_uploads:inputs['_card_hashes']={str(i):hashlib.sha256(a.content).hexdigest() for i,a in card_uploads.items()}
    if upload:inputs['_media_hash']=hashlib.sha256(upload.content).hexdigest()
    previous=db.get(SystemValue,'bulk_draft:'+data.token)
    if previous:
        old=json.loads(previous.value)
        if old['inputs']==inputs:
            existing=require(db,Campaign,old['id'])
            saved=db.get(SystemValue,f'bulk_config:{existing.id}')
            if saved and definition_matches(t,json.loads(saved.value)):return draft_result(db,existing)
            if existing.status!='draft':raise HTTPException(409,'Bu gönderim zaten başlatılmış; mevcut gönderim sonuçlarını kontrol edin.')
    c=Campaign(kind=p.get('kind','customer'),name='Toplu mesaj · '+t.name,description='İzinli Excel/CSV listesi',template_id=t.id,filters=json.dumps({'ids':p['ids']}),variables=json.dumps(data.variables),max_count=len(p['ids']),budget='')
    db.add(c);db.flush()
    cfg={'template':compiled,'preview':preview,'single_approval':c.kind!='staff','started':False,'test_only':False,'phone_number_id':settings.meta_phone_number_id,'waba_id':settings.meta_waba_id,'definition_hash':definition_hash(t),'definition_hash_version':2}
    if upload:
        MEDIA_DIR.mkdir(parents=True,exist_ok=True)
        if sum(p.stat().st_size for p in MEDIA_DIR.glob('*') if p.is_file())+len(upload.content)>512*1024*1024:raise HTTPException(413,'Yerel medya alanı doldu. Eski tamamlanmış taslak dosyalarını temizleyin.')
        key=secrets.token_hex(16);(MEDIA_DIR/key).write_bytes(upload.content)
        cfg['media_file']={'key':key,'sha256':inputs['_media_hash'],'filename':upload.filename,'content_type':upload.content_type,'kind':media_kind}
    if card_uploads:
        MEDIA_DIR.mkdir(parents=True,exist_ok=True)
        if sum(f.stat().st_size for f in MEDIA_DIR.glob('*') if f.is_file())+sum(len(a.content) for a in card_uploads.values())>512*1024*1024:raise HTTPException(413,'Yerel medya alanı doldu.')
        cfg['media_files']=[]
        carousel=next(x for x in compiled['components'] if x['type']=='carousel')
        for i,asset in card_uploads.items():
            key=secrets.token_hex(16);(MEDIA_DIR/key).write_bytes(asset.content)
            kind=next(x for x in carousel['cards'][i]['components'] if x['type']=='header')['parameters'][0]['type']
            cfg['media_files'].append({'key':key,'sha256':hashlib.sha256(asset.content).hexdigest(),'filename':asset.filename,'content_type':asset.content_type,'kind':kind,'card_index':i})
    db.add(SystemValue(key=f'bulk_config:{c.id}',value=json.dumps(cfg)));db.merge(SystemValue(key='bulk_draft:'+data.token,value=json.dumps({'id':c.id,'inputs':inputs})))
    audit(db,user.username,'bulk_campaign_create',str(c.id));db.commit();return draft_result(db,c)

class BulkConfirm(BaseModel):
    confirmed:bool=False
    phone:str|None=None

def canonical_components(components,body=''):
    """Meta example handles/URLs are review samples, not the sending definition."""
    if isinstance(components,str):components=json.loads(components)
    if not isinstance(components,list) or any(not isinstance(c,dict) for c in components):raise HTTPException(422,'Meta şablon bileşenleri geçersiz.')
    def clean(value):
        if isinstance(value,dict):return {k:clean(v) for k,v in value.items() if k not in ('example','examples')}
        if isinstance(value,list):return [clean(v) for v in value]
        return value
    result=[clean(c) for c in components]
    if not result:result=[{'type':'BODY','text':body}]
    # HEADER/BODY/FOOTER order is incidental; button order is semantically important.
    return sorted(result,key=lambda c:c.get('type',''))

def legacy_definition_hash(t):
    return hashlib.sha256(json.dumps([t.name,t.language,t.category,t.body,t.components]).encode()).hexdigest()

def definition_hash(t):
    return hashlib.sha256(json.dumps([t.name,t.language,t.category,canonical_components(t.components,t.body)],sort_keys=True,separators=(',',':')).encode()).hexdigest()

def definition_matches(t,cfg):
    expected=definition_hash(t) if cfg.get('definition_hash_version')==2 else legacy_definition_hash(t)
    return cfg.get('definition_hash')==expected

def check_live_template(t,cfg,db):
    if cfg['phone_number_id']!=settings.meta_phone_number_id or cfg['waba_id']!=settings.meta_waba_id:raise HTTPException(403,'Production numarası veya WABA değişti; dosyayı tekrar hazırlayın.')
    if t.status!='APPROVED' or t.category!='MARKETING':raise HTTPException(403,'Şablon onaylı Marketing durumunda değil.')
    if not definition_matches(t,cfg):raise HTTPException(403,'Şablon içeriği değişti; mesajı yeniden hazırlayın.')
    if not settings.dry_run:
        if not settings.live_send_enabled:raise HTTPException(403,'Canlı gönderim izni etkin değil.')
        if not connection_ok(db):
            # The user's Send confirmation may refresh an expired read-only access check.
            number=graph('GET',settings.meta_phone_number_id,params={'fields':'id,status'})
            numbers=graph('GET',settings.meta_waba_id+'/phone_numbers',params={'fields':'id','limit':100})
            matched=any(r.get('id')==settings.meta_phone_number_id for r in numbers.get('data',[]));seen=set()
            while not matched and numbers.get('paging',{}).get('next'):
                cursor=numbers.get('paging',{}).get('cursors',{}).get('after')
                if not cursor or cursor in seen:break
                seen.add(cursor)
                if len(seen)>100:break
                numbers=graph('GET',settings.meta_waba_id+'/phone_numbers',params={'fields':'id','limit':100,'after':cursor})
                matched=any(r.get('id')==settings.meta_phone_number_id for r in numbers.get('data',[]))
            if not matched or number.get('id')!=settings.meta_phone_number_id or number.get('status')!='CONNECTED':raise HTTPException(403,'Meta production numarasını CONNECTED ve bu WABA’ya bağlı olarak doğrulamadı.')
            fingerprint=hashlib.sha256((settings.meta_access_token+settings.meta_phone_number_id+settings.meta_waba_id+settings.meta_environment).encode()).hexdigest()
            db.merge(SystemValue(key='meta_verified',value=json.dumps({'fingerprint':fingerprint,'checked_at':now().isoformat()})))
        result=graph('GET',settings.meta_waba_id+'/message_templates',params={'name':t.name,'fields':'id,name,status,category,language,components','limit':100})
        r=next((r for r in result.get('data',[]) if r.get('name')==t.name and r.get('language')==t.language),None)
        if not r or r.get('status')!='APPROVED' or r.get('category')!='MARKETING' or r.get('id')!=t.meta_id:raise HTTPException(403,'Meta, şablonun onaylı Marketing durumunu doğrulamadı; şablonları yenileyin.')
        if canonical_components(r.get('components'),t.body)!=canonical_components(t.components,t.body):raise HTTPException(403,'Meta şablon içeriği değişti; şablonları yenileyip mesajı tekrar hazırlayın.')

@app.post('/api/bulk/campaign/{campaign_id}/start')
@app.post('/api/bulk/campaign/{campaign_id}/test')
def begin_bulk(campaign_id:int,data:BulkConfirm,request:Request,user=Depends(admin),db=Depends(db_session)):
    if not data.confirmed:raise HTTPException(422,'Alıcıları ve şablonu onaylayın.')
    c=require(db,Campaign,campaign_id);cfgrow=require(db,SystemValue,f'bulk_config:{c.id}');cfg=json.loads(cfgrow.value)
    test=request.url.path.endswith('/test')
    if cfg['started'] or c.status not in ('draft','completed'):raise HTTPException(409,'Gönderim zaten başladı veya örnek gönderim henüz tamamlanmadı.')
    if test and cfg['test_only']:raise HTTPException(409,'Örnek gönderim zaten başlatıldı; tekrar gönderilmedi.')
    if c.kind=='staff' and not settings.dry_run and not (c.first_approval and c.second_approval and c.first_approval!=c.second_approval):raise HTTPException(403,'Personel canlı gönderimi için iki farklı yönetici onayı gerekir.')
    check_live_template(require(db,Template,c.template_id),cfg,db)
    rows=[require(db,Contact,i) for i in json.loads(c.filters)['ids']]
    if any(not bulk_eligible(db,r) for r in rows):raise HTTPException(403,'İzinler değişti; listeyi tekrar hazırlayın.')
    if test:
        rows=[r for r in rows if r.phone==cell_phone(data.phone)]
        if len(rows)!=1:raise HTTPException(422,'Örnek alıcı yüklenen izinli listede bulunmalı.')
    stages=([cfg['media_file']] if cfg.get('media_file') else cfg.get('media_files',[])) if not settings.dry_run else []
    stage=bool(stages)
    claimed=db.execute(update(Campaign).where(Campaign.id==c.id,Campaign.status==c.status).values(status='preparing' if stage else 'running',first_approval=c.first_approval if c.kind=='staff' else user.id)).rowcount
    if claimed!=1:db.rollback();raise HTTPException(409,'Başka bir istek gönderimi başlattı.')
    if stage:
        db.commit() # Claim upload before external I/O; worker cannot run a preparing campaign.
        try:
            for asset in stages:
                db.refresh(c)
                if c.status!='preparing':raise HTTPException(409,'Medya yüklenirken kampanya durduruldu; alıcılar kuyruğa eklenmedi.')
                if not re.fullmatch(r'[a-f0-9]{32}',asset['key']):raise HTTPException(422,'Yerel medya kaydı geçersiz.')
                if asset.get('media_id'):continue
                content=(MEDIA_DIR/asset['key']).read_bytes()
                if hashlib.sha256(content).hexdigest()!=asset['sha256']:raise HTTPException(422,'Yerel medya dosyası değişmiş. Dosyayı yeniden seçin.')
                validate_upload(asset['kind'].upper(),MediaUpload(asset['filename'],asset['content_type'],content))
                media_id=upload_media(asset['filename'],content,asset['content_type'])
                parts=cfg['template']['components']
                if 'card_index' in asset:parts=next(p for p in parts if p['type']=='carousel')['cards'][asset['card_index']]['components']
                header=next(p for p in parts if p['type']=='header')
                header['parameters'][0][asset['kind']]['id']=media_id
                asset['media_id']=media_id
                cfgrow.value=json.dumps(cfg);db.commit()
            cfg['media_file']=None;cfg['media_files']=[];cfgrow.value=json.dumps(cfg);db.commit()
            for asset in stages:(MEDIA_DIR/asset['key']).unlink(missing_ok=True)
        except HTTPException:
            db.refresh(c)
            if c.status=='preparing':c.status='draft'
            db.commit();raise
        except Exception:
            db.refresh(c)
            if c.status=='preparing':c.status='draft'
            db.commit();raise HTTPException(502,'Medya yüklemesi tamamlanamadı; hiçbir alıcı kuyruğa eklenmedi.')
        db.refresh(c)
        if c.status!='preparing':raise HTTPException(409,'Medya yüklenirken kampanya durduruldu; alıcılar kuyruğa eklenmedi.')
        c.status='running'
    existing=set(db.scalars(select(Message.phone).where(Message.campaign_id==c.id)));queued=0
    for r in rows:
        if r.phone in existing:continue
        db.add(Message(campaign_id=c.id,contact_id=r.id,phone=r.phone,body=cfg['preview']));queued+=1
    cfg['test_only']=test
    cfg['execution_dry_run']=settings.dry_run
    if not test:cfg['started']=True
    cfgrow.value=json.dumps(cfg)
    if not queued:c.status='completed'
    audit(db,user.username,'bulk_test_start' if test else 'bulk_start',json.dumps({'id':c.id,'queued':queued}));db.commit()
    return {'queued':queued,'already_targeted':len(existing),'dry_run':settings.dry_run}

def safe_error(value):
    try:
        p=json.loads(value)
        if isinstance(p,dict):value=str(p.get('message','Meta hatası'))+(f" (Meta kodu: {p['code']})" if 'code' in p else '')
    except (ValueError,TypeError):pass
    code=re.search(r'\b(131026|131049|130472|131048|131056|130429)\b',value)
    if code:
        from app.meta import delivery_error_message
        value=delivery_error_message(int(code.group(1)))+f' (Meta kodu: {code.group(1)})'
    for secret in (settings.meta_access_token,settings.meta_app_secret,settings.meta_verify_token):
        if secret:value=value.replace(secret,'[gizli]')
    return value

@app.get('/api/bulk/campaign/{campaign_id}')
def bulk_campaign_status(campaign_id:int,page:int=Query(1,ge=1),user=Depends(actor),db=Depends(db_session)):
    c=require(db,Campaign,campaign_id)
    if c.kind!='customer':raise HTTPException(404,'Müşteri kampanyası bulunamadı.')
    rows=db.scalars(select(Message).where(Message.campaign_id==c.id)).all()
    counts={s:sum(m.status==s for m in rows) for s in ['queued','retry','sending','accepted','sent','delivered','read','failed','blocked','uncertain','cancelled','dry_run']}
    cfgrow=db.get(SystemValue,f'bulk_config:{c.id}');cfg=json.loads(cfgrow.value) if cfgrow else {}
    failures=[{'phone':m.phone if user.role=='admin' else mask(m.phone),'status':m.status,'error':safe_error(m.error)} for m in rows if m.status in ('failed','blocked','uncertain')]
    rows.sort(key=lambda m:m.id)
    recipients=[{'id':m.id,'phone':m.phone if user.role=='admin' else mask(m.phone),'status':m.status,'error':safe_error(m.error) if m.status not in ('delivered','read') else '', 'attempts':m.attempts,'next_attempt':m.next_attempt.isoformat() if m.status=='retry' else None} for m in rows[(page-1)*50:page*50]]
    queue_notice={'paused':'Kampanya duraklatılmış; bekleyen mesajlar gönderilmez.','cancelled':'Kampanya durdurulmuş; iptal edilen mesajlar gönderilmez.'}.get(c.status,'')
    worker=worker_health()
    if not queue_notice and counts['queued']+counts['retry']+counts['sending']:
        if c.scheduled and c.scheduled>now():queue_notice='Planlanan gönderim zamanı bekleniyor.'
        elif settings.deployment_send_lock:queue_notice='Dağıtım gönderim kilidi açık; kuyruk işlenmez.'
        elif not settings.bulk_dispatch_enabled:queue_notice='Toplu kuyruk kapalı: BULK_DISPATCH_ENABLED etkin değil.'
        elif not settings.dry_run and not settings.live_send_enabled:queue_notice='Canlı gönderim kapalı; bekleyen mesajlar gönderilmez.'
        elif worker.get('configuration_matches') is False:queue_notice='Worker ile backend veritabanı veya Meta yapılandırması eşleşmiyor. Worker değişkenlerini kontrol edin.'
        elif worker.get('send_locked') is True:queue_notice='Worker gönderim kilidi açık; worker servisindeki DEPLOYMENT_SEND_LOCK ayarını kontrol edin.'
        elif worker.get('dispatch_enabled') is False:queue_notice='Worker kuyruğu kapalı; worker servisindeki BULK_DISPATCH_ENABLED ayarını kontrol edin.'
        elif not settings.dry_run and worker.get('dry_run') is True:queue_notice='Worker simülasyon modunda; backend ile gönderim modu eşleşmiyor.'
        elif not settings.dry_run and worker.get('live_enabled') is False:queue_notice='Worker canlı gönderimi kapalı; worker servisindeki LIVE_SEND_ENABLED ayarını kontrol edin.'
        elif worker['state']=='missing':queue_notice='Aktif worker sinyali yok. Ayrı Railway worker servisini ve Redis bağlantısını kontrol edin.'
        elif worker['state']=='unavailable':queue_notice='Worker durumu Redis üzerinden doğrulanamadı; bağlantı kontrolü gerekiyor.'
        elif worker['state']=='error':queue_notice='Worker kuyruk işleme hatası bildiriyor. Worker Deploy Logs içindeki worker_dispatch_failed kaydını kontrol edin.'
        else:
            rate=db.get(SystemValue,'bulk_rate:'+now().date().isoformat())
            try:daily=json.loads(rate.value).get('count',0) if rate else 0
            except (ValueError,TypeError,AttributeError):daily=0
            if not isinstance(daily,int):daily=0
            if daily>=settings.bulk_daily_limit:queue_notice='Günlük gönderim sınırına ulaşıldı; kuyruk sonraki güne kadar bekler.'
            elif any(m.status=='retry' and m.next_attempt>now() for m in rows):queue_notice='Meta hız sınırı veya geçici hata nedeniyle yeniden deneme zamanı bekleniyor.'
    return {**counts,'waiting':counts['queued']+counts['retry']+counts['sending'],'total':len(rows),'audience_count':c.max_count,'campaign':{'id':c.id,'name':c.name,'status':c.status,'kind':c.kind,'first_approval':c.first_approval,'second_approval':c.second_approval},'started':cfg.get('started',False),'test_only':cfg.get('test_only',False),'failures':failures[:200],'recipients':recipients,'recipient_page':page,'recipient_pages':max(1,(len(rows)+49)//50),'queue_notice':queue_notice,'worker':worker,'dry_run_enabled':settings.dry_run,'live_send_enabled':settings.live_send_enabled,'connection_verified':connection_ok(db)}

@app.get('/api/bulk/campaign/{campaign_id}/failures.xlsx')
def export_failures(campaign_id:int,user=Depends(admin),db=Depends(db_session)):
    require(db,Campaign,campaign_id)
    from openpyxl import Workbook
    wb=Workbook();ws=wb.active;ws.title='Gönderim hataları';ws.append(['Telefon','Durum','Hata açıklaması','Meta mesaj kimliği'])
    for m in db.scalars(select(Message).where(Message.campaign_id==campaign_id,Message.status.in_(['failed','blocked','uncertain']))):ws.append([safe_cell(m.phone),m.status,safe_cell(safe_error(m.error)),m.meta_id or ''])
    out=io.BytesIO();wb.save(out);out.seek(0);audit(db,user.username,'bulk_failure_export',str(campaign_id));db.commit()
    return StreamingResponse(out,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':f'attachment; filename="hys-hatalar-{campaign_id}.xlsx"'})
