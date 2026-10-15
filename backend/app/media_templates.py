"""Administrator-confirmed, deduplicated document/video template applications."""
import hashlib,json,logging
from fastapi import Depends,HTTPException
from pydantic import BaseModel,Field
from sqlalchemy import select,update
from sqlalchemy.exc import IntegrityError
from app.core import *
from app.main import app,admin,db_session,require,connection_ok
from app.meta import graph,upload_template_sample,safe_meta_text
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
    existing=db.scalar(select(Template).where(Template.name==data.name))
    if existing and existing.status not in ('UPLOAD_FAILED','SUBMISSION_REJECTED'):raise HTTPException(409,'Bu adla şablon kaydı zaten var. Başvurular listesinden Meta durumunu kontrol edin; belirsiz başvuru tekrar gönderilmedi.')
    if not settings.dry_run:
        remote=graph('GET',settings.meta_waba_id+'/message_templates',params={'name':data.name,'fields':'name,status','limit':100})
        if any(t.get('name')==data.name for t in remote.get('data',[])):raise HTTPException(409,'Bu şablon Meta’da mevcut; şablonları yenileyin.')
    components=[{'type':'HEADER','format':asset.kind.upper()},{'type':'BODY','text':data.body.strip()}]
    if data.footer.strip():components.append({'type':'FOOTER','text':data.footer.strip()})
    key='media_review:'+hashlib.sha256((settings.meta_waba_id+':'+data.name).encode()).hexdigest()
    if existing:
        claim=db.get(SystemValue,key)
        if not claim:raise HTTPException(409,'Bu şablonun güvenli tekrar kaydı yok; Meta durumunu kontrol edin.')
        previous=claim.value
        if json.loads(previous).get('phase') not in ('UPLOAD_FAILED','SUBMISSION_REJECTED'):raise HTTPException(409,'Başvuru halen işleniyor veya sonucu belirsiz; tekrar gönderilmedi.')
        if db.execute(update(SystemValue).where(SystemValue.key==key,SystemValue.value==previous).values(value=json.dumps({'phase':'uploading'}))).rowcount!=1:db.rollback();raise HTTPException(409,'Başka bir istek başvuruyu işliyor.')
        t=existing;t.body=data.body.strip();t.category=data.category;t.components=json.dumps(components);t.status='LOCAL_DRAFT' if settings.dry_run else 'SUBMITTING'
    else:
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
    except Exception as exc:
        detail=exc.detail if isinstance(exc,HTTPException) else {}
        detail=detail if isinstance(detail,dict) else {'message':safe_meta_text(detail)}
        definite=detail.get('ambiguous') is False and isinstance(detail.get('code'),int)
        state='UPLOAD_FAILED' if phase=='uploading' else 'SUBMISSION_REJECTED' if definite else 'SUBMISSION_UNKNOWN'
        stage='Örnek dosyanın Meta’ya yüklenmesi' if phase=='uploading' else 'Şablonun Meta incelemesine iletilmesi'
        reason=safe_meta_text(detail.get('meta_message') or detail.get('message') or 'Meta yanıtı doğrulanamadı.')
        failure={'phase':phase,'stage':stage,'message':reason,'code':detail.get('code'),'subcode':detail.get('subcode'),'trace_id':safe_meta_text(detail.get('trace_id')),'safe_to_retry':phase=='uploading' or definite}
        db.rollback();t=db.get(Template,t.id);t.status=state
        db.get(SystemValue,key).value=json.dumps({**failure,'phase':state});db.commit()
        logging.getLogger('hys.templates').error('media_review_failed template_id=%s stage=%s exception=%s details=%s',t.id,phase,type(exc).__name__,json.dumps(failure,ensure_ascii=False))
        action='Sorunu düzeltip aynı adla, yeniden açık onay vererek deneyebilirsiniz.' if failure['safe_to_retry'] else 'Başvurular listesinden Meta durumunu kontrol edin; sonuç belirsiz olduğu için tekrar gönderilmedi.'
        raise HTTPException(502,{'message':f'{stage} başarısız. {reason} {action}',**{k:v for k,v in failure.items() if k!='message'},'template_id':t.id}) from None


@app.get('/api/templates/media-review/{id}')
def review_details(id:int,user=Depends(admin),db=Depends(db_session)):
    t=require(db,Template,id);key='media_review:'+hashlib.sha256((settings.meta_waba_id+':'+t.name).encode()).hexdigest();row=db.get(SystemValue,key)
    return {'id':t.id,'status':t.status,'review':json.loads(row.value) if row else {}}


@app.post('/api/templates/media-review/{id}/check')
def check_review(id:int,user=Depends(admin),db=Depends(db_session)):
    t=require(db,Template,id)
    if settings.dry_run:return {'status':t.status,'notice':'Simülasyon: Meta sorgulanmadı.'}
    result=graph('GET',settings.meta_waba_id+'/message_templates',params={'name':t.name,'fields':'id,name,status,language,category,components','limit':100})
    seen=set();found=None
    while True:
        found=next((item for item in result.get('data',[]) if item.get('name')==t.name and item.get('language')==t.language),None)
        if found or not result.get('paging',{}).get('next'):break
        cursor=result.get('paging',{}).get('cursors',{}).get('after')
        if not cursor or cursor in seen:raise HTTPException(502,'Meta sayfalaması doğrulanamadı; başvuru tekrar gönderilmedi.')
        seen.add(cursor);result=graph('GET',settings.meta_waba_id+'/message_templates',params={'name':t.name,'fields':'id,name,status,language,category,components','limit':100,'after':cursor})
    if not found:return {'status':t.status,'notice':'Şablon Meta sorgusunda henüz bulunamadı. Bu durum belirsiz bir başvurunun kesin başarısız olduğunu kanıtlamaz; otomatik tekrar yapılmadı.'}
    t.meta_id=str(found['id']);t.status=found['status'];t.category=found.get('category',t.category);t.components=json.dumps(found.get('components',json.loads(t.components)))
    key='media_review:'+hashlib.sha256((settings.meta_waba_id+':'+t.name).encode()).hexdigest();row=db.get(SystemValue,key)
    if row:row.value=json.dumps({'phase':'submitted','reconciled':True})
    db.commit();return {'status':t.status,'notice':'Meta’daki mevcut başvuru bulundu ve durumu güncellendi. Yeni başvuru gönderilmedi.'}
