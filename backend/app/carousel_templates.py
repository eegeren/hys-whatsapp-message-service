"""Admin-confirmed carousel template review submission. Never sends messages."""
import hashlib,json
from fastapi import Depends,File,Form,HTTPException,UploadFile
from pydantic import BaseModel,Field,ValidationError
from sqlalchemy import select,update
from sqlalchemy.exc import IntegrityError
from app.core import settings,Template,SystemValue,audit
from app.main import app,admin,db_session
from app.meta import graph,upload_template_sample
from app.template_components import MediaUpload,validate_upload,text_parameters,variable_keys

class ReviewCard(BaseModel):
    text:str=Field(min_length=1,max_length=160)
    examples:dict[str,str]=Field(default_factory=dict,max_length=20)

class CarouselReview(BaseModel):
    name:str=Field(pattern=r'^[a-z0-9_]{1,150}$')
    body:str=Field(min_length=1,max_length=1024)
    examples:dict[str,str]=Field(default_factory=dict,max_length=20)
    cards:list[ReviewCard]=Field(min_length=2,max_length=10)
    button_text:str=Field(default='Gördüm',min_length=1,max_length=25)
    confirmed:bool=False

def review_body(text,examples):
    if not text.strip():raise HTTPException(422,'Şablon metni boş olamaz.')
    keys=variable_keys(text)
    if any(not k.isdigit() for k in keys):raise HTTPException(422,'Başvuru değişkenlerini {{1}}, {{2}} şeklinde numaralandırın.')
    params,_=text_parameters(text,examples)
    result={'type':'BODY','text':text}
    if params:result['example']={'body_text':[[p['text'] for p in params]]}
    return result

