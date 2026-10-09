import json, re, time, random
from datetime import timedelta
from sqlalchemy import select,update
from sqlalchemy.exc import IntegrityError
from celery import Celery
from redis import Redis
from fastapi import HTTPException
from app.core import *
from app.meta import graph,NO_RETRY_CODES

celery=Celery('hys',broker=settings.redis_url,backend=settings.redis_url)
celery.conf.update(task_acks_late=True,worker_prefetch_multiplier=1,timezone='UTC',beat_schedule={'dispatch':{'task':'hys.dispatch','schedule':5.0}},broker_transport_options={'visibility_timeout':3600})
def reserve_bulk_slot(db):
    """One global request/second, bounded daily; CAS works with SQLite and PostgreSQL."""
    key='bulk_rate:'+now().date().isoformat();row=db.get(SystemValue,key)
    if not row:
        db.add(SystemValue(key=key,value=json.dumps({'last':0,'count':0})))
        try:db.commit()
        except IntegrityError:db.rollback()
        row=db.get(SystemValue,key)
    old=row.value;state=json.loads(old);stamp=time.time()
    if stamp-state['last']<1 or state['count']>=settings.bulk_daily_limit:return False
    value=json.dumps({'last':stamp,'count':state['count']+1})
    claimed=db.execute(update(SystemValue).where(SystemValue.key==key,SystemValue.value==old).values(value=value)).rowcount
    db.commit();return claimed==1

def defer_bulk_slot(db,seconds):
    """Persist sender-wide backoff so other workers cannot continue a rate-limit burst."""
    key='bulk_rate:'+now().date().isoformat()
    row=db.get(SystemValue,key)
    if not row:return
    for _ in range(3):
        db.refresh(row);old=row.value;state=json.loads(old)
        state['last']=max(state['last'],time.time()+seconds)
        if db.execute(update(SystemValue).where(SystemValue.key==key,SystemValue.value==old).values(value=json.dumps(state))).rowcount:return

def process_one(id):
    if not settings.bulk_dispatch_enabled or settings.deployment_send_lock:return
    with Session() as db:
        m=db.scalar(select(Message).where(Message.id==id).with_for_update(skip_locked=True))
        if not m or m.status not in ('queued','retry') or m.next_attempt>now():return
        c=db.scalar(select(Campaign).where(Campaign.id==m.campaign_id).with_for_update())
        if not c or c.status not in ('running','scheduled'):return
        if c.scheduled and c.scheduled>now():return
        contact=db.scalar(select(Contact).where(Contact.id==m.contact_id).with_for_update())
        from app.bulk import bulk_eligible
        if not contact or not bulk_eligible(db,contact):m.status='blocked';m.error='Gönderim anında izin/ret kontrolü başarısız';db.commit();return
        t=db.get(Template,c.template_id)
        cfgrow=db.get(SystemValue,f'bulk_config:{c.id}');cfg=json.loads(cfgrow.value) if cfgrow else None
        if cfg and cfg.get('execution_dry_run') and not settings.dry_run:
            m.status='blocked';m.error='Simülasyon kuyruğu otomatik canlı gönderime dönüştürülemez';db.commit();return
        if settings.dry_run:
            m.status='dry_run';m.error='Simülasyon: Meta API çağrılmadı';db.commit();return
        from app.main import connection_ok
        approval=c.first_approval and (c.second_approval or cfg and cfg.get('single_approval'))
        if cfg and settings.live_send_enabled and approval and not connection_ok(db):
            try:
                from app.bulk import check_live_template
                check_live_template(t,cfg,db)
            except HTTPException:
                c.status='paused';audit(db,'worker','bulk_connection_pause',str(c.id));db.commit();return
        if not(settings.live_send_enabled and connection_ok(db) and approval and not c.budget):
            m.status='blocked';m.error='Canlı gönderim güvenlik kilidi';db.commit();return
        if t.status!='APPROVED' or (c.kind=='customer' and t.category!='MARKETING'):
            m.status='blocked';m.error='Şablon uygun/onaylı değil';db.commit();return
        if cfg:
            if cfg.get('media_file'):
                m.status='blocked';m.error='Medya henüz Meta’ya yüklenmedi; kampanya onayını kullanın';db.commit();return
            from app.bulk import definition_matches
            if not definition_matches(t,cfg):
                m.status='blocked';m.error='Şablon içeriği değişti; yeniden hazırlama gerekli';db.commit();return
            if cfg['phone_number_id']!=settings.meta_phone_number_id or cfg['waba_id']!=settings.meta_waba_id:
                m.status='blocked';m.error='Production numarası/WABA değişti';db.commit();return
            payload={'messaging_product':'whatsapp','to':contact.phone.lstrip('+'),'type':'template','template':cfg['template']}
        else:
            payload=legacy_payload(t,c,contact,m,db)
            if payload is None:return
        if not reserve_bulk_slot(db):return
        claimed=db.execute(update(Message).where(Message.id==id,Message.status.in_(['queued','retry'])).values(status='sending',attempts=Message.attempts+1,next_attempt=now())).rowcount
        db.commit()
        if claimed!=1:return
        db.refresh(m)
        c=db.scalar(select(Campaign).where(Campaign.id==m.campaign_id).with_for_update())
        db.refresh(contact)
        if c:db.refresh(c)
        if not c or c.status not in ('running','scheduled'):
            # No network call has happened yet; a pause preserves this pending item.
            m.status='queued' if c and c.status=='paused' else 'cancelled';m.attempts-=1;db.commit();return
        if not bulk_eligible(db,contact):
            m.status='blocked';m.error='Son izin veya kampanya kontrolü başarısız';db.commit();return
        try:
            result=graph('POST',f'{settings.meta_phone_number_id}/messages',payload)
            meta_id=result.get('messages',[{}])[0].get('id')
            if not isinstance(meta_id,str) or not meta_id.startswith('wamid.') or len(meta_id)>200 or any(secret and secret in meta_id for secret in (settings.meta_access_token,settings.meta_app_secret,settings.meta_verify_token)):raise ValueError('Invalid message ID')
            m.meta_id=meta_id;m.status='accepted';m.error=''
            db.flush()
            # Reconcile a webhook which arrived before the send response was stored.
            from app.webhook_infra import delivery
            for event in db.scalars(select(WebhookItem).where(WebhookItem.meta_id==meta_id,WebhookItem.kind=='status').order_by(WebhookItem.created)):
                delivery(db,json.loads(event.payload))
        except HTTPException as e:
            detail=e.detail
            if isinstance(detail,dict) and detail.get('code')==131048:
                c.status='paused';audit(db,'worker','bulk_quality_pause',str(c.id))
            if isinstance(detail,dict) and detail.get('code') not in NO_RETRY_CODES and detail.get('retryable') and not detail.get('ambiguous') and m.attempts<5:
                delay=max(min(900,30*2**m.attempts)+random.uniform(0,10),min(86400,max(0,float(detail.get('retry_after',0) or 0))))
                m.status='retry';m.next_attempt=now()+timedelta(seconds=delay)
                defer_bulk_slot(db,delay)
            else:m.status='uncertain' if not isinstance(detail,dict) or detail.get('ambiguous') else 'failed'
            m.error=json.dumps(detail,ensure_ascii=False)
            for secret in (settings.meta_access_token,settings.meta_app_secret,settings.meta_verify_token):
                if secret:m.error=m.error.replace(secret,'[gizli]')
        except Exception:m.status='uncertain';m.error='Sonuç doğrulanamadı; otomatik tekrar yok'
        db.commit()

