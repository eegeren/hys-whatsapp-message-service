"""Private DB-backed video jobs. API/worker replicas never depend on shared disks."""
import hashlib,hmac,json,logging,re,secrets,time,uuid
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import Depends,HTTPException,Request
from fastapi.responses import Response
from pydantic import BaseModel,Field
from sqlalchemy import select,update,func
from app.core import *
from app.main import app,actor,admin,db_session,require
from app.video_processing import prepare_video,VideoError,VIDEO_EXTENSIONS,VIDEO_LIMIT,tools_health

log=logging.getLogger('hys.video.jobs');LOCAL_SECRET=secrets.token_hex(32)

def video_origin():
    origin=settings.staff_upload_origin.strip().rstrip('/')
    if settings.app_environment=='production':
        p=urlsplit(origin)
        if p.scheme!='https' or not p.hostname or not p.hostname.endswith('.up.railway.app') or p.path or p.username or p.password or p.port or p.query or p.fragment:raise HTTPException(503,'Video yükleme için STAFF_UPLOAD_ORIGIN backend Railway HTTPS adresi olmalıdır.')
    return origin

def owned(db,id,user):
    job=require(db,VideoJob,id)
    if job.owner_id!=user.id and user.role!='admin':raise HTTPException(403,'Bu videoya erişim yetkiniz yok.')
    return job

def ready_video(db,id,user):
    job=owned(db,id,user)
    if job.expires<=now() or job.status!='ready' or not job.output:raise HTTPException(409,'Video henüz hazır değil veya süresi dolmuş. Önizlemeden sonra tekrar deneyin.')
    if job.output_size>VIDEO_LIMIT:raise HTTPException(422,'Hazırlanan video boyut sınırını aşıyor.')
    return job

def preview_signature(id,expiry):return hmac.new((settings.panel_proxy_secret or LOCAL_SECRET).encode(),f'{id}:{expiry}'.encode(),hashlib.sha256).hexdigest()

def worker_health(db):
    live=[]
    for row in db.scalars(select(SystemValue).where(SystemValue.key.like('video_worker:%'))):
        try:
            value=json.loads(row.value)
            if now()-datetime.fromisoformat(value['seen'])<timedelta(seconds=20) and value.get('enabled'):live.append(value)
        except (ValueError,KeyError,TypeError):continue
    healthy=any(value.get('state')=='ready' for value in live)
    active=db.scalar(select(func.count(VideoJob.id)).where(VideoJob.status.in_(['probing','converting','validating']),VideoJob.expires>now()))
    return {'state':'disabled' if not settings.video_processing_enabled else 'healthy' if healthy else 'error' if live else 'missing','active_jobs':active,'workers':len(live)}


def job_info(job,db=None):
    expiry=int(time.time())+900
    diagnostics={}
    if db is not None:
        diagnostics={'worker':worker_health(db),'queue_position':db.scalar(select(func.count(VideoJob.id)).where(VideoJob.status=='queued',VideoJob.expires>now(),VideoJob.created<=job.created)) if job.status=='queued' else None}
    return {**diagnostics,'id':job.id,'filename':job.filename,'output_filename':Path(job.filename).stem+'.mp4','status':job.status,'progress':job.progress,'source_size':job.source_size,'output_size':job.output_size,'info':json.loads(job.info),'error_code':job.error_code,'error':job.error,'expires':job.expires.isoformat(),'preview_url':video_origin()+f'/api/video-preview/{job.id}/{expiry}/{preview_signature(job.id,expiry)}' if job.status=='ready' else None}

class VideoInput(BaseModel):
    filename:str=Field(min_length=1,max_length=200)
    size:int=Field(gt=0)

@app.get('/api/video/tools')
def tool_state(user=Depends(admin)):return {'tools':tools_health(),'source_limit_mb':settings.video_input_limit_mb,'output_limit_bytes':VIDEO_LIMIT,'processing_enabled':settings.video_processing_enabled}