@app.post('/api/templates/carousel-review')
def carousel_review(data:str=Form(...,max_length=50000),files:list[UploadFile]=File(...),user=Depends(admin),db=Depends(db_session)):
    try:
        try:proposal=CarouselReview.model_validate_json(data)
        except ValidationError:raise HTTPException(422,'Şablon adı, metin ve 2–10 görsel kartını kontrol edin.')
        if not proposal.confirmed:raise HTTPException(422,'Şablon ve örnek görsellerin Meta onayına gönderilmesini açıkça onaylayın.')
        if settings.meta_environment!='production' or (settings.meta_test_phone_number_id and settings.meta_phone_number_id==settings.meta_test_phone_number_id):raise HTTPException(403,'Carousel başvurusu için gerçek production numarası ve WABA yapılandırması gereklidir; test hesabına başvuru yapılmadı.')
        if len(files)!=len(proposal.cards):raise HTTPException(422,'Her kart için bir örnek görsel seçin.')
        if not proposal.button_text.strip():raise HTTPException(422,'Buton metni boş olamaz.')
        body=review_body(proposal.body,proposal.examples)
        cards=[{'components':[{'type':'HEADER','format':'IMAGE'},review_body(c.text,c.examples),
                             {'type':'BUTTONS','buttons':[{'type':'QUICK_REPLY','text':proposal.button_text}]}]} for c in proposal.cards]
        assets=[]
        for file in files:
            asset=MediaUpload((file.filename or 'gorsel').replace('\\','/').rsplit('/',1)[-1][:200],file.content_type or '',file.file.read(5*1024*1024+1))
            validate_upload('IMAGE',asset);assets.append(asset)
        # Read-only checks must precede any sample upload or template mutation.
        numbers=graph('GET',settings.meta_waba_id+'/phone_numbers',params={'fields':'id','limit':100})
        ids={str(n.get('id')) for n in numbers.get('data',[])};seen=set()
        while settings.meta_phone_number_id not in ids and numbers.get('paging',{}).get('next'):
            cursor=numbers.get('paging',{}).get('cursors',{}).get('after')
            if not cursor or cursor in seen or len(seen)>=100:break
            seen.add(cursor);numbers=graph('GET',settings.meta_waba_id+'/phone_numbers',params={'fields':'id','limit':100,'after':cursor})
            ids.update(str(n.get('id')) for n in numbers.get('data',[]))
        if settings.meta_phone_number_id not in ids:raise HTTPException(403,'Numara bu WABA’ya bağlı olarak doğrulanamadı; şablon başvurusu yapılmadı.')
        remote=graph('GET',settings.meta_waba_id+'/message_templates',params={'name':proposal.name,'fields':'id,name,status,language','limit':100})
        if any(t.get('name')==proposal.name for t in remote.get('data',[])):raise HTTPException(409,'Bu şablon adı Meta’da mevcut. Şablonları yenileyin; ikinci başvuru yapılmadı.')
        # A unique DB claim survives double clicks, restarts, and ambiguous API timeouts.
        key='carousel_review:'+hashlib.sha256((settings.meta_waba_id+':'+proposal.name).encode()).hexdigest()
        cfg=db.get(SystemValue,key)
        t=db.scalar(select(Template).where(Template.name==proposal.name))
        if cfg:
            if not t:raise HTTPException(409,'Başvuru kaydı mevcut; önce şablon durumunu kontrol edin.')
            old=cfg.value;state=json.loads(old)
            if state.get('phase')!='upload_failed':raise HTTPException(409,'Bu başvuru zaten işlenmiş veya sonucu belirsiz. Önce Meta şablonlarını yenileyin; otomatik tekrar yapılmadı.')
            if db.execute(update(SystemValue).where(SystemValue.key==key,SystemValue.value==old).values(value=json.dumps({'phase':'uploading'}))).rowcount!=1:
                db.rollback();raise HTTPException(409,'Başka bir istek başvuruyu işliyor.')
        else:
            if t:raise HTTPException(409,'Şablon adı panelde mevcut; başka bir ad seçin.')
            db.add(SystemValue(key=key,value=json.dumps({'phase':'uploading'})))
            t=Template(name=proposal.name,body=proposal.body,category='MARKETING',language='tr',status='LOCAL_DRAFT')
            db.add(t)
        try:db.commit()
        except IntegrityError:db.rollback();raise HTTPException(409,'Başvuru başka bir istek tarafından başlatıldı.')
        cfg=db.get(SystemValue,key);phase='uploading'
        try:
            t.body=proposal.body
            for card,asset in zip(cards,assets):
                card['components'][0]['example']={'header_handle':[upload_template_sample(asset)]}
            components=[body,{'type':'CAROUSEL','cards':cards}]
            phase='submitting';cfg.value=json.dumps({'phase':phase});t.status='SUBMITTING';db.commit()
            result=graph('POST',settings.meta_waba_id+'/message_templates',{'name':proposal.name,'language':'tr','category':'MARKETING','components':components})
            meta_id=result.get('id')
            if not isinstance(meta_id,str) or not meta_id.isdigit():raise HTTPException(502,'Meta başvuru kimliği doğrulanamadı. Şablonları yenileyin; başvuru tekrarlanmadı.')
            # Sample handles stay server-side and are excluded from the saved public definition.
            def strip(value):
                if isinstance(value,dict):return {k:strip(v) for k,v in value.items() if k!='example'}
                if isinstance(value,list):return [strip(v) for v in value]
                return value
            t.components=json.dumps(strip(components));t.meta_id=meta_id
            t.status=result.get('status') if result.get('status') in ('PENDING','APPROVED','REJECTED') else 'PENDING'
            cfg.value=json.dumps({'phase':'submitted','template_id':t.id})
            audit(db,user.username,'carousel_template_review',json.dumps({'name':t.name,'cards':len(cards),'status':t.status}));db.commit()
            return {'id':t.id,'name':t.name,'status':t.status,'notice':'Şablon başvurusu Meta’ya iletildi. APPROVED olmadan mesaj gönderilemez. Hiçbir alıcıya mesaj gönderilmedi.'}
        except Exception as exc:
            db.rollback();cfg=db.get(SystemValue,key);t=db.scalar(select(Template).where(Template.name==proposal.name))
            cfg.value=json.dumps({'phase':'upload_failed' if phase=='uploading' else 'unknown'})
            t.status='LOCAL_DRAFT' if phase=='uploading' else 'SUBMISSION_UNKNOWN';db.commit()
            if isinstance(exc,HTTPException):raise
            raise HTTPException(502,'Şablon başvurusu tamamlanamadı; ayrıntılar gizlendi. Önce Meta şablonlarını yenileyin; otomatik tekrar yapılmadı.') from None
    finally:
        for file in files:file.file.close()
