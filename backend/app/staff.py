"""Independent staff audience, private expiring assets and durable at-most-once queue."""
import hashlib,json,secrets,re,subprocess,tempfile
from urllib.parse import urlsplit
from pathlib import Path
from datetime import timedelta
from fastapi import Depends,HTTPException,UploadFile,File,Request
from pydantic import BaseModel,Field
from sqlalchemy import select,update,func,exists
from sqlalchemy.orm import aliased
from app.core import *
from app.main import app,admin,db_session,require,serial,connection_ok
from app.meta import graph,upload_media
from app.recipient_files import read_rows,header,cell_phone
from app.template_components import definitions,validate_upload,MediaUpload

# Staff lists and files are restricted to administrators, including read access.
def announcement(db,id):return require(db,StaffAnnouncement,id)
def editable(a):
    if a.status!='draft':raise HTTPException(409,'Gönderilmiş duyurunun alıcıları ve dosyaları değiştirilemez.')
def summary(a):return {key:value for key,value in serial(a).items() if key not in ('config','preview_token','preview_expires')}
def assets(db,id):return list(db.scalars(select(StaffAsset).where(StaffAsset.announcement_id==id).order_by(StaffAsset.position)))
def window_open(db,n):
    last=db.scalar(select(func.max(Message.created)).where(Message.phone==n,Message.direction=='in'))
    return last is not None and timedelta(0)<=now()-last<timedelta(hours=24)
def blocked(db,c):return not c.active or c.opted_out or bool(db.scalar(select(Contact.id).where(Contact.phone==c.phone,Contact.opted_out.is_(True)).limit(1)))
def template(db,id,kind):
    t=require(db,Template,id);d=definitions(t)
    if t.status!='APPROVED' or d.get('HEADER',{}).get('format','').upper()!=kind.upper() or set(d)-{'HEADER','BODY','FOOTER'} or '{{' in t.body:
        raise HTTPException(422,f'{kind}: onaylı, değişkensiz ve tek medya başlıklı şablon seçin.')
    return t

def chosen(db,cfg):
    q=select(Contact).where(Contact.kind=='staff')
    if cfg['target']=='stores':q=q.where(Contact.store.in_(cfg['stores']))
    elif cfg['target']=='people':q=q.where(Contact.id.in_(cfg['people']))
    return [c for c in db.scalars(q.order_by(Contact.id)) if not blocked(db,c)]

class Draft(BaseModel):name:str=Field(min_length=1,max_length=200)
class Selection(BaseModel):
    target:str='all'
    stores:list[str]=Field(default_factory=list,max_length=1000)
    people:list[int]=Field(default_factory=list,max_length=10000)
    document_template:int
    video_template:int | None=None
class Approval(BaseModel):
    token:str
    confirm_live:bool=False

@app.get('/api/staff/people')
def people(user=Depends(admin),db=Depends(db_session)):
    return [dict(id=c.id,name=(c.first_name+' '+c.last_name).strip(),phone=c.phone,store=c.store,blocked=blocked(db,c)) for c in db.scalars(select(Contact).where(Contact.kind=='staff').order_by(Contact.first_name))]

@app.post('/api/staff/import')
async def import_staff(file:UploadFile=File(...),user=Depends(admin),db=Depends(db_session)):
    raw=await file.read(5*1024*1024+1);rows=read_rows(raw,file.filename)
    headers=[header(x) for x in rows[0]]
    def column(names):return next((i for i,h in enumerate(headers) if h in names),None)
    ni=column({'adsoyad','adisoyadi','isimsoyisim','fullname','name','ad','isim'});pi=column({'telefon','telefonnumarasi','telefonno','phone','gsm','ceptelefonu'});si=column({'magaza','magazaadi','store'})
    if pi is None:raise HTTPException(422,'Telefon sütunu zorunludur. Ad Soyad ve Mağaza isteğe bağlıdır.')
    errors=[];seen=set();count=0;duplicates=0
    if len(rows)>10001:raise HTTPException(422,'En fazla 10.000 personel yükleyin.')
    for index,row in enumerate(rows[1:],2):
        if not any(str(v or '').strip() for v in row):continue
        get=lambda i:str(row[i] or '').strip() if i is not None and i<len(row) else ''
        n=cell_phone(row[pi] if pi<len(row) else None);name=get(ni);store=get(si)
        if not n or len(name)>100 or len(store)>160:
            errors.append({'row':index,'reason':'Geçerli cep telefonu gerekli; ad soyad en fazla 100, mağaza en fazla 160 karakter olabilir.'});continue
        if n in seen:duplicates+=1;continue
        seen.add(n);c=db.scalar(select(Contact).where(Contact.kind=='staff',Contact.phone==n))
        if not c:c=Contact(kind='staff',phone=n,first_name=name);db.add(c)
        if name:c.first_name=name;c.last_name=''
        if store:c.store=store
        count+=1
    audit(db,user.username,'staff_import',f'{count} kayıt; {len(errors)} hata');db.commit()
    return {'imported':count,'duplicates':duplicates,'errors':errors}

