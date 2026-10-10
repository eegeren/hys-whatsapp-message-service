"""Mock template review requests only; never calls real Meta or message sending."""
import json
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from app.core import settings,Session,Template,Message,Campaign
from app.template_components import MediaUpload

PNG=b'\x89PNG\r\n\x1a\nmock-image'

def inputs():
    return {'name':'mock_personel_carousel','body':'HYS {{1}}','examples':{'1':'Duyuru'},
            'cards':[{'text':'Kart {{1}}','examples':{'1':'Bir'}},{'text':'İkinci görsel'}],
            'button_text':'Gördüm','confirmed':True}

def post(client,payload=None,content=PNG):
    return client.post('/api/templates/carousel-review',data={'data':json.dumps(payload or inputs())},
        files=[('files',('one.png',content,'image/png')),('files',('two.png',PNG,'image/png'))])

@pytest.fixture
def meta(monkeypatch):
    monkeypatch.setattr(settings,'meta_environment','production')
    calls=[];uploads=[]
    def graph(method,path,payload=None,params=None):
        calls.append((method,path,payload))
        assert not path.endswith('/messages')
        if path.endswith('/phone_numbers'):return {'data':[{'id':settings.meta_phone_number_id}]}
        if method=='GET':return {'data':[]}
        return {'id':'777','status':'PENDING'}
    monkeypatch.setattr('app.carousel_templates.graph',graph)
    monkeypatch.setattr('app.carousel_templates.upload_template_sample',lambda asset:uploads.append(asset) or f'4::private-sample-{len(uploads)}')
    return calls,uploads

def test_confirmed_review_payload_stays_pending_no_messages_and_no_double_submit(client,meta):
    calls,uploads=meta;r=post(client)
    assert r.status_code==200,r.text
    assert r.json()['status']=='PENDING' and len(uploads)==2
    submitted=[c for c in calls if c[0]=='POST'];assert len(submitted)==1
    payload=submitted[0][2]
    assert payload['category']=='MARKETING' and payload['language']=='tr'
    assert payload['components'][0]['example']['body_text']==[['Duyuru']]
    cards=payload['components'][1]['cards']
    assert cards[0]['components'][0]['example']['header_handle']==['4::private-sample-1']
    assert cards[0]['components'][1]['example']['body_text']==[['Bir']]
    assert cards[0]['components'][2]['buttons']==[{'type':'QUICK_REPLY','text':'Gördüm'}]
    with Session() as db:
        t=db.scalar(select(Template));assert t.status=='PENDING' and 'private-sample' not in t.components
        assert db.scalar(select(Message.id)) is None and db.scalar(select(Campaign.id)) is None
    assert post(client).status_code==409 and len(uploads)==2
    assert client.post(f"/api/templates/{r.json()['id']}/submit").status_code==409
    assert len([c for c in calls if c[0]=='POST'])==1

@pytest.mark.parametrize('change',[{'confirmed':False},{'name':'BAD NAME'},{'cards':[{'text':'Only one'}]},{'examples':{}},{'body':'{{2}}','examples':{'2':'Wrong order'}}])
def test_invalid_review_never_calls_meta(client,meta,change):
    payload={**inputs(),**change};assert post(client,payload).status_code==422
    assert meta==([],[])

def test_invalid_file_and_wrong_waba_stop_before_upload(client,meta,monkeypatch):
    assert post(client,content=b'not-a-png').status_code==422 and meta==([],[])
    monkeypatch.setattr('app.carousel_templates.graph',lambda *a,**k:{'data':[{'id':'wrong-number'}]})
    assert post(client).status_code==403 and not meta[1]

def test_existing_remote_template_never_uploads_or_resubmits(client,meta,monkeypatch):
    def lookup(method,path,**kw):
        if path.endswith('/phone_numbers'):return {'data':[{'id':settings.meta_phone_number_id}]}
        return {'data':[{'name':inputs()['name'],'status':'PENDING'}]}
    monkeypatch.setattr('app.carousel_templates.graph',lookup)
    assert post(client).status_code==409 and not meta[1]

def test_ambiguous_create_timeout_is_not_automatically_repeated(client,meta,monkeypatch):
    calls,uploads=meta
    original=__import__('app.carousel_templates',fromlist=['graph']).graph
    def timeout(method,path,payload=None,params=None):
        if method=='POST':calls.append((method,path,payload));raise HTTPException(502,'Meta zaman aşımı')
        return original(method,path,payload,params)
    monkeypatch.setattr('app.carousel_templates.graph',timeout)
    assert post(client).status_code==502
    with Session() as db:assert db.scalar(select(Template)).status=='SUBMISSION_UNKNOWN'
    assert post(client).status_code==409
    assert len([c for c in calls if c[0]=='POST'])==1

def test_sample_upload_failure_can_be_manually_retried_without_template_post(client,meta,monkeypatch):
    def fail(asset):raise HTTPException(502,{'code':100,'message':'Mock görsel reddedildi'})
    monkeypatch.setattr('app.carousel_templates.upload_template_sample',fail)
    assert post(client).status_code==502
    assert not any(c[0]=='POST' for c in meta[0])
    monkeypatch.setattr('app.carousel_templates.upload_template_sample',lambda asset:'4::private-retry-sample')
    assert post(client).status_code==200
    assert len([c for c in meta[0] if c[0]=='POST'])==1

def test_operator_cannot_submit_review(client,meta):
    assert client.post('/api/users',json={'username':'operator','password':'TestPassword123!','role':'operator'}).status_code==200
    assert client.post('/api/login',json={'username':'operator','password':'TestPassword123!'}).status_code==200
    assert post(client).status_code==403 and meta==([],[])

def test_resumable_upload_uses_app_session_and_binary_body(monkeypatch):
    from app.meta import upload_template_sample
    calls=[]
    def graph(method,path,payload=None,params=None,content=None):
        calls.append((method,path,params,content))
        return {'id':'upload:abc=?sig=signed_mock'} if path=='app/uploads' else {'h':'4::mock-private-handle'}
    monkeypatch.setattr('app.meta.graph',graph)
    result=upload_template_sample(MediaUpload('sample.png','image/png',PNG))
    assert result=='4::mock-private-handle'
    assert calls[0][2]=={'file_name':'sample.png','file_length':len(PNG),'file_type':'image/png'}
    assert calls[1][1]=='upload:abc=?sig=signed_mock' and calls[1][3]==PNG

def test_resumable_http_format_has_oauth_offset_and_raw_bytes(monkeypatch):
    import httpx
    from app.meta import graph
    calls=[]
    class Client:
        def __init__(self,**kwargs):assert kwargs['follow_redirects'] is False and kwargs['trust_env'] is False
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def request(self,method,url,**kwargs):
            calls.append((method,url,kwargs))
            return httpx.Response(200,json={'h':'4::mock-handle'})
    monkeypatch.setattr('app.meta.httpx.Client',Client)
    graph('POST','upload:mock?sig=mock-signature',content=PNG)
    method,url,kwargs=calls[0]
    assert method=='POST' and url.startswith('https://graph.facebook.com/')
    assert settings.meta_access_token not in url
    assert kwargs['headers']['Authorization']=='OAuth '+settings.meta_access_token
    assert kwargs['headers']['file_offset']=='0'
    assert kwargs['content']==PNG and 'json' not in kwargs and 'files' not in kwargs
