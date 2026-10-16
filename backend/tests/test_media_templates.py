import json
import pytest
from sqlalchemy import select,func
from app.core import *
from app import media_templates
from tests.test_staff import prepared,no_network

@pytest.fixture
def proposal(prepared):
    with Session() as db:asset=db.scalar(select(StaffAsset).where(StaffAsset.kind=='document'))
    return {'name':'hys_personel_yeni_belge','category':'UTILITY','body':'Personel duyuru belgesi ektedir.','footer':'HYS','asset_id':asset.id,'confirmed':True}

@pytest.fixture(autouse=True)
def forbidden(monkeypatch):
    def fail(*a,**kw):pytest.fail('Gerçek Meta API yasak')
    monkeypatch.setattr(media_templates,'graph',fail);monkeypatch.setattr(media_templates,'upload_template_sample',fail)

def test_simulation_and_duplicate(client,proposal):
    r=client.post('/api/templates/media-review',json=proposal);assert r.status_code==200,r.text
    assert r.json()['status']=='LOCAL_DRAFT'
    assert client.post('/api/templates/media-review',json=proposal).status_code==409
    with Session() as db:assert json.loads(db.get(Template,r.json()['id']).components)[0]['format']=='DOCUMENT'

def test_confirmation_and_validation(client,proposal):
    assert client.post('/api/templates/media-review',json={**proposal,'confirmed':False}).status_code==422
    assert client.post('/api/templates/media-review',json={**proposal,'body':'Merhaba {{1}}'}).status_code==422
    assert client.post('/api/templates/media-review',json={**proposal,'name':'Geçersiz ad'}).status_code==422

@pytest.mark.parametrize('kind',['document','video'])
def test_mock_submission(client,proposal,monkeypatch,kind):
    with Session() as db:proposal={**proposal,'asset_id':db.scalar(select(StaffAsset.id).where(StaffAsset.kind==kind))}
    monkeypatch.setattr(settings,'dry_run',False);monkeypatch.setattr(settings,'meta_environment','production');monkeypatch.setattr(media_templates,'connection_ok',lambda db:True)
    calls=[];uploads=[]
    def fake(method,path,payload=None,params=None):
        assert not path.endswith('/messages');calls.append((method,path,payload));return {'data':[]} if method=='GET' else {'id':'12345','status':'PENDING'}
    monkeypatch.setattr(media_templates,'graph',fake);monkeypatch.setattr(media_templates,'upload_template_sample',lambda asset,kind:uploads.append(kind) or '4:fakehandle')
    r=client.post('/api/templates/media-review',json=proposal);assert r.status_code==200,r.text
    assert uploads==[kind.upper()] and r.json()['status']=='PENDING'
    assert calls[-1][2]['components'][0]['example']=={'header_handle':['4:fakehandle']}
    with Session() as db:assert 'fakehandle' not in db.get(Template,r.json()['id']).components
    assert client.post('/api/templates/media-review',json=proposal).status_code==409

