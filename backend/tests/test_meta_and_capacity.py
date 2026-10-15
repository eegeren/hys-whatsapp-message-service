import json,hashlib,io
from datetime import timedelta
from sqlalchemy import select
from fastapi import HTTPException
from app.core import *
from app.worker import process_one,finalize
from app.main import connection_ok
from tests.test_workflows import contact,consent,campaign,event,signed

def prepare_live(client):
    id=contact(client);consent(client,id);cid=campaign(client);client.post(f'/api/campaigns/{cid}/start')
    with Session() as db:
        c=db.get(Campaign,cid);c.first_approval=1;c.second_approval=2
        t=db.get(Template,c.template_id);t.body='Merhaba {{1}}';t.status='APPROVED';t.meta_id='meta.template';t.components='[]';c.variables=json.dumps({'1':'Test'})
        fingerprint=hashlib.sha256((settings.meta_access_token+settings.meta_phone_number_id+settings.meta_waba_id+settings.meta_environment).encode()).hexdigest()
        db.merge(SystemValue(key='meta_verified',value=json.dumps({'fingerprint':fingerprint,'checked_at':now().isoformat()})));db.commit();mid=db.scalar(select(Message.id))
    return mid,cid
def test_meta_acceptance_is_not_delivery(client,monkeypatch):
    mid,_=prepare_live(client);settings.dry_run=False;settings.live_send_enabled=True;seen=[]
    def fake(method,path,payload=None,params=None):seen.append(payload);return {'messages':[{'id':'wamid.accepted'}]}
    monkeypatch.setattr('app.worker.graph',fake)
    try:
        process_one(mid);process_one(mid)
        with Session() as db:
            m=db.get(Message,mid);assert m.status=='accepted';assert m.meta_id=='wamid.accepted'
        assert len(seen)==1;assert seen[0]['template']['components'][0]['parameters'][0]['text']=='Test'
    finally:settings.dry_run=True;settings.live_send_enabled=False
def test_rate_limit_retry_and_ambiguous_response(client,monkeypatch):
    # This test exercises retry classification; global pacing is covered separately.
    monkeypatch.setattr('app.worker.reserve_bulk_slot',lambda db:True)
    mid,_=prepare_live(client);settings.dry_run=False;settings.live_send_enabled=True
    def reject(*args,**kwargs):raise HTTPException(502,{'retryable':True,'ambiguous':False,'code':130429})
    monkeypatch.setattr('app.worker.graph',reject)
    try:
        process_one(mid)
        with Session() as db:
            m=db.get(Message,mid);assert m.status=='retry';assert m.next_attempt>now();m.next_attempt=now();db.commit()
        def uncertain(*args,**kwargs):raise HTTPException(502,'Timeout')
        monkeypatch.setattr('app.worker.graph',uncertain);process_one(mid);process_one(mid)
        with Session() as db:assert db.get(Message,mid).status=='uncertain';assert db.get(Message,mid).attempts==2
    finally:settings.dry_run=True;settings.live_send_enabled=False
def test_stale_connection_is_not_verified(client):
    prepare_live(client)
    with Session() as db:
        assert connection_ok(db)
        v=db.get(SystemValue,'meta_verified');d=json.loads(v.value);d['checked_at']=(now()-timedelta(hours=2)).isoformat();v.value=json.dumps(d);db.commit();assert not connection_ok(db)
def test_uncertain_and_preview_cleanup(client):
    with Session() as db:
        db.add(Message(phone='+905321234567',body='Test',status='sending',next_attempt=now()-timedelta(minutes=11)))
        db.add(SystemValue(key='import:expired',value=json.dumps({'expires':(now()-timedelta(hours=1)).isoformat()})));db.commit()
    finalize()
    with Session() as db:assert db.scalar(select(Message)).status=='uncertain';assert db.get(SystemValue,'import:expired') is None
def test_ten_thousand_csv_preview(client):
    content='ad,telefon,izin\n'+''.join(f'Test {i},+90532{i:07d},izinli\n' for i in range(10000))
    r=client.post('/api/import/customer/preview',files={'file':('10000.csv',content.encode(),'text/csv')})
    assert r.status_code==200,r.text;assert r.json()['valid_count']==10000;assert len(r.json()['preview'])==20
    r=client.post('/api/import/customer/commit',json={'token':r.json()['token']});assert r.status_code==200,r.text;assert r.json()['imported']==10000
    d=client.get('/api/contacts/customer?page=200').json();assert d['total']==10000;assert len(d['items'])==50
    assert client.get('/api/dashboard').json()['eligible']==0
def test_oversize_upload_blocked(client):
    r=client.post('/api/import/customer/preview',files={'file':('big.csv',b'x'*(5*1024*1024+1),'text/csv')});assert r.status_code==413
def test_review_and_unmatched_filters(client):
    payload=event([{'id':'in.ambiguous','from':'905329999999','type':'text','text':{'body':'Bana mesaj göndermeyin lütfen'}}]);signed(client,payload)
    assert client.get('/api/messages?direction=in&review=true&unmatched=true&unread=true').json()['total']==1