@app.post('/api/staff/announcements')
def create(data:Draft,user=Depends(admin),db=Depends(db_session)):
    a=StaffAnnouncement(owner_id=user.id,name=data.name);db.add(a);db.commit();return serial(a)

@app.get('/api/staff/announcements')
def listing(user=Depends(admin),db=Depends(db_session)):
    return [summary(a) for a in db.scalars(select(StaffAnnouncement).order_by(StaffAnnouncement.id.desc()).limit(100))]

class UploadTicket(BaseModel):
    filename:str=Field(min_length=1,max_length=200)
    size:int=Field(gt=0)

@app.post('/api/staff/announcements/{id}/upload-ticket')
def upload_ticket(id:int,data:UploadTicket,user=Depends(admin),db=Depends(db_session)):
    a=announcement(db,id);editable(a)
    origin=settings.staff_upload_origin.rstrip('/')
    if settings.app_environment=='production':
        parsed=urlsplit(origin)
        if parsed.scheme!='https' or not parsed.hostname or not parsed.hostname.endswith('.up.railway.app') or parsed.path or parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment:raise HTTPException(503,'STAFF_UPLOAD_ORIGIN Railway HTTPS origin olarak ayarlanmalıdır.')
    ext=Path(data.filename).suffix.lower()
    if ext not in ('.pdf','.mp4'):raise HTTPException(422,'Yalnızca PDF ve MP4 yükleyin.')
    if data.size>(100 if ext=='.pdf' else 16)*1024*1024:raise HTTPException(413,'PDF en fazla 100 MB, MP4 en fazla 16 MB olabilir.')
    token=secrets.token_urlsafe(32);key='staff_upload:'+hashlib.sha256(token.encode()).hexdigest()
    db.add(SystemValue(key=key,value=json.dumps({'owner':user.id,'announcement':id,'filename':data.filename,'size':data.size,'expires':(now()+timedelta(minutes=10)).isoformat()})));db.commit()
    return {'url':origin+'/api/staff-upload/'+token}

@app.put('/api/staff-upload/{token}')
async def direct_upload(token:str,request:Request,db=Depends(db_session)):
    if settings.app_environment=='production' and request.headers.get('origin')!=settings.panel_origin:raise HTTPException(403,'Panel kaynağı doğrulanamadı.')
    key='staff_upload:'+hashlib.sha256(token.encode()).hexdigest();grant=db.get(SystemValue,key)
    if not grant:raise HTTPException(403,'Yükleme izni geçersiz veya kullanılmış.')
    saved=grant.value;data=json.loads(saved)
    if datetime.fromisoformat(data['expires'])<now():raise HTTPException(403,'Yükleme izninin süresi doldu.')
    user=db.get(User,data['owner'])
    if not user or user.role!='admin':raise HTTPException(403,'Yönetici yetkisi gerekiyor.')
    claimed=db.execute(update(SystemValue).where(SystemValue.key==key,SystemValue.value==saved).values(value=json.dumps({**data,'expires':now().isoformat()}))).rowcount
    db.commit()
    if claimed!=1:raise HTTPException(409,'Yükleme izni zaten kullanıldı.')
    # Spill large requests to a private OS temporary file; always remove it.
    with tempfile.SpooledTemporaryFile(max_size=1024*1024,mode='w+b') as temporary:
        size=0
        async for chunk in request.stream():
            size+=len(chunk)
            if size>data['size']:raise HTTPException(413,'Dosya belirtilen boyutu aşıyor.')
            temporary.write(chunk)
        if size!=data['size']:raise HTTPException(422,'Dosya eksik yüklendi.')
        temporary.seek(0)
        upload=UploadFile(filename=data['filename'],file=temporary)
        try:return await add_asset(data['announcement'],upload,user,db)
        finally:await upload.close()

