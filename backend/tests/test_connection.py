import httpx,pytest,json
from fastapi import HTTPException
from sqlalchemy import select
from app.core import settings,Session,SystemValue
from app.meta import graph
from app.main import connection_ok

@pytest.fixture
def meta_config(monkeypatch):
    monkeypatch.setattr(settings,'meta_access_token','test-only-sensitive-token')
    monkeypatch.setattr(settings,'meta_phone_number_id','123456')
    monkeypatch.setattr(settings,'meta_waba_id','654321')
    monkeypatch.setattr(settings,'meta_environment','test')
    monkeypatch.setattr(settings,'dry_run',True)
    monkeypatch.setattr(settings,'live_send_enabled',False)

def test_connection_only_get_and_no_secret_exposure(client,meta_config,monkeypatch):
    calls=[]
    def fake(method,path,payload=None,params=None):
        calls.append((method,path,payload,params))
        return {'id':'123456','verified_name':'Test'} if path=='123456' else {'data':[{'id':'123456'}]}
    monkeypatch.setattr('app.messaging.graph',fake)
    r=client.post('/api/settings/test');assert r.status_code==200
    assert len(calls)==2 and all(c[0]=='GET' and c[2] is None for c in calls)
    assert all('messages' not in c[1] and 'register' not in c[1] for c in calls)
    assert settings.dry_run and not settings.live_send_enabled
    data=client.get('/api/settings').json();assert data['verified'];assert data['environment']=='test'
    assert settings.meta_access_token not in r.text and settings.meta_access_token not in json.dumps(data)

def test_failed_check_clears_old_success(client,meta_config,monkeypatch):
    monkeypatch.setattr('app.messaging.graph',lambda method,path,**kwargs:{'id':'123456'} if path=='123456' else {'data':[{'id':'123456'}]})
    assert client.post('/api/settings/test').status_code==200
    def fail(*args,**kwargs):raise HTTPException(502,'Meta erişim tokenı geçersiz veya süresi dolmuş.')
    monkeypatch.setattr('app.messaging.graph',fail)
    r=client.post('/api/settings/test');assert r.status_code==502;assert not client.get('/api/settings').json()['verified']

def test_waba_mismatch_and_pagination(client,meta_config,monkeypatch):
    calls=[]
    def fake(method,path,payload=None,params=None):
        calls.append((path,params))
        if path=='123456':return {'id':'123456'}
        if params.get('after'):return {'data':[{'id':'123456'}]}
        return {'data':[],'paging':{'next':'https://untrusted.invalid/?access_token=secret','cursors':{'after':'next-page'}}}
    monkeypatch.setattr('app.messaging.graph',fake)
    assert client.post('/api/settings/test').status_code==200
    assert all(not c[0].startswith('https:') for c in calls)
    monkeypatch.setattr('app.messaging.graph',lambda *args,**kwargs:{'id':'123456','data':[]})
    assert client.post('/api/settings/test').status_code==422

def test_authorization_header_only(meta_config,monkeypatch):
    original=httpx.Client;seen=[]
    def transport(request):
        seen.append(request)
        return httpx.Response(200,json={'id':'123456'})
    monkeypatch.setattr('app.meta.httpx.Client',lambda **kwargs:original(transport=httpx.MockTransport(transport),**kwargs))
    graph('GET','123456',params={'fields':'id'})
    r=seen[0];assert r.method=='GET';assert not r.content
    assert r.headers['Authorization']=='Bearer '+settings.meta_access_token
    assert settings.meta_access_token not in str(r.url)

@pytest.mark.parametrize('code',[190,100,10,200,130429])
def test_meta_error_is_turkish_and_sanitized(meta_config,monkeypatch,code):
    original=httpx.Client
    transport=httpx.MockTransport(lambda request:httpx.Response(400,json={'error':{'code':code,'message':'raw secret '+settings.meta_access_token}}))
    monkeypatch.setattr('app.meta.httpx.Client',lambda **kwargs:original(transport=transport,**kwargs))
    with pytest.raises(HTTPException) as caught:graph('GET','123456')
    detail=caught.value.detail
    assert settings.meta_access_token not in json.dumps(detail)
    assert 'raw secret' not in detail['message']
    assert detail['code']==code

def test_missing_credentials_does_not_call_network(client,monkeypatch):
    monkeypatch.setattr(settings,'meta_access_token','')
    def forbidden(*args,**kwargs):raise AssertionError('Eksik tokenla ağ isteği yapılmamalı')
    monkeypatch.setattr('app.meta.httpx.Client',forbidden)
    r=client.post('/api/settings/test');assert r.status_code==503;assert '.env' in r.json()['detail']

def test_environment_loading(tmp_path,monkeypatch):
    from app.core import Settings
    keys=['META_ACCESS_TOKEN','META_PHONE_NUMBER_ID','META_WABA_ID','META_APP_SECRET','META_VERIFY_TOKEN','META_GRAPH_API_VERSION']
    for key in keys:monkeypatch.delenv(key,raising=False)
    path=tmp_path/'.env';path.write_text('\n'.join(f'{k}=test-{i}' for i,k in enumerate(keys)))
    config=Settings(_env_file=path)
    for i,key in enumerate(keys):assert getattr(config,key.lower())==f'test-{i}'

def test_empty_inherited_meta_values_do_not_hide_env_file(tmp_path,monkeypatch):
    from app.core import Settings
    keys=['META_ACCESS_TOKEN','META_PHONE_NUMBER_ID','META_WABA_ID','META_APP_SECRET','META_VERIFY_TOKEN','META_GRAPH_API_VERSION']
    for key in keys:monkeypatch.setenv(key,'')
    path=tmp_path/'.env';path.write_text('\n'.join(f'{k}=test-{i}' for i,k in enumerate(keys)))
    config=Settings(_env_file=path)
    for i,key in enumerate(keys):assert getattr(config,key.lower())==f'test-{i}'