@app.post('/api/video/jobs')
def create_job(data:VideoInput,user=Depends(actor),db=Depends(db_session)):
    if not settings.video_processing_enabled:raise HTTPException(503,'Video işleme hizmeti şu anda kapalı.')
    if Path(data.filename).suffix.lower() not in VIDEO_EXTENSIONS:raise HTTPException(422,'MP4, MOV, MKV, WebM, AVI veya desteklenen başka bir video dosyası seçin.')
    if data.size>settings.video_input_limit_mb*1024*1024:raise HTTPException(413,f'Kaynak video en fazla {settings.video_input_limit_mb} MB olabilir.')
    count=db.scalar(select(func.count(VideoJob.id)).where(VideoJob.owner_id==user.id,VideoJob.status.in_(['awaiting_upload','queued','probing','converting','validating']),VideoJob.expires>now()))
    if count>=5:raise HTTPException(429,'En fazla 5 video aynı anda bekleyebilir. İşlemlerin bitmesini bekleyin veya bekleyen videoları kaldırın.')
    token=secrets.token_urlsafe(32);job=VideoJob(id=str(uuid.uuid4()),owner_id=user.id,filename=re.sub(r'[^\w. -]','_',Path(data.filename.replace('\\','/')).name)[:200],ticket_hash=hashlib.sha256(token.encode()).hexdigest(),source_size=data.size,expires=now()+timedelta(hours=24))
    origin=video_origin();db.add(job);audit(db,user.username,'video_prepare',job.id);db.commit()
    return {**job_info(job,db),'upload_url':origin+f'/api/video-upload/{job.id}/{token}'}

@app.put('/api/video-upload/{id}/{token}')
async def upload_job(id:str,token:str,request:Request,db=Depends(db_session)):
    if settings.app_environment=='production' and request.headers.get('origin')!=settings.panel_origin:raise HTTPException(403,'Panel kaynağı doğrulanamadı.')
    job=require(db,VideoJob,id);user=db.get(User,job.owner_id)
    if not user or user.role not in ('admin','operator') or not secrets.compare_digest(job.ticket_hash,hashlib.sha256(token.encode()).hexdigest()) or job.status!='awaiting_upload' or now()-job.created>timedelta(minutes=10):raise HTTPException(403,'Video yükleme izni geçersiz veya süresi dolmuş.')
    if db.execute(update(VideoJob).where(VideoJob.id==id,VideoJob.status=='awaiting_upload').values(status='uploading')).rowcount!=1:db.rollback();raise HTTPException(409,'Yükleme zaten başlatıldı.')
    db.commit()
    try:
        import tempfile
        with tempfile.SpooledTemporaryFile(max_size=1024*1024,mode='w+b') as tmp:
            size=0
            async for chunk in request.stream():
                size+=len(chunk)
                if size>job.source_size:raise HTTPException(413,'Dosya belirtilen kaynak boyutunu aşıyor.')
                tmp.write(chunk)
            if size!=job.source_size:raise HTTPException(422,'Video eksik yüklendi. Dosyayı yeniden seçin.')
            tmp.seek(0);job.source=tmp.read()
        job.status='queued';job.progress=1;db.commit();return job_info(job,db)
    except Exception:
        job.status='failed';job.error_code='upload_failed';job.error='Video yüklenemedi. Dosyayı yeniden seçin.';job.source=None;db.commit();raise

@app.get('/api/video/jobs/{id}')
def status(id:str,user=Depends(actor),db=Depends(db_session)):return job_info(owned(db,id,user),db)

@app.delete('/api/video/jobs/{id}')
def discard(id:str,user=Depends(actor),db=Depends(db_session)):
    job=owned(db,id,user)
    if job.status in ('probing','converting','validating'):raise HTTPException(409,'Video işleniyor; tamamlandıktan sonra kaldırabilirsiniz.')
    job.status='expired';job.source=None;job.output=None;db.commit();return {'ok':True}

