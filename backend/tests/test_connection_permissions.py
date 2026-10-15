"""Connection checks query Meta only; authenticated operators may also run them."""
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from app.core import Session,Audit,settings


def operator_login(client):
    assert client.post('/api/users',json={'username':'operator','password':'TestPassword123!','role':'operator'}).status_code==200
    assert client.post('/api/logout').status_code==200
    assert client.post('/api/login',json={'username':'operator','password':'TestPassword123!'}).status_code==200


@pytest.mark.parametrize('role',['admin','operator'])
def test_authenticated_connection_check_is_read_only(client,monkeypatch,role):
    if role=='operator':operator_login(client)
    calls=[]
    def fake(method,path,payload=None,params=None):
        assert method=='GET' and payload is None
        calls.append(path)
        if path==settings.meta_phone_number_id:return {'id':settings.meta_phone_number_id,'verified_name':'Synthetic business'}
        assert path==settings.meta_waba_id+'/phone_numbers'
        return {'data':[{'id':settings.meta_phone_number_id}]}
    monkeypatch.setattr('app.messaging.graph',fake)
    flags=(settings.dry_run,settings.live_send_enabled,settings.deployment_send_lock)
    response=client.post('/api/settings/test',json={})
    assert response.status_code==200 and response.json()['ok']
    assert len(calls)==2
    assert client.get('/api/settings/client-status').json()['verified']
    assert flags==(settings.dry_run,settings.live_send_enabled,settings.deployment_send_lock)
    for secret in (settings.meta_access_token,settings.meta_app_secret,settings.meta_verify_token):assert secret not in response.text
    with Session() as db:
        row=db.scalar(select(Audit).where(Audit.action=='meta_connection_test'))
        assert row is not None
    if role=='operator':
        assert client.get('/api/settings').status_code==403
        assert client.get('/api/settings/webhook').status_code==403
        assert client.post('/api/settings/test-message/prepare',json={'recipient':'+905321234567'}).status_code==403
        assert client.post('/api/users',json={'username':'other','password':'TestPassword123!','role':'operator'}).status_code==403


def test_connection_check_requires_session_and_csrf(client,monkeypatch):
    monkeypatch.setattr('app.messaging.graph',lambda *a,**k:pytest.fail('Unauthorized check reached Meta'))
    client.headers.pop('X-HYS-Request')
    assert client.post('/api/settings/test',json={}).status_code==403
    client.headers['X-HYS-Request']='1'
    client.post('/api/logout')
    assert client.post('/api/settings/test',json={}).status_code==401


def test_operator_connection_failure_never_marks_verified(client,monkeypatch):
    operator_login(client)
    def fail(*args,**kwargs):raise HTTPException(502,{'code':190,'message':'Meta erişim tokenı geçersiz.'})
    monkeypatch.setattr('app.messaging.graph',fail)
    response=client.post('/api/settings/test',json={})
    assert response.status_code==502 and response.json()['detail']['code']==190
    assert not client.get('/api/settings/client-status').json()['verified']
