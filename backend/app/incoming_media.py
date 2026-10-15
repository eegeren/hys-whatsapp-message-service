"""Authenticated incoming attachment retrieval; Meta credentials stay server-side."""
import json,re,tempfile,logging
from urllib.parse import urlsplit,quote
import httpx
from fastapi import Depends,HTTPException,Request
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from sqlalchemy import select
from app.core import Message,WebhookItem,settings,audit
from app.main import app,actor,db_session
from app.meta import graph

log=logging.getLogger(__name__)
MEDIA_KINDS={'audio','image','video','document','sticker'}
MIME_TYPES={'audio':{'audio/ogg','audio/mpeg','audio/mp4','audio/aac','audio/amr','audio/opus'},'image':{'image/jpeg','image/png'},'video':{'video/mp4','video/3gpp'},'sticker':{'image/webp'},'document':{'application/pdf','text/plain','application/msword','application/vnd.openxmlformats-officedocument.wordprocessingml.document','application/vnd.ms-excel','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','application/vnd.ms-powerpoint','application/vnd.openxmlformats-officedocument.presentationml.presentation'}}

def incoming_content(item):
    kind=item.get('type','unknown')
    if not isinstance(kind,str):return None
    data=item.get(kind,{})
    data=data if isinstance(data,dict) else {}
    if kind in MEDIA_KINDS:
        return {'kind':kind,'available':bool(re.fullmatch(r'\d+',str(data.get('id','')))),'filename':str(data.get('filename',''))[:200],'caption':str(data.get('caption',''))[:4096]}
    if kind=='location':return {'kind':kind,**{k:data[k] for k in ('latitude','longitude','name','address') if k in data}}
    if kind=='contacts':return {'kind':kind,'contacts':item.get('contacts',[])}
    if kind=='interactive':
        reply=data.get(data.get('type'),{})
        return {'kind':kind,'text':reply.get('title','') if isinstance(reply,dict) else ''}
    if kind=='reaction':return {'kind':kind,'text':data.get('emoji','')}
    return None

def event_for(db,message):
    return db.scalar(select(WebhookItem).where(WebhookItem.kind=='message',WebhookItem.meta_id==message.meta_id)) if message.meta_id else None

@app.get('/api/messages/{message_id}/media')
def incoming_attachment(message_id:int,request:Request,download:bool=False,user=Depends(actor),db=Depends(db_session)):
    message=db.get(Message,message_id)
    if not message or message.direction!='in':raise HTTPException(404,'Gelen dosya bulunamadı.')
    event=event_for(db,message)
    try:item=json.loads(event.payload) if event else {}
    except ValueError:item={}
    kind=item.get('type');data=item.get(kind,{}) if kind in MEDIA_KINDS else {}
    media_id=data.get('id','') if isinstance(data,dict) else ''
    if not isinstance(media_id,str) or not re.fullmatch(r'\d+',media_id):raise HTTPException(410,'Bu eski mesajın dosya bilgisi kaydedilmemiş. Gönderenden dosyayı yeniden göndermesini isteyin.')
    try:info=graph('GET',media_id,params={'phone_number_id':event.phone_number_id})
    except HTTPException as exc:
        log.warning('Incoming media lookup failed message=%s status=%s',message_id,exc.status_code)
        raise HTTPException(502,'Dosya Meta’dan alınamadı. Dosyanın süresi dolmuş olabilir; tekrar deneyin veya gönderenden yeniden göndermesini isteyin.')
    try:
        url=info.get('url','');parsed=urlsplit(url);host=parsed.hostname or ''
        valid=parsed.scheme=='https' and not parsed.username and not parsed.password and parsed.port in (None,443) and (host=='lookaside.fbsbx.com' or host.endswith('.whatsapp.net') or host.endswith('.fbcdn.net'))
    except (TypeError,ValueError):valid=False
    if not valid:raise HTTPException(502,'Meta dosya adresi doğrulanamadı.')
    spool=tempfile.SpooledTemporaryFile(max_size=1024*1024,mode='w+b');size=0
    try:
        with httpx.Client(timeout=60,follow_redirects=False,trust_env=False) as client:
            with client.stream('GET',url,headers={'Authorization':'Bearer '+settings.meta_access_token}) as response:
                if response.status_code!=200:raise HTTPException(502,'Dosya Meta’dan indirilemedi. Tekrar deneyin veya dosyanın yeniden gönderilmesini isteyin.')
                mime=str(info.get('mime_type') or data.get('mime_type') or response.headers.get('content-type','')).split(';')[0].lower()
                if mime not in MIME_TYPES.get(kind,set()):raise HTTPException(415,'Bu dosya türü güvenli önizleme için desteklenmiyor.')
                for chunk in response.iter_bytes(65536):
                    size+=len(chunk)
                    if size>100*1024*1024:raise HTTPException(413,'Gelen dosya 100 MB görüntüleme sınırını aşıyor.')
                    spool.write(chunk)
        if not size:raise HTTPException(502,'Meta boş dosya döndürdü.')
    except Exception as exc:
        spool.close()
        if isinstance(exc,HTTPException):raise
        log.warning('Incoming media download failed message=%s error=%s',message_id,type(exc).__name__)
        raise HTTPException(502,'Dosya indirilirken bağlantı kesildi. Tekrar deneyin.')
    start,end,status=0,size-1,200
    headers={'Cache-Control':'private, no-store','X-Content-Type-Options':'nosniff','Accept-Ranges':'bytes'}
    requested=request.headers.get('range')
    if requested:
        match=re.fullmatch(r'bytes=(\d*)-(\d*)',requested)
        if not match or not any(match.groups()):spool.close();raise HTTPException(416,'Geçersiz dosya aralığı.',headers={'Content-Range':f'bytes */{size}'})
        left,right=match.groups()
        if left:start=int(left);end=min(int(right),size-1) if right else size-1
        else:start=max(0,size-int(right))
        if start>end or start>=size:spool.close();raise HTTPException(416,'Geçersiz dosya aralığı.',headers={'Content-Range':f'bytes */{size}'})
        status=206;headers['Content-Range']=f'bytes {start}-{end}/{size}'
    filename=str(data.get('filename') or f'{kind}-{message_id}').replace('\\','/').rsplit('/',1)[-1][:200]
    headers['Content-Disposition']=('attachment' if download else 'inline')+"; filename*=UTF-8''"+quote(filename,safe='')
    headers['Content-Length']=str(end-start+1)
    audit(db,user.username,'incoming_media_access',str(message_id));db.commit()
    def chunks():
        try:
            spool.seek(start);remaining=end-start+1
            while remaining:
                chunk=spool.read(min(65536,remaining))
                if not chunk:break
                remaining-=len(chunk);yield chunk
        finally:spool.close()
    return StreamingResponse(chunks(),status_code=status,media_type=mime,headers=headers,background=BackgroundTask(spool.close))
