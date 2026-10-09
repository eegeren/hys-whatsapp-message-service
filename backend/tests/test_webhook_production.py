import hashlib,hmac,json
import pytest
from sqlalchemy import select,func
from app.core import settings,Session,WebhookItem,Message,Event

def envelope(messages=None,statuses=None,number='123456',waba='654321'):
    return {'object':'whatsapp_business_account','entry':[{'id':waba,'changes':[{'field':'messages','value':{'metadata':{'phone_number_id':number},'messages':messages or [],'statuses':statuses or []}}]}]}
def post(client,data):
    raw=json.dumps(data).encode();sig='sha256='+hmac.new(settings.meta_app_secret.encode(),raw,hashlib.sha256).hexdigest()
    return client.post('/api/webhook',content=raw,headers={'X-Hub-Signature-256':sig})
def message(id='wamid.inbound'):
    return {'id':id,'from':'905321234567','timestamp':'1720000000','type':'text','text':{'body':'Merhaba'}}

def test_get_challenge_and_missing_or_wrong_verification(client):
    r=client.get('/api/webhook',params={'hub.mode':'subscribe','hub.verify_token':settings.meta_verify_token,'hub.challenge':'123456'})
    assert r.status_code==200 and r.text=='123456' and r.headers['content-type'].startswith('text/plain')
    for query in [{'hub.mode':'subscribe','hub.verify_token':'wrong','hub.challenge':'123'}, {'hub.mode':'subscribe','hub.verify_token':settings.meta_verify_token}]:
        assert client.get('/api/webhook',params=query).status_code==403

def test_invalid_signature_and_tampered_payload_never_persist(client):
    raw=json.dumps(envelope([message()])).encode()
    sig='sha256='+hmac.new(settings.meta_app_secret.encode(),raw,hashlib.sha256).hexdigest()
    assert client.post('/api/webhook',content=raw+b' ',headers={'X-Hub-Signature-256':sig}).status_code==403
    assert client.post('/api/webhook',content=raw,headers={'X-Hub-Signature-256':'sha256=zz'}).status_code==403
    with Session() as db:assert db.scalar(select(func.count(Event.id)))==0

def test_per_item_dedup_across_different_batches_keeps_other_items(client):
    assert post(client,envelope([message()])).status_code==200
    assert post(client,envelope([message(),message('wamid.second')])).status_code==200
    with Session() as db:
        assert db.scalar(select(func.count(WebhookItem.id)))==2
        assert db.scalar(select(func.count(Message.id)))==2
    assert client.get('/api/messages?direction=in').json()['total']==2
    assert client.get('/api/settings/webhook').json()['last_event_at']

def test_status_history_saved_even_if_message_unknown_and_errors_safe(client):
    status={'id':'wamid.unknown','status':'failed','timestamp':'1720000000','errors':[{'code':131030,'message':settings.meta_access_token}]}
    assert post(client,envelope(statuses=[status])).status_code==200
    altered=envelope(statuses=[status]);altered['extra']='different batch'
    assert post(client,altered).status_code==200
    with Session() as db:
        rows=db.scalars(select(WebhookItem)).all();assert len(rows)==1
        assert settings.meta_access_token not in rows[0].payload
        assert json.loads(rows[0].payload)['errors']==[{'code':131030}]

def test_outgoing_status_monotonic_and_no_outbound_graph(client,monkeypatch):
    monkeypatch.setattr('app.messaging.graph',lambda *a,**k:pytest.fail('Webhook must never send'))
    with Session() as db:db.add(Message(phone='+905321234567',body='Existing',meta_id='wamid.out',status='accepted'));db.commit()
    for status in ['read','failed','delivered','sent']:
        assert post(client,envelope(statuses=[{'id':'wamid.out','status':status,'timestamp':'1720000000'}])).status_code==200
    with Session() as db:
        assert db.scalar(select(Message)).status=='read'
        assert db.scalar(select(func.count(WebhookItem.id)))==4

def test_controlled_production_reception_never_changes_test_ids(client,monkeypatch):
    monkeypatch.setattr(settings,'webhook_production_phone_number_id','999999')
    monkeypatch.setattr(settings,'webhook_production_waba_id','888888')
    monkeypatch.setattr(settings,'webhook_production_enabled',False)
    test_id=settings.meta_test_phone_number_id;primary=settings.meta_phone_number_id
    assert post(client,envelope([message('wamid.disabled')],number='999999',waba='888888')).status_code==200
    assert client.get('/api/messages?direction=in').json()['total']==0
    monkeypatch.setattr(settings,'webhook_production_enabled',True)
    assert post(client,envelope([message('wamid.wrong-waba')],number='999999',waba='777777')).status_code==200
    assert post(client,envelope([message('wamid.enabled')],number='999999',waba='888888')).status_code==200
    assert client.get('/api/messages?direction=in').json()['total']==1
    assert settings.meta_test_phone_number_id==test_id and settings.meta_phone_number_id==primary
    assert settings.dry_run and not settings.live_send_enabled

@pytest.mark.parametrize('data',[[],{}, {'entry':'bad'}, {'entry':[None]}, envelope([{'id':'bad','from':'905321234567','text':[]}])])
def test_malformed_signed_payload_rolls_back(client,data):
    assert post(client,data).status_code==422
    with Session() as db:assert db.scalar(select(func.count(Event.id)))==0

def test_https_not_claimed_ready_without_real_url_and_secrets_never_exposed(client,monkeypatch):
    monkeypatch.setattr(settings,'webhook_public_url','')
    r=client.get('/api/settings/webhook');assert r.status_code==200
    assert not r.json()['https_configured'] and not r.json()['public_reachability_verified']
    assert settings.meta_verify_token not in r.text and settings.meta_app_secret not in r.text
    monkeypatch.setattr(settings,'webhook_public_url','https://localhost/api/webhook')
    assert not client.get('/api/settings/webhook').json()['https_configured']
