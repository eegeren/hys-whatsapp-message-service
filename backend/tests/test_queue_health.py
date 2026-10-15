import json
from datetime import timedelta
import pytest
from app.core import settings,Session,Campaign,Message,Template,SystemValue,now
from app.queue_health import worker_health,worker_snapshot

@pytest.mark.parametrize('mode',['ready','missing','stale','mismatch','error','redis_failure','legacy'])
def test_worker_health_is_read_only_and_secret_free(monkeypatch,mode):
    monkeypatch.setattr(settings,'app_environment','production')
    payload=json.loads(worker_snapshot('error' if mode=='error' else 'ready'))
    payload['arbitrary_secret']=settings.meta_access_token
    if mode=='mismatch':payload['fingerprint']='incorrect'
    class Cache:
        closed=False
        def mget(self,keys):
            assert keys==['hys:production-worker:heartbeat','hys:production-worker:state']
            if mode=='redis_failure':raise RuntimeError('fake-private-password')
            stamp=(now()-timedelta(minutes=3) if mode=='stale' else now()).isoformat()
            return [None if mode=='missing' else stamp,None if mode=='legacy' else json.dumps(payload)]
        def close(self):self.closed=True
    cache=Cache()
    monkeypatch.setattr('app.queue_health.Redis.from_url',lambda *a,**k:cache)
    result=worker_health()
    expected={'stale':'missing','mismatch':'ready','redis_failure':'unavailable'}.get(mode,mode)
    assert result['state']==expected
    if mode=='mismatch':assert result['configuration_matches'] is False
    text=json.dumps(result)
    assert settings.meta_access_token not in text and 'fingerprint' not in text and 'fake-private-password' not in text
    assert cache.closed

@pytest.mark.parametrize('cause,needle',[
    ('missing','Aktif worker sinyali yok'),('worker_disabled','Worker kuyruğu kapalı'),
    ('worker_locked','Worker gönderim kilidi'),('mismatch','yapılandırması eşleşmiyor'),
    ('error','işleme hatası'),('unavailable','Redis üzerinden'),
    ('backend_disabled','Toplu kuyruk kapalı'),('daily','Günlük gönderim sınırı'),
    ('paused','Kampanya duraklatılmış'),('future','Planlanan gönderim zamanı'),
])
def test_campaign_explains_waiting_without_starting_or_sending(client,monkeypatch,cause,needle):
    monkeypatch.setattr(settings,'bulk_dispatch_enabled',cause!='backend_disabled')
    monkeypatch.setattr(settings,'deployment_send_lock',False)
    state={'state':cause if cause in ('missing','error','unavailable') else 'ready','configuration_matches':cause!='mismatch','dispatch_enabled':cause!='worker_disabled','send_locked':cause=='worker_locked'}
    monkeypatch.setattr('app.bulk.worker_health',lambda:state)
    monkeypatch.setattr('app.bulk.graph',lambda *a,**k:pytest.fail('Diagnostic must never reach Meta'))
    with Session() as db:
        t=Template(name='synthetic_diagnostic',body='Test',status='APPROVED',category='MARKETING')
        db.add(t);db.flush()
        c=Campaign(name='Synthetic diagnostic',kind='customer',template_id=t.id,status='paused' if cause=='paused' else 'running',scheduled=now()+timedelta(days=1) if cause=='future' else None)
        db.add(c);db.flush();cid=c.id
        m=Message(campaign_id=cid,phone='+905321234567',body='Synthetic queued message',status='queued')
        db.add(m);db.flush();mid=m.id
        if cause=='daily':db.add(SystemValue(key='bulk_rate:'+now().date().isoformat(),value=json.dumps({'count':settings.bulk_daily_limit})))
        db.commit()
    response=client.get(f'/api/bulk/campaign/{cid}')
    assert response.status_code==200 and needle in response.json()['queue_notice']
    assert response.json()['waiting']==1
    with Session() as db:
        row=db.get(Message,mid)
        assert row.status=='queued' and row.attempts==0 and not row.meta_id
        assert db.get(Campaign,cid).status==('paused' if cause=='paused' else 'running')
