import hashlib,hmac,json
from datetime import timedelta
import pytest
from sqlalchemy import select,func
from fastapi import HTTPException
from app.core import settings,Session,TestMessage,Message,now,SystemValue

@pytest.fixture
def sandbox(monkeypatch):
    monkeypatch.setattr(settings,'meta_test_message_enabled',True)
    monkeypatch.setattr(settings,'meta_test_phone_number_id','123456')
    monkeypatch.setattr(settings,'meta_test_waba_id','654321')
    monkeypatch.setattr(settings,'meta_production_phone_number_ids','')
    monkeypatch.setattr(settings,'meta_test_recipients','+905321234567,+905329999999')
    monkeypatch.setattr(settings,'meta_phone_number_id','123456')
    monkeypatch.setattr(settings,'meta_waba_id','654321')
    monkeypatch.setattr(settings,'meta_environment','test')
    monkeypatch.setattr(settings,'dry_run',True)
    monkeypatch.setattr(settings,'live_send_enabled',False)
    calls=[]
    def fake(method,path,payload=None,params=None):
        calls.append((method,path,payload,params))
        if method=='POST':return {'messaging_product':'whatsapp','messages':[{'id':'wamid.test.'+str(len(calls)),'message_status':'accepted'}]}
        if path=='654321':return {'id':'654321'}
        if path=='123456':return {'id':'123456','account_mode':'SANDBOX'}
        if path.endswith('/phone_numbers'):return {'data':[{'id':'123456','account_mode':'SANDBOX'}]}
        return {'data':[{'name':'hello_world','language':'en_US','status':'APPROVED'}]}
    monkeypatch.setattr('app.test_messages.graph',fake)
    from app.test_messages import sender_hash
    with Session() as db:db.add(SystemValue(key='test_sender_attestation',value=json.dumps({'fingerprint':sender_hash(),'phone_number_id':'123456','waba_id':'654321'})));db.commit()
    return calls
def prepare(c,recipient='+905321234567'):
    r=c.post('/api/settings/test-message/prepare',json={'recipient':recipient});assert r.status_code==200,r.text
    return r.json()
def body(p,confirmed=True,verified=True):return {'id':p['id'],'confirmation_token':p['confirmation_token'],'confirmed':confirmed,'recipient_verified':verified}
def test_prepare_is_read_only_and_send_is_separate(client,sandbox):
    p=prepare(client);assert all(call[0]=='GET' for call in sandbox)
    r=client.post('/api/settings/test-message/send',json=body(p));assert r.status_code==200,r.text
    assert r.json()['status']=='accepted';assert r.json()['delivery_status']=='unknown';assert r.json()['message_id'].startswith('wamid.')
    assert settings.dry_run and not settings.live_send_enabled
    assert client.get('/api/messages').json()['total']==0
    posts=[call for call in sandbox if call[0]=='POST'];assert len(posts)==1
    assert posts[0][1]=='123456/messages'
    assert posts[0][2]['template']=={'name':'hello_world','language':{'code':'en_US'}}
    assert posts[0][2]['to']=='905321234567'
    assert client.post('/api/settings/test-message/send',json=body(p)).json()['message_id']==r.json()['message_id']
    assert len([call for call in sandbox if call[0]=='POST'])==1
@pytest.mark.parametrize('number',['05321234567','905321234567','+90 5321234567','+00000000000','abc','+905320000000'])
def test_unlisted_or_invalid_recipient_blocks_network(client,sandbox,number):
    r=client.post('/api/settings/test-message/prepare',json={'recipient':number});assert r.status_code in (403,422)
    assert not sandbox
@pytest.mark.parametrize('field,value',[('meta_environment','production'),('meta_test_phone_number_id','777777'),('meta_test_phone_number_id',''),('meta_test_message_enabled',False),('dry_run',False),('live_send_enabled',True)])
def test_configuration_gates(client,sandbox,monkeypatch,field,value):
    monkeypatch.setattr(settings,field,value)
    r=client.post('/api/settings/test-message/prepare',json={'recipient':'+905321234567'});assert r.status_code==403;assert not sandbox
