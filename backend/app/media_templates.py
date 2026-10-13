"""Administrator-confirmed, deduplicated document/video template applications."""
import hashlib,json
from fastapi import Depends,HTTPException
from pydantic import BaseModel,Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.core import *
from app.main import app,admin,db_session,require,connection_ok
from app.meta import graph,upload_template_sample
from app.template_components import MediaUpload

class Proposal(BaseModel):
    name:str=Field(pattern=r'^[a-z0-9_]{1,150}$')
    category:str=Field(pattern='^(UTILITY|MARKETING)$')
    body:str=Field(min_length=1,max_length=1024)
    footer:str=Field(default='',max_length=60)
    asset_id:int
    confirmed:bool=False

@app.post('/api/templates/media-review')
def submit_media(data:Proposal,user=Depends(admin),db=Depends(db_session)):
    if not data.confirmed:raise HTTPException(422,'Metin ve örnek dosyanın Meta incelemesine gönderilmesini onaylayın.')
    if not data.body.strip() or '{{' in data.body or '{{' in data.footer:raise HTTPException(422,'Bu duyuru şablonunda sabit metin kullanın; değişken eklemeyin.')
    asset=require(db,StaffAsset,data.asset_id);announcement=require(db,StaffAnnouncement,asset.announcement_id)
    if announcement.status!='draft' or asset.expires<=now() or not asset.content:raise HTTPException(422,'Örnek dosya geçersiz veya süresi dolmuş. Yeni bir duyuru taslağında dosya yükleyin.')
    if not settings.dry_run and (settings.meta_environment!='production' or not connection_ok(db)):raise HTTPException(403,'Başvuru için production Meta hesabı ve doğrulanmış bağlantı gerekiyor.')
    if db.scalar(select(Template.id).where(Template.name==data.name)):raise HTTPException(409,'Bu adla şablon zaten mevcut. Durumunu yenileyin veya farklı ad seçin.')
    if not settings.dry_run:
        remote=graph('GET',settings.meta_waba_id+'/message_templates',params={'name':data.name,'fields':'name,status','limit':100})
        if any(t.get('name')==data.name for t in remote.get('data',[])):raise HTTPException(409,'Bu şablon Meta’da mevcut; şablonları yenileyin.')
    components=[{'type':'HEADER','format':asset.kind.upper()},{'type':'BODY','text':data.body.strip()}]
    if data.footer.strip():components.append({'type':'FOOTER','text':data.footer.strip()})
    key='media_review:'+hashlib.sha256((settings.meta_waba_id+':'+data.name).encode()).hexdigest()
    t=Template(name=data.name,language='tr',category=data.category,body=data.body.strip(),components=json.dumps(components),status='LOCAL_DRAFT' if settings.dry_run else 'SUBMITTING')
    db.add(t);db.add(SystemValue(key=key,value=json.dumps({'phase':'simulation' if settings.dry_run else 'uploading'})))
    try:db.commit()
    except IntegrityError:db.rollback();raise HTTPException(409,'Başvuru zaten başlatıldı; durumunu yenileyin.')
    if settings.dry_run:return {'id':t.id,'name':t.name,'status':t.status,'notice':'Simülasyon taslağı kaydedildi. Meta’ya başvuru veya alıcılara mesaj gönderilmedi.'}
    phase='uploading'
    try:
        handle=upload_template_sample(MediaUpload(asset.filename,asset.content_type,asset.content),asset.kind.upper())
        payload=[{**components[0],'example':{'header_handle':[handle]}},*components[1:]]
        phase='submitting';db.get(SystemValue,key).value=json.dumps({'phase':phase});db.commit()
        result=graph('POST',settings.meta_waba_id+'/message_templates',{'name':data.name,'language':'tr','category':data.category,'components':payload})
        mid=result.get('id')
        if not isinstance(mid,str) or not mid.isdigit():raise ValueError()
        t.meta_id=mid;t.status=result.get('status') if result.get('status') in ('APPROVED','PENDING','REJECTED') else 'PENDING'
        t.category=result.get('category') if result.get('category') in ('UTILITY','MARKETING') else data.category
        db.get(SystemValue,key).value=json.dumps({'phase':'submitted'})
        audit(db,user.username,'media_template_review',data.name);db.commit()
        return {'id':t.id,'name':t.name,'status':t.status,'notice':'Meta incelemesine gönderildi. Onayı Meta verir; alıcılara mesaj gönderilmedi.'}
    except Exception:
        db.rollback();t=db.get(Template,t.id);t.status='UPLOAD_FAILED' if phase=='uploading' else 'SUBMISSION_UNKNOWN'
        db.get(SystemValue,key).value=json.dumps({'phase':t.status});db.commit()
        raise HTTPException(502,'Başvuru tamamlanamadı. Durumu Meta’dan yenileyin; çift başvuru riskine karşı otomatik tekrar yapılmadı.') from None
