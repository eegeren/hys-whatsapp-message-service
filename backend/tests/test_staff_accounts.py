from sqlalchemy import select
from app.core import Session,User,settings
from app.main import ph

def test_create_named_support_account_and_permissions(client):
    assert client.post('/api/users',json={'username':'emre.erbilen','password':'FakeLocalTest123!','display_name':'Emre Erbilen','role':'operator'}).status_code==200
    row=next(u for u in client.get('/api/users').json() if u['username']=='emre.erbilen')
    assert row['display_name']=='Emre Erbilen' and row['role']=='operator' and 'password' not in row
    with Session() as db:
        stored=db.scalar(select(User).where(User.username=='emre.erbilen'))
        assert stored.password!='FakeLocalTest123!' and ph.verify(stored.password,'FakeLocalTest123!')
    assert client.post('/api/quick-replies',json={'title':'Karşılama','category':'Genel','body':'Merhaba, ben {{personel_adi}}.'}).status_code==201
    assert client.post('/api/login',json={'username':'emre.erbilen','password':'FakeLocalTest123!'}).status_code==200
    assert client.get('/api/me').json()['display_name']=='Emre Erbilen'
    assert client.get('/api/quick-replies').json()[0]['rendered_body']=='Merhaba, ben Emre.'
    assert client.get('/api/users').status_code==403
    assert client.get('/api/settings').status_code==403
    assert client.post('/api/users',json={'username':'other','password':'FakeLocalTest123!'}).status_code==403

def test_support_can_verify_shared_meta_connection_without_sends(client,monkeypatch):
    client.post('/api/users',json={'username':'support','password':'FakeLocalTest123!','role':'operator'})
    client.post('/api/login',json={'username':'support','password':'FakeLocalTest123!'})
    calls=[]
    def fake_graph(method,path,payload=None,params=None):
        assert method=='GET';calls.append(path)
        return {'data':[{'id':settings.meta_phone_number_id}]} if path.endswith('/phone_numbers') else {'id':settings.meta_phone_number_id,'verified_name':'HYS'}
    monkeypatch.setattr('app.messaging.graph',fake_graph)
    result=client.post('/api/settings/test')
    assert result.status_code==200 and len(calls)==2 and settings.meta_access_token not in result.text
    assert client.get('/api/settings/client-status').json()['verified'] is True
    client.post('/api/login',json={'username':'admin','password':'TestPassword123!'})
    assert client.get('/api/settings/client-status').json()['verified'] is True

def test_duplicates_and_invalid_display_names(client):
    assert client.post('/api/users',json={'username':'admin','password':'FakeLocalTest123!'}).status_code==409
    assert client.post('/api/users',json={'username':'invalid','password':'FakeLocalTest123!','display_name':'Name\nOther'}).status_code==422