@app.post('/api/staff/announcements/{id}/assets')
async def add_asset(id:int,file:UploadFile=File(...),user=Depends(admin),db=Depends(db_session)):
    a=db.scalar(select(StaffAnnouncement).where(StaffAnnouncement.id==id).with_for_update());
    if not a:raise HTTPException(404,'Duyuru bulunamadı.')
    editable(a);existing=assets(db,id);ext=Path(file.filename or '').suffix.lower()
    if ext not in ('.pdf','.mp4'):raise HTTPException(422,'Yalnızca PDF ve MP4 yükleyin.')
    kind='document' if ext=='.pdf' else 'video';mime='application/pdf' if kind=='document' else 'video/mp4';limit=(100 if kind=='document' else 16)*1024*1024
    if kind=='document' and existing or kind=='video' and not existing:raise HTTPException(422,'Önce tek PDF yükleyin, ardından videoları ekleyin.')
    if len(existing)>=11:raise HTTPException(422,'En fazla bir PDF ve 10 video ekleyin.')
    raw=await file.read(limit+1)
    if len(raw)>limit:raise HTTPException(413,f'{kind}: en fazla {limit//1024//1024} MB.')
    name=re.sub(r'[^\w. -]','_',Path(file.filename or '').name)[:200]
    validate_upload(kind.upper(),MediaUpload(name,mime,raw))
    if kind=='video':
        from app.video_processing import prepare_video,VideoError
        try:raw,info=prepare_video(raw,name)
        except VideoError as e:raise HTTPException(503 if e.code in ('tools_missing','ffmpeg_missing','ffprobe_missing') else 422,e.message)
    if any(x.digest==hashlib.sha256(raw).hexdigest() for x in existing):raise HTTPException(409,'Bu dosya duyuruda zaten var.')
    db.add(StaffAsset(announcement_id=id,position=len(existing),filename=name,kind=kind,content_type=mime,content=raw,size=len(raw),digest=hashlib.sha256(raw).hexdigest(),expires=now()+timedelta(hours=24)))
    a.preview_token='';db.commit();return {'ok':True}

class PreparedVideo(BaseModel):
    video_job_id:str

@app.post('/api/staff/announcements/{id}/videos')
def attach_video(id:int,data:PreparedVideo,user=Depends(admin),db=Depends(db_session)):
    from app.video_jobs import ready_video
    a=db.scalar(select(StaffAnnouncement).where(StaffAnnouncement.id==id).with_for_update())
    if not a:raise HTTPException(404,'Duyuru bulunamadı.')
    editable(a);files=assets(db,id)
    if not files:raise HTTPException(422,'Önce PDF yükleyin.')
    if len(files)>=11:raise HTTPException(422,'En fazla 10 video ekleyin.')
    job=ready_video(db,data.video_job_id,user);digest=hashlib.sha256(job.output).hexdigest()
    if any(f.digest==digest or f.video_job_id==job.id for f in files):raise HTTPException(409,'Bu video duyuruda zaten var.')
    db.add(StaffAsset(announcement_id=id,position=len(files),filename=Path(job.filename).stem+'.mp4',kind='video',content_type='video/mp4',content=job.output,size=job.output_size,digest=digest,expires=job.expires,video_job_id=job.id))
    a.preview_token='';db.commit();return {'ok':True}