def test_ambiguous_never_resubmits(client,proposal,monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(settings,'dry_run',False);monkeypatch.setattr(settings,'meta_environment','production');monkeypatch.setattr(media_templates,'connection_ok',lambda db:True)
    def fake(method,*a,**k):
        if method=='GET':return {'data':[]}
        raise HTTPException(502,'timeout')
    monkeypatch.setattr(media_templates,'graph',fake);monkeypatch.setattr(media_templates,'upload_template_sample',lambda *a:'4:fake')
    assert client.post('/api/templates/media-review',json=proposal).status_code==502
    with Session() as db:assert db.scalar(select(Template).where(Template.name==proposal['name'])).status=='SUBMISSION_UNKNOWN'
    assert client.post('/api/templates/media-review',json=proposal).status_code==409

def test_operator_cannot_submit(client,proposal):
    client.post('/api/users',json={'username':'operator','password':'TestPassword123!','role':'operator'});client.post('/api/logout',json={});client.post('/api/login',json={'username':'operator','password':'TestPassword123!'})
    assert client.post('/api/templates/media-review',json=proposal).status_code==403

@pytest.fixture
def real_mode(monkeypatch):
    monkeypatch.setattr(settings,'dry_run',False);monkeypatch.setattr(settings,'meta_environment','production');monkeypatch.setattr(media_templates,'connection_ok',lambda db:True)

def test_upload_error_is_explained_redacted_and_same_name_can_retry(client,proposal,real_mode,monkeypatch):
    from fastapi import HTTPException
    creates=[]
    def graph(method,path,payload=None,params=None):
        if method=='GET':return {'data':[]}
        creates.append(payload);return {'id':'1234','status':'PENDING'}
    monkeypatch.setattr(media_templates,'graph',graph)
    def bad(*args):raise HTTPException(502,{'message':'Yetki yok','meta_message':'Invalid token '+settings.meta_access_token,'code':190,'ambiguous':False})
    monkeypatch.setattr(media_templates,'upload_template_sample',bad)
    r=client.post('/api/templates/media-review',json=proposal);assert r.status_code==502
    detail=r.json()['detail'];assert detail['phase']=='uploading' and detail['safe_to_retry'] and detail['code']==190
    assert 'Invalid token' in detail['message'] and settings.meta_access_token not in r.text
    assert creates==[]
    state=client.get('/api/templates/media-review/'+str(detail['template_id'])).json()
    assert state['status']=='UPLOAD_FAILED' and state['review']['code']==190
    monkeypatch.setattr(media_templates,'upload_template_sample',lambda *a:'4:handle')
    r=client.post('/api/templates/media-review',json=proposal);assert r.status_code==200,r.text
    assert len(creates)==1

def test_definitive_template_rejection_can_retry_but_not_ambiguous(client,proposal,real_mode,monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(media_templates,'upload_template_sample',lambda *a:'4:handle')
    def bad(method,*args,**kwargs):
        if method=='GET':return {'data':[]}
        raise HTTPException(502,{'code':100,'ambiguous':False,'meta_message':'Invalid category'})
    monkeypatch.setattr(media_templates,'graph',bad)
    r=client.post('/api/templates/media-review',json=proposal)
    assert r.json()['detail']['safe_to_retry']
    with Session() as db:assert db.scalar(select(Template).where(Template.name==proposal['name'])).status=='SUBMISSION_REJECTED'

def test_old_upload_failed_record_allows_retry_without_resetting_data(client,proposal,real_mode,monkeypatch):
    import hashlib
    with Session() as db:
        t=Template(name=proposal['name'],body='Eski metin',status='UPLOAD_FAILED',components='[]');db.add(t)
        key='media_review:'+hashlib.sha256((settings.meta_waba_id+':'+proposal['name']).encode()).hexdigest()
        db.add(SystemValue(key=key,value=json.dumps({'phase':'UPLOAD_FAILED'})));db.commit();id=t.id
    monkeypatch.setattr(media_templates,'upload_template_sample',lambda *a:'4:handle')
    monkeypatch.setattr(media_templates,'graph',lambda method,*a,**k:{'data':[]} if method=='GET' else {'id':'123','status':'PENDING'})
    r=client.post('/api/templates/media-review',json=proposal);assert r.status_code==200,r.text
    assert r.json()['id']==id

def test_check_reconciles_unknown_without_any_post_to_meta(client,proposal,real_mode,monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(media_templates,'upload_template_sample',lambda *a:'4:handle')
    def timeout(method,*a,**k):
        if method=='GET':return {'data':[]}
        raise HTTPException(502,'timeout')
    monkeypatch.setattr(media_templates,'graph',timeout)
    client.post('/api/templates/media-review',json=proposal)
    with Session() as db:id=db.scalar(select(Template.id).where(Template.name==proposal['name']))
    def read_only(method,*a,**k):
        assert method=='GET'
        return {'data':[{'id':'987','name':proposal['name'],'language':'tr','status':'PENDING','category':'UTILITY','components':[{'type':'HEADER','format':'DOCUMENT'},{'type':'BODY','text':proposal['body']}]}]}
    monkeypatch.setattr(media_templates,'graph',read_only)
    assert client.post(f'/api/templates/media-review/{id}/check').json()['status']=='PENDING'
    assert client.post(f'/api/templates/{id}/submit').status_code==409


def test_multiline_meta_handle_reaches_template_review_without_modification(client,proposal,real_mode,monkeypatch):
    import app.meta as meta
    import app.media_templates as reviews
    handle='4::first-signed-handle\n4::second-signed-handle'
    submitted=[]
    def fake_graph(method,path,payload=None,**kwargs):
        if method=='GET':return {'data':[]}
        if path=='app/uploads':return {'id':'upload:sample'}
        if path=='upload:sample':return {'h':handle}
        submitted.append(payload);return {'id':'12345','status':'PENDING'}
    monkeypatch.setattr(meta,'graph',fake_graph)
    monkeypatch.setattr(reviews,'graph',fake_graph)
    monkeypatch.setattr(reviews,'upload_template_sample',meta.upload_template_sample)
    response=client.post('/api/templates/media-review',json=proposal)
    assert response.status_code==200,response.text
    assert len(submitted)==1
    assert submitted[0]['components'][0]['example']['header_handle']==[handle]
    with Session() as db:assert db.scalar(select(func.count()).select_from(Message))==0
