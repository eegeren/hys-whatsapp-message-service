import json
import pytest
import httpx
from sqlalchemy import select
from fastapi import HTTPException
from app.core import Session,Message,Campaign,settings,now
from app.worker import process_one,reserve_bulk_slot,defer_bulk_slot,dispatch_local
from tests.test_bulk_friendly import prepare,fake_live

@pytest.mark.parametrize('code',[131026,131049,130472,131048])
def test_terminal_errors_never_retry_even_if_flagged_retryable(client,monkeypatch,code):
    cid,_,_=prepare(client);fake_live(monkeypatch)
    client.post(f'/api/bulk/campaign/{cid}/start',json={'confirmed':True})
    with Session() as db:mid=db.scalar(select(Message.id))
    calls=[]
    def reject(*a,**k):
        calls.append(1);raise HTTPException(502,{'code':code,'retryable':True,'ambiguous':False})
    monkeypatch.setattr('app.worker.graph',reject)
    process_one(mid);process_one(mid)
    with Session() as db:
        assert db.get(Message,mid).status=='failed'
        if code==131048:assert db.get(Campaign,cid).status=='paused'
    assert len(calls)==1

def test_global_backoff_blocks_other_recipients_and_expires(client,monkeypatch):
    monkeypatch.setattr('app.worker.time.time',lambda:100.)
    with Session() as db:
        assert reserve_bulk_slot(db)
        defer_bulk_slot(db,120);db.commit()
        monkeypatch.setattr('app.worker.time.time',lambda:180.)
        assert not reserve_bulk_slot(db)
        monkeypatch.setattr('app.worker.time.time',lambda:222.)
        assert reserve_bulk_slot(db)

def test_rate_retry_respects_retry_after_and_attempt_cap(client,monkeypatch):
    cid,_,_=prepare(client);fake_live(monkeypatch)
    client.post(f'/api/bulk/campaign/{cid}/start',json={'confirmed':True})
    with Session() as db:mid=db.scalar(select(Message.id))
    def reject(*a,**k):raise HTTPException(502,{'code':131056,'retryable':True,'ambiguous':False,'retry_after':600})
    monkeypatch.setattr('app.worker.graph',reject)
    before=now();process_one(mid)
    with Session() as db:
        m=db.get(Message,mid);assert m.status=='retry';assert (m.next_attempt-before).total_seconds()>=600
        m.attempts=4;m.next_attempt=now();db.commit()
    process_one(mid);process_one(mid)
    with Session() as db:assert db.get(Message,mid).status=='failed';assert db.get(Message,mid).attempts==5

def test_paused_backlog_does_not_starve_active_campaign(client,monkeypatch):
    cid,_,tid=prepare(client)
    with Session() as db:
        db.get(Campaign,cid).status='paused'
        db.add_all([Message(campaign_id=cid,phone='+905321234567',body='Pending') for _ in range(101)])
        active=Campaign(kind='customer',name='Active',status='running',template_id=tid);db.add(active);db.flush()
        m=Message(campaign_id=active.id,phone='+905331234567',body='Active');db.add(m);db.commit();mid=m.id
    seen=[];monkeypatch.setattr('app.worker.process_one',lambda id:seen.append(id))
    dispatch_local();assert seen==[mid]
    with Session() as db:assert db.get(Campaign,cid).status=='paused'

@pytest.mark.parametrize('code,status,expected',[(131056,400,True),(130429,400,True),(131026,429,False),(131049,400,False),(130472,400,False),(131048,400,False)])
def test_graph_error_classification_without_network(monkeypatch,code,status,expected):
    from app.meta import graph
    class Client:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def request(self,*a,**k):return httpx.Response(status,json={'error':{'code':code}},headers={'Retry-After':'123'})
    monkeypatch.setattr('app.meta.httpx.Client',Client)
    with pytest.raises(HTTPException) as e:graph('POST','123456/messages',{})
    assert e.value.detail['retryable']==expected
    assert e.value.detail['retry_after']==123

@pytest.mark.parametrize('status',['accepted','sent','delivered','read','failed'])
def test_final_or_accepted_messages_are_never_resent(client,monkeypatch,status):
    cid,_,_=prepare(client);calls=fake_live(monkeypatch)
    client.post(f'/api/bulk/campaign/{cid}/start',json={'confirmed':True})
    with Session() as db:
        m=db.scalar(select(Message));mid=m.id;m.status=status;db.commit()
    process_one(mid);assert calls==[]
    p=client.get(f'/api/bulk/campaign/{cid}').json()
    assert p['recipients'][0]['status']==status

def test_late_sent_does_not_erase_failed_but_delivered_is_proof(client):
    from app.webhook_infra import delivery
    with Session() as db:
        m=Message(phone='+905321234567',body='Existing',status='accepted',meta_id='wamid.existing');db.add(m);db.flush()
        delivery(db,{'id':m.meta_id,'status':'failed','errors':[{'code':131026}]})
        delivery(db,{'id':m.meta_id,'status':'sent'})
        assert m.status=='failed';assert '131026' in m.error
        delivery(db,{'id':m.meta_id,'status':'delivered'})
        assert m.status=='delivered';assert m.error==''

def test_recipient_list_is_paged_and_explains_paused_queue(client):
    cid,_,_=prepare(client)
    with Session() as db:
        db.get(Campaign,cid).status='paused'
        db.add_all([Message(campaign_id=cid,phone='+905321234567',body='Pending') for _ in range(51)])
        db.add(Message(campaign_id=cid,phone='+905331234567',body='Delivered',status='delivered',error='Meta teslimat hatasi (kod 131026).'))
        db.commit()
    first=client.get(f'/api/bulk/campaign/{cid}').json()
    second=client.get(f'/api/bulk/campaign/{cid}?page=2').json()
    assert len(first['recipients'])==50;assert len(second['recipients'])==2
    assert first['waiting']==51;assert first['recipient_pages']==2
    assert 'duraklat' in first['queue_notice']
    assert second['recipients'][-1]['status']=='delivered';assert second['recipients'][-1]['error']==''
    assert client.get(f'/api/bulk/campaign/{cid}?page=0').status_code==422