def test_live_sender_requires_manual_confirmation_but_is_not_automatic_rejection(client,sandbox,monkeypatch):
    old=__import__('app.test_messages',fromlist=['graph']).graph
    def live(method,path,payload=None,params=None):
        if path=='123456':return {'id':'123456','account_mode':'LIVE'}
        return old(method,path,payload,params)
    monkeypatch.setattr('app.test_messages.graph',live)
    with Session() as db:db.delete(db.get(SystemValue,'test_sender_attestation'));db.commit()
    assert client.post('/api/settings/test-message/prepare',json={'recipient':'+905321234567'}).status_code==403
    data={'phone_number_id':'123456','waba_id':'654321','compared_in_meta':True,'meta_development_number':True}
    assert client.post('/api/settings/test-message/verify-sender',json={**data,'waba_id':'999'}).status_code==403
    assert client.post('/api/settings/test-message/verify-sender',json={**data,'compared_in_meta':False}).status_code==403
    r=client.post('/api/settings/test-message/verify-sender',json=data);assert r.status_code==200;assert r.json()['mode']=='LIVE'
    prepare(client);assert all(x[0]=='GET' for x in sandbox)
    monkeypatch.setattr(settings,'meta_production_phone_number_ids','123456')
    assert client.post('/api/settings/test-message/prepare',json={'recipient':'+905321234567'}).status_code==403

def test_remote_template_not_approved(client,sandbox,monkeypatch):
    old=__import__('app.test_messages',fromlist=['graph']).graph
    def fake(method,path,payload=None,params=None):
        if path.endswith('/message_templates'):return {'data':[{'name':'hello_world','language':'en_US','status':'PENDING'}]}
        return old(method,path,payload,params)
    monkeypatch.setattr('app.test_messages.graph',fake)
    assert client.post('/api/settings/test-message/prepare',json={'recipient':'+905321234567'}).status_code==403
    assert all(x[0]=='GET' for x in sandbox)
def test_missing_consent_or_bad_token_never_sends(client,sandbox):
    p=prepare(client)
    assert client.post('/api/settings/test-message/send',json=body(p,False)).status_code==403
    assert client.post('/api/settings/test-message/send',json=body(p,True,False)).status_code==403
    b=body(p);b['confirmation_token']='x'*40
    assert client.post('/api/settings/test-message/send',json=b).status_code==403
    assert all(x[0]=='GET' for x in sandbox)
def test_expired_or_changed_configuration_blocks(client,sandbox,monkeypatch):
    p=prepare(client)
    with Session() as db:db.get(TestMessage,p['id']).expires=now()-timedelta(seconds=1);db.commit()
    assert client.post('/api/settings/test-message/send',json=body(p)).status_code==409
    p=prepare(client);monkeypatch.setattr(settings,'meta_graph_api_version','v26.0')
    assert client.post('/api/settings/test-message/send',json=body(p)).status_code==403
def test_global_rate_limit(client,sandbox):
    p=prepare(client);assert client.post('/api/settings/test-message/send',json=body(p)).status_code==200
    p2=prepare(client,'+905329999999')
    assert client.post('/api/settings/test-message/send',json=body(p2)).status_code==429
    assert len([x for x in sandbox if x[0]=='POST'])==1
def test_failed_preflight_is_rate_limited(client,sandbox,monkeypatch):
    count=[]
    def deny(*args,**kwargs):count.append(1);raise HTTPException(502,{'code':190,'message':'Geçersiz test tokenı'})
    monkeypatch.setattr('app.test_messages.graph',deny)
    for _ in range(5):assert client.post('/api/settings/test-message/prepare',json={'recipient':'+905321234567'}).status_code==502
    assert client.post('/api/settings/test-message/prepare',json={'recipient':'+905321234567'}).status_code==429
    assert len(count)==5