@app.get('/api/video-preview/{id}/{expiry}/{signature}')
def preview_video(id:str,expiry:int,signature:str,request:Request,db=Depends(db_session)):
    if expiry<int(time.time()) or expiry>int(time.time())+901 or not hmac.compare_digest(signature,preview_signature(id,expiry)):raise HTTPException(403,'Video önizleme bağlantısının süresi doldu. Panelden yenileyin.')
    job=require(db,VideoJob,id)
    if job.expires<=now() or job.status!='ready' or not job.output:raise HTTPException(410,'Önizleme videosunun süresi doldu.')
    raw=job.output;size=len(raw);start=0;end=size-1;code=200
    range_header=request.headers.get('range','')
    if range_header:
        match=re.fullmatch(r'bytes=(\d*)-(\d*)',range_header)
        if not match or not any(match.groups()):return Response(status_code=416,headers={'Content-Range':f'bytes */{size}'})
        if not match[1]:start=max(0,size-int(match[2]))
        else:start=int(match[1]);end=min(end,int(match[2]) if match[2] else end)
        if start>end or start>=size:return Response(status_code=416,headers={'Content-Range':f'bytes */{size}'})
        code=206
    headers={'Accept-Ranges':'bytes','Cache-Control':'private, no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff','Content-Length':str(end-start+1),'Content-Disposition':'inline; filename="video.mp4"'}
    if code==206:headers['Content-Range']=f'bytes {start}-{end}/{size}'
    return Response(raw[start:end+1],status_code=code,media_type='video/mp4',headers=headers)

def process_next_video(stop=None):
    with Session() as db:
        # A converter may safely be restarted: it never talks to Meta.
        cutoff=now()-timedelta(seconds=settings.video_timeout_seconds+120)
        for job in db.scalars(select(VideoJob).where(VideoJob.status.in_(['uploading','probing','converting','validating']),VideoJob.updated<cutoff)):
            job.status='failed';job.error_code='worker_interrupted';job.error='Video işleyicisi kesildi. Dosyayı yeniden yükleyin.';job.source=None;job.output=None
        for job in db.scalars(select(VideoJob).where(VideoJob.expires<=now(),VideoJob.status!='expired')):
            job.status='expired';job.source=None;job.output=None
        db.commit()
        id=db.scalar(select(VideoJob.id).where(VideoJob.status=='queued',VideoJob.expires>now()).order_by(VideoJob.created).limit(1))
        if not id:return False
        if db.execute(update(VideoJob).where(VideoJob.id==id,VideoJob.status=='queued').values(status='probing',progress=3,updated=now())).rowcount!=1:db.rollback();return False
        db.commit();job=db.get(VideoJob,id);source=job.source;filename=job.filename
    last=[-1,0.0]
    def update_progress(stage,pct):
        if pct==last[0] and time.monotonic()-last[1]<5:return
        if time.monotonic()-last[1]<.5 and pct<90:return
        with Session() as db:
            db.execute(update(VideoJob).where(VideoJob.id==id,VideoJob.expires>now()).values(status=stage,progress=pct,updated=now()));db.commit()
        last[:]=[pct,time.monotonic()]
    try:
        content,info=prepare_video(source,filename,update_progress,stop)
        with Session() as db:
            job=db.get(VideoJob,id)
            if job.expires>now():job.output=content;job.output_size=len(content);job.info=json.dumps(info);job.status='ready';job.progress=100
            else:job.status='expired'
            job.source=None;db.commit()
        log.info('video_ready job=%s input_bytes=%d output_bytes=%d converted=%s original_codec=%s original_audio=%s',id,len(source),len(content),info['converted'],info['original']['video_codec'],info['original']['audio_codec'])
    except Exception as exc:
        log.error('video_failed job=%s code=%s exception=%s',id,getattr(exc,'code','internal_error'),type(exc).__name__)
        with Session() as db:
            job=db.get(VideoJob,id);job.status='failed';job.error_code=exc.code if isinstance(exc,VideoError) else 'internal_error';job.error=exc.message if isinstance(exc,VideoError) else 'Video işlenirken sunucu hatası oluştu. İşlem kodunu yöneticiye iletin.';job.source=None;job.output=None;db.commit()
    return True