@app.post('/api/staff/announcements/{id}/preview')
def preview(id:int,data:Selection,user=Depends(admin),db=Depends(db_session)):
    a=announcement(db,id);editable(a);cfg=data.model_dump()
    if data.target not in ('all','stores','people'):raise HTTPException(422,'Hedef türü geçersiz.')
    files=assets(db,id)
    if not files or files[0].kind!='document' or any(f.expires<=now() or f.content is None for f in files):raise HTTPException(422,'Geçerli PDF yükleyin; geçici dosyalar 24 saat saklanır.')
    doc=template(db,data.document_template,'document');vid=template(db,data.video_template,'video') if any(f.kind=='video' for f in files) else None
    recipients=chosen(db,cfg)
    if not recipients:raise HTTPException(422,'Gönderilebilir personel bulunamadı.')
    cfg['recipients']=[c.id for c in recipients];cfg['recipient_snapshot']={str(c.id):[c.phone,c.first_name,c.last_name,c.store] for c in recipients};cfg['templates']={str(t.id):serial(t) for t in (doc,vid) if t}
    cfg['phone_number_id']=settings.meta_phone_number_id;cfg['waba_id']=settings.meta_waba_id
    paid=sum(not window_open(db,c.phone) for c in recipients)*len(files)
    prices=[settings.staff_document_unit_price if f.kind=='document' else settings.staff_video_unit_price for f in files]
    cost=None if any(p is None for p in prices) else sum(prices)*paid/len(files)
    a.config=json.dumps(cfg);a.preview_token=secrets.token_hex(32);a.preview_expires=now()+timedelta(minutes=10);db.commit()
    return {'token':a.preview_token,'people':len(recipients),'files':len(files),'paid_messages':paid,'paid_messages_upper_bound':len(recipients)*len(files),'estimated_cost':cost,'currency':settings.staff_price_currency,'simulation':settings.dry_run,'recipients':[{'name':(c.first_name+' '+c.last_name).strip(),'phone':c.phone,'store':c.store} for c in recipients],'template_bodies':{'document':doc.body,'video':vid.body if vid else ''},'notice':'Pencere gönderim anında tekrar kontrol edilir; ücretli mesaj sayısı artabilir. Ücret tahminidir.'}

@app.post('/api/staff/announcements/{id}/send')
def approve(id:int,data:Approval,user=Depends(admin),db=Depends(db_session)):
    a=db.scalar(select(StaffAnnouncement).where(StaffAnnouncement.id==id).with_for_update())
    if not a:raise HTTPException(404,'Duyuru bulunamadı.')
    if a.status!='draft':return {'id':id,'status':a.status,'duplicate':True}
    if not a.preview_token or not secrets.compare_digest(data.token,a.preview_token) or not a.preview_expires or a.preview_expires<now():raise HTTPException(409,'Önizlemeyi yenileyin.')
    if not settings.dry_run and (not data.confirm_live or not settings.staff_dispatch_enabled or settings.deployment_send_lock or not settings.live_send_enabled or not connection_ok(db)):raise HTTPException(403,'Panelde canlı gönderim onayı ve etkin Meta/worker bağlantısı gerekli.')
    cfg=json.loads(a.config)
    if cfg['phone_number_id']!=settings.meta_phone_number_id or cfg['waba_id']!=settings.meta_waba_id:raise HTTPException(409,'Meta hesabı değişti; önizlemeyi yenileyin.')
    files=assets(db,id)
    if any(f.expires<=now() or not f.content for f in files):raise HTTPException(409,'Dosyalar zaman aşımına uğradı.')
    for key,saved in cfg['templates'].items():
        if serial(require(db,Template,int(key)))!=saved:raise HTTPException(409,'Şablon değişti; önizlemeyi yenileyin.')
    for cid in cfg['recipients']:
        c=require(db,Contact,cid)
        if c.kind!='staff' or blocked(db,c) or [c.phone,c.first_name,c.last_name,c.store]!=cfg['recipient_snapshot'][str(cid)]:raise HTTPException(409,'Alıcı listesi değişti; önizlemeyi yenileyin.')
        for f in files:db.add(StaffDelivery(announcement_id=id,contact_id=cid,asset_id=f.id,phone=c.phone,name=(c.first_name+' '+c.last_name).strip(),store=c.store))
    a.simulation=settings.dry_run;a.sender_id=settings.meta_phone_number_id;a.status='running'
    audit(db,user.username,'staff_approve',f'{id}; simulation={a.simulation}');db.commit();return {'id':id,'status':a.status}

@app.post('/api/staff/announcements/{id}/{action}')
def control(id:int,action:str,user=Depends(admin),db=Depends(db_session)):
    a=db.scalar(select(StaffAnnouncement).where(StaffAnnouncement.id==id).with_for_update())
    if not a:raise HTTPException(404,'Duyuru bulunamadı.')
    if action not in ('pause','resume','cancel'):raise HTTPException(404,'İşlem bulunamadı.')
    if action=='resume' and a.status!='paused' or action=='pause' and a.status!='running' or action=='cancel' and a.status not in ('draft','running','paused'):raise HTTPException(409,'Bu durumda işlem yapılamaz.')
    a.status={'pause':'paused','resume':'running','cancel':'cancelled'}[action]
    if action=='cancel':
        db.execute(update(StaffDelivery).where(StaffDelivery.announcement_id==id,StaffDelivery.status=='queued').values(status='cancelled'))
        for f in assets(db,id):f.content=None
    audit(db,user.username,'staff_'+action,str(id));db.commit();return {'status':a.status}