def test_meta_error_is_recorded_without_secrets(client,sandbox,monkeypatch):
    p=prepare(client);old=__import__('app.test_messages',fromlist=['graph']).graph
    def fake(method,path,payload=None,params=None):
        if method=='POST':raise HTTPException(502,{'code':131030,'message':'Alıcı doğrulanmadı '+settings.meta_access_token,'ambiguous':False})
        return old(method,path,payload,params)
    monkeypatch.setattr('app.test_messages.graph',fake)
    r=client.post('/api/settings/test-message/send',json=body(p));assert r.status_code==502;assert r.json()['detail']['code']==131030
    assert settings.meta_access_token not in r.text
    state=client.get('/api/settings/test-message');assert settings.meta_access_token not in state.text
    assert state.json()['records'][0]['status']=='failed';assert state.json()['records'][0]['delivery_status']=='unknown'
def test_timeout_never_retries(client,sandbox,monkeypatch):
    p=prepare(client);old=__import__('app.test_messages',fromlist=['graph']).graph;calls=[]
    def fake(method,path,payload=None,params=None):
        if method=='POST':calls.append(1);raise HTTPException(502,'Ağ zaman aşımı')
        return old(method,path,payload,params)
    monkeypatch.setattr('app.test_messages.graph',fake)
    assert client.post('/api/settings/test-message/send',json=body(p)).status_code==502
    assert client.post('/api/settings/test-message/send',json=body(p)).json()['status']=='uncertain'
    assert len(calls)==1
def test_signed_webhook_updates_only_test_delivery(client,sandbox):
    p=prepare(client);r=client.post('/api/settings/test-message/send',json=body(p));id=r.json()['message_id']
    for status in ['read','delivered','sent']:
        data={'entry':[{'changes':[{'value':{'metadata':{'phone_number_id':'123456'},'statuses':[{'id':id,'status':status}]}}]}]}
        raw=json.dumps(data).encode();sig='sha256='+hmac.new(settings.meta_app_secret.encode(),raw,hashlib.sha256).hexdigest()
        assert client.post('/api/webhook',content=raw,headers={'X-Hub-Signature-256':sig}).status_code==200
    row=client.get('/api/settings/test-message').json()['records'][0]
    assert row['status']=='accepted';assert row['delivery_status']=='read';assert client.get('/api/messages').json()['total']==0
def test_operator_cannot_prepare_or_send(client,sandbox):
    p=prepare(client)
    client.post('/api/users',json={'username':'operator','password':'TestPassword123!','role':'operator'})
    client.post('/api/logout');client.post('/api/login',json={'username':'operator','password':'TestPassword123!'})
    assert client.get('/api/settings/test-message').status_code==403
    assert client.post('/api/settings/test-message/prepare',json={'recipient':'+905321234567'}).status_code==403
    assert client.post('/api/settings/test-message/send',json=body(p)).status_code==403
    assert all(x[0]=='GET' for x in sandbox)

def test_readiness_uses_get_and_records_live_lock(client,sandbox,monkeypatch):
    r=client.post('/api/settings/test-message/check');assert r.status_code==200;assert r.json()['ready']
    assert client.get('/api/settings/test-message').json()['sender_mode']=='SANDBOX'
    assert all(x[0]=='GET' for x in sandbox)
    monkeypatch.setattr('app.test_messages.graph',lambda *args,**kwargs:{'id':'123456','account_mode':'LIVE'})
    r=client.post('/api/settings/test-message/check');assert not r.json()['ready'];assert r.json()['mode']=='unknown'
    assert client.get('/api/settings/test-message').json()['sender_mode']=='unknown'

def test_client_cannot_change_recipient_after_confirmation(client,sandbox):
    p=prepare(client);b=body(p);b['recipient']='+905320000000';b['template']='arbitrary'
    r=client.post('/api/settings/test-message/send',json=b);assert r.status_code==200
    sent=[x for x in sandbox if x[0]=='POST'][0][2]
    assert sent['to']=='905321234567';assert sent['template']['name']=='hello_world'

def test_daily_limit_never_calls_send(client,sandbox):
    p=prepare(client)
    with Session() as db:db.add(SystemValue(key='test_message_rate',value=json.dumps({'day':now().date().isoformat(),'count':10,'last':(now()-timedelta(minutes=2)).isoformat()})));db.commit()
    assert client.post('/api/settings/test-message/send',json=body(p)).status_code==429
    assert all(x[0]=='GET' for x in sandbox)

