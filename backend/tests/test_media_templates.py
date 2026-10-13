import json
import pytest
from sqlalchemy import select
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