def legacy_payload(t,c,contact,m,db):
        # Preserve the existing campaign path and its two-admin approval policy.
        # are never silently sent with incomplete components.
        components=json.loads(t.components)
        if any(x.get('type') in ('HEADER','BUTTONS') for x in components):
            m.status='blocked';m.error='Görsel/buton şablonları bu sürümde canlı gönderime kapalı';db.commit();return
        vars=json.loads(c.variables)
        values={'personel_adi':contact.first_name,'musteri_adi':contact.first_name,'magaza_adi':contact.store,**vars}
        keys=re.findall(r'{{\s*([^} ]+)\s*}}',t.body)
        if any(not k.isdigit() for k in keys):
            m.status='blocked';m.error='Canlı gönderimde yalnızca numaralı Meta parametreleri desteklenir';db.commit();return
        if any(k not in values for k in keys):m.status='blocked';m.error='Eksik şablon değişkeni';db.commit();return
        parameters=[{'type':'text','text':str(values[k])} for k in sorted(set(keys),key=lambda x:(0,int(x)) if x.isdigit() else (1,x))]
        payload={'messaging_product':'whatsapp','to':contact.phone.lstrip('+'),'type':'template','template':{'name':t.name,'language':{'code':t.language}}}
        if parameters:payload['template']['components']=[{'type':'body','parameters':parameters}]
        return payload
def dispatch_local(limit=100):
    if not settings.bulk_dispatch_enabled or settings.deployment_send_lock:return
    with Session() as db:
        ids=list(db.scalars(select(Message.id).join(Campaign,Message.campaign_id==Campaign.id).where(Message.status.in_(['queued','retry']),Message.next_attempt<=now(),Campaign.status.in_(['running','scheduled']),(Campaign.scheduled.is_(None))|(Campaign.scheduled<=now())).order_by(Message.id).limit(limit)))
    for id in ids:process_one(id)
    finalize()
def finalize():
    with Session() as db:
        for item in db.scalars(select(SystemValue).where(SystemValue.key.like('import:%'))):
            if json.loads(item.value).get('expires','')<now().isoformat():db.delete(item)
        for m in db.scalars(select(Message).where(Message.status=='sending',Message.next_attempt<now()-timedelta(minutes=10))):
            m.status='uncertain';m.error='İşleyici kesintisi veya yanıt zaman aşımı; manuel kontrol gerekli, tekrar gönderilmez'
        for c in db.scalars(select(Campaign).where(Campaign.status.in_(['running','scheduled']))):
            pending=db.scalar(select(Message.id).where(Message.campaign_id==c.id,Message.status.in_(['queued','retry','sending'])).limit(1))
            if not pending:c.status='completed'
        db.commit()
@celery.task(name='hys.send',rate_limit='1/s')
def send(id):
    try:process_one(id)
    finally:Redis.from_url(settings.redis_url).delete(f'hys:dispatch:{id}')
@celery.task(name='hys.dispatch')
def dispatch():
    if not settings.bulk_dispatch_enabled or settings.deployment_send_lock:return
    with Session() as db:
        ids=list(db.scalars(select(Message.id).join(Campaign,Message.campaign_id==Campaign.id).where(Message.status.in_(['queued','retry']),Message.next_attempt<=now(),Campaign.status.in_(['running','scheduled']),(Campaign.scheduled.is_(None))|(Campaign.scheduled<=now())).order_by(Message.id).limit(100)))
    cache=Redis.from_url(settings.redis_url)
    for id in ids:
        if cache.set(f'hys:dispatch:{id}','1',nx=True,ex=600):
            try:send.delay(id)
            except Exception:cache.delete(f'hys:dispatch:{id}');raise
    finalize()
if __name__=='__main__':
    while True:
        try:dispatch_local()
        except Exception:print('HYS kuyruk kontrolü tamamlanamadı; ayrıntılar gizli tutuldu.',flush=True)
        time.sleep(1)