@pytest.mark.parametrize('field,value',[('meta_phone_number_id','777'),('meta_waba_id','888'),('meta_test_waba_id','888'),('meta_access_token','changed-token')])
def test_attestation_is_bound_to_configuration(client,sandbox,monkeypatch,field,value):
    monkeypatch.setattr(settings,field,value)
    assert client.post('/api/settings/test-message/prepare',json={'recipient':'+905321234567'}).status_code==403
    assert not sandbox

def test_unknown_mode_not_inferred_as_sandbox_and_audited(client,sandbox,monkeypatch):
    from app.core import Audit
    old=__import__('app.test_messages',fromlist=['graph']).graph
    def remote(method,path,payload=None,params=None):
        if path=='123456':return {'id':'123456'}
        return old(method,path,payload,params)
    monkeypatch.setattr('app.test_messages.graph',remote)
    r=client.post('/api/settings/test-message/verify-sender',json={'phone_number_id':'123456','waba_id':'654321','compared_in_meta':True,'meta_development_number':True})
    assert r.status_code==200 and r.json()['mode']=='unknown'
    with Session() as db:
        record=db.scalar(select(Audit).where(Audit.action=='test_sender_manual_confirmation'))
        assert '123456' in record.detail and '654321' in record.detail
        assert settings.meta_access_token not in record.detail
    assert all(x[0]=='GET' for x in sandbox)

def test_local_recipient_setup_is_admin_confirmed_and_preserves_secrets(client,sandbox,monkeypatch,tmp_path):
    env=tmp_path/'local.env';env.write_text('META_ACCESS_TOKEN=private-test-only\nMETA_APP_SECRET=unchanged-test-secret\nMETA_TEST_RECIPIENTS=\n',encoding='utf-8')
    monkeypatch.setattr('app.test_messages.LOCAL_ENV_PATH',env)
    payload={'recipient':'+905321234567','recipient_verified_in_meta':True}
    assert client.post('/api/settings/test-message/recipient',json={**payload,'recipient_verified_in_meta':False}).status_code==403
    assert client.post('/api/settings/test-message/recipient',json={**payload,'recipient':'05321234567'}).status_code==422
    r=client.post('/api/settings/test-message/recipient',json=payload);assert r.status_code==200
    assert env.read_text(encoding='utf-8')=='META_ACCESS_TOKEN=private-test-only\nMETA_APP_SECRET=unchanged-test-secret\nMETA_TEST_RECIPIENTS=+905321234567\n'
    assert client.get('/api/settings/test-message').json()['recipient_count']==1
    assert client.post('/api/settings/test-message/prepare',json={'recipient':'+905329999999'}).status_code==403
    assert not sandbox
    client.post('/api/users',json={'username':'operator','password':'TestPassword123!','role':'operator'})
    client.post('/api/logout');client.post('/api/login',json={'username':'operator','password':'TestPassword123!'})
    assert client.post('/api/settings/test-message/recipient',json=payload).status_code==403

def test_recipient_setup_requires_sender_onboarding(client,sandbox,monkeypatch,tmp_path):
    env=tmp_path/'local.env';env.write_text('META_TEST_RECIPIENTS=\n',encoding='utf-8')
    monkeypatch.setattr('app.test_messages.LOCAL_ENV_PATH',env)
    with Session() as db:db.delete(db.get(SystemValue,'test_sender_attestation'));db.commit()
    assert client.post('/api/settings/test-message/recipient',json={'recipient':'+905321234567','recipient_verified_in_meta':True}).status_code==403
    assert env.read_text()=='META_TEST_RECIPIENTS=\n'
    assert not sandbox

def test_recipient_save_failure_never_enables_recipient(client,sandbox,monkeypatch,tmp_path):
    monkeypatch.setattr('app.test_messages.LOCAL_ENV_PATH',tmp_path/'missing.env')
    previous=settings.meta_test_recipients
    r=client.post('/api/settings/test-message/recipient',json={'recipient':'+905321234567','recipient_verified_in_meta':True})
    assert r.status_code==409 and settings.meta_test_recipients==previous
    assert not sandbox