@app.get('/api/staff/announcements/{id}')
def detail(id:int,page:int=1,user=Depends(admin),db=Depends(db_session)):
    a=announcement(db,id);files=assets(db,id)
    total=db.scalar(select(func.count(func.distinct(StaffDelivery.contact_id))).where(StaffDelivery.announcement_id==id))
    page=max(1,min(page,max(1,(total+49)//50)))
    contacts=list(db.scalars(select(StaffDelivery.contact_id).where(StaffDelivery.announcement_id==id).distinct().order_by(StaffDelivery.contact_id).offset((page-1)*50).limit(50)))
    rows=list(db.scalars(select(StaffDelivery).where(StaffDelivery.announcement_id==id,StaffDelivery.contact_id.in_(contacts)).order_by(StaffDelivery.id)))
    grouped={};rank={'queued':0,'sending':0,'accepted':1,'sent':1,'delivered':2,'read':3,'dry_run':4}
    for r in rows:
        g=grouped.setdefault(r.contact_id,{'name':r.name,'phone':r.phone,'store':r.store,'messages':[]});g['messages'].append(serial(r))
    for g in grouped.values():
        statuses=[r['status'] for r in g['messages']]
        g['status']=next((s for s in ('uncertain','failed','cancelled') if s in statuses),min(statuses,key=lambda s:rank.get(s,0)))
    return {'announcement':summary(a),'page':page,'recipient_total':total,'pages':max(1,(total+49)//50),'files':[{'id':f.id,'filename':f.filename,'kind':f.kind,'size':f.size,'video_job_id':f.video_job_id} for f in files],'recipients':list(grouped.values())}

def staff_delivery(db,item):
    row=db.scalar(select(StaffDelivery).where(StaffDelivery.meta_id==item['id']))
    if not row:return
    new=item.get('status');rank={'accepted':0,'sent':1,'delivered':2,'read':3}
    if new in rank and rank[new]>rank.get(row.status,-1) and (row.status!='failed' or new in ('delivered','read')):row.status=new;row.error=''
    elif new=='failed' and row.status not in ('delivered','read'):row.status='failed';row.error='Meta teslimat hatası; otomatik tekrar yapılmaz.'

def dispatch_staff(limit=1):
    with Session() as db:
        for grant in db.scalars(select(SystemValue).where(SystemValue.key.like('staff_upload:%'))):
            if json.loads(grant.value)['expires']<now().isoformat():db.delete(grant)
        for f in db.scalars(select(StaffAsset).where(StaffAsset.expires<=now(),StaffAsset.content.is_not(None))):f.content=None
        for r in db.scalars(select(StaffDelivery).where(StaffDelivery.status=='sending',StaffDelivery.attempted<now()-timedelta(minutes=10))):r.status='uncertain';r.error='İşleyici kesintisi; tekrar gönderilmez.'
        db.commit()
        prior=aliased(StaffDelivery);prior_asset=aliased(StaffAsset)
        waiting=exists(select(prior.id).join(prior_asset,prior.asset_id==prior_asset.id).where(prior.announcement_id==StaffDelivery.announcement_id,prior.contact_id==StaffDelivery.contact_id,prior_asset.position<StaffAsset.position,prior.status.in_(['queued','sending','accepted','sent'])))
        failed=exists(select(prior.id).join(prior_asset,prior.asset_id==prior_asset.id).where(prior.announcement_id==StaffDelivery.announcement_id,prior.contact_id==StaffDelivery.contact_id,prior_asset.position<StaffAsset.position,prior.status.in_(['failed','uncertain','cancelled'])))
        ids=list(db.scalars(select(StaffDelivery.id).join(StaffAnnouncement).join(StaffAsset,StaffDelivery.asset_id==StaffAsset.id).where(StaffAnnouncement.status=='running',StaffDelivery.status=='queued',StaffAnnouncement.simulation.is_(True)|~waiting|failed).order_by(StaffDelivery.id).limit(max(100,limit))))
    sent=0
    for id in ids:
        if sent>=limit:break
        if process_staff(id):sent+=1
    with Session() as db:
        for a in db.scalars(select(StaffAnnouncement).where(StaffAnnouncement.status=='running')):
            if not db.scalar(select(StaffDelivery.id).where(StaffDelivery.announcement_id==a.id,StaffDelivery.status.in_(['queued','sending','accepted','sent'])).limit(1)):a.status='completed'
        db.commit()

def process_staff(id):
    with Session() as db:
        r=db.get(StaffDelivery,id)
        if not r or r.status!='queued':return False
        a=db.scalar(select(StaffAnnouncement).where(StaffAnnouncement.id==r.announcement_id).with_for_update())
        if not a or a.status!='running':return False
        f=db.get(StaffAsset,r.asset_id);cfg=json.loads(a.config);c=db.get(Contact,r.contact_id)
        prior=list(db.scalars(select(StaffDelivery).join(StaffAsset).where(StaffDelivery.announcement_id==a.id,StaffDelivery.contact_id==r.contact_id,StaffAsset.position<f.position)))
        if any(p.status in ('failed','uncertain','cancelled') for p in prior):r.status='failed';r.error='Önceki dosya teslim edilemedi.';db.commit();return False
        if any(p.status not in ('delivered','read','dry_run') for p in prior):return False
        if not c or c.kind!='staff' or c.phone!=r.phone or blocked(db,c):r.status='failed';r.error='Alıcı devre dışı veya ret kaydı var.';db.commit();return False
        if a.simulation:r.status='dry_run';db.commit();return True
        if settings.dry_run or not settings.staff_dispatch_enabled or settings.deployment_send_lock or not settings.live_send_enabled or not connection_ok(db):return False
        if a.sender_id!=settings.meta_phone_number_id or cfg['waba_id']!=settings.meta_waba_id:a.status='paused';db.commit();return False
        if f.expires<=now():a.status='paused';r.error='Medya süresi doldu; yeni duyuru hazırlayın.';db.commit();return False
        try:t=template(db,cfg['document_template'] if f.kind=='document' else cfg['video_template'],f.kind)
        except HTTPException:a.status='paused';r.error='Onaylı şablon kullanılamıyor.';db.commit();return False
        if serial(t)!=cfg['templates'][str(t.id)]:a.status='paused';db.commit();return False
        from app.worker import reserve_bulk_slot
        if not reserve_bulk_slot(db):return False
        # CAS + committed claim before any network call: ambiguous/crashed sends never retry.
        if db.execute(update(StaffDelivery).where(StaffDelivery.id==id,StaffDelivery.status=='queued').values(status='sending',attempted=now())).rowcount!=1:db.rollback();return False
        db.commit();db.refresh(a);db.refresh(r)
        if a.status!='running':r.status='queued' if a.status=='paused' else 'cancelled';db.commit();return False
        try:
            f=db.scalar(select(StaffAsset).where(StaffAsset.id==f.id).with_for_update());db.refresh(c)
            if blocked(db,c):raise HTTPException(403,'Alıcı ret kaydı var.')
            if not f.media_id:
                if not f.content:raise HTTPException(410,'Geçici dosya süresi doldu.')
                f.media_id=upload_media(f.filename,f.content,f.content_type);f.content=None;db.commit()
            db.refresh(a)
            if a.status!='running':r.status='queued' if a.status=='paused' else 'cancelled';db.commit();return False
            media={'id':f.media_id}
            if f.kind=='document':media['filename']=f.filename
            payload={'messaging_product':'whatsapp','to':r.phone.lstrip('+')}
            if window_open(db,r.phone):payload.update(type=f.kind,**{f.kind:media})
            else:payload.update(type='template',template={'name':t.name,'language':{'code':t.language},'components':[{'type':'header','parameters':[{'type':f.kind,f.kind:media}]}]})
            response=graph('POST',f'{a.sender_id}/messages',payload);mid=response.get('messages',[{}])[0].get('id')
            if not isinstance(mid,str) or not mid.startswith('wamid.') or len(mid)>200:raise ValueError()
            r.meta_id=mid;r.status='accepted';db.flush()
            for event in db.scalars(select(WebhookItem).where(WebhookItem.meta_id==mid,WebhookItem.kind=='status').order_by(WebhookItem.created)):staff_delivery(db,json.loads(event.payload))
        except HTTPException as e:
            r.status='uncertain' if e.status_code>=500 else 'failed';r.error='Meta isteği tamamlanamadı; otomatik tekrar yok.'
        except Exception:r.status='uncertain';r.error='API sonucu belirsiz; otomatik tekrar yok.'
        db.commit();return True
