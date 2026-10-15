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

def test_admin_edits_resets_and_soft_deletes_without_losing_history(client):
    from app.core import Message,LoginSession,QuickReply
    assert client.post('/api/users',json={'username':'support.life','password':'OldPassword123!','display_name':'Emre Erbilen','role':'operator'}).status_code==200
    target=next(u for u in client.get('/api/users').json() if u['username']=='support.life')['id']
    assert client.put(f'/api/users/{target}',json={'username':'admin','display_name':'Name'}).status_code==409
    assert client.put(f'/api/users/{target}',json={'username':'emre.updated','display_name':'Emre Yeni'}).status_code==200
    client.post('/api/login',json={'username':'emre.updated','password':'OldPassword123!'})
    old_cookie=client.cookies.get('hys_session')
    client.post('/api/login',json={'username':'admin','password':'TestPassword123!'})
    assert client.post(f'/api/users/{target}/password',json={'password':'short'}).status_code==422
    assert client.post(f'/api/users/{target}/password',json={'password':'NewPassword123!'}).status_code==200
    assert client.get('/api/me',headers={'cookie':'hys_session='+old_cookie}).status_code==401
    assert client.post('/api/login',json={'username':'emre.updated','password':'OldPassword123!'}).status_code==401
    assert client.post('/api/login',json={'username':'emre.updated','password':'NewPassword123!'}).status_code==200
    second_cookie=client.cookies.get('hys_session');assert client.get('/api/me').json()['display_name']=='Emre Yeni'
    client.post('/api/login',json={'username':'admin','password':'TestPassword123!'})
    with Session() as db:
        db.add(QuickReply(title='Private',category='Support',body='Saved',owner_id=target));db.add(Message(phone='+905550000001',body='Historical message',direction='out'));db.commit()
    assert client.delete(f'/api/users/{target}').status_code==200
    assert client.get('/api/me',headers={'cookie':'hys_session='+second_cookie}).status_code==401
    assert client.post('/api/login',json={'username':'emre.updated','password':'NewPassword123!'}).status_code==401
    assert target not in [u['id'] for u in client.get('/api/users').json()]
    assert target not in [u['id'] for u in client.get('/api/quick-replies/users').json()]
    with Session() as db:
        assert not db.get(User,target).active
        assert db.scalar(select(QuickReply).where(QuickReply.owner_id==target)).body=='Saved'
        assert db.scalar(select(Message).where(Message.body=='Historical message')) is not None
        assert db.scalar(select(LoginSession).where(LoginSession.user_id==target)) is None

def test_account_lifecycle_is_admin_only_and_protects_admins(client):
    client.post('/api/users',json={'username':'support.secure','password':'Password123!','role':'operator'})
    users=client.get('/api/users').json();admin_id=next(u['id'] for u in users if u['role']=='admin');target=next(u['id'] for u in users if u['username']=='support.secure')
    assert client.delete(f'/api/users/{admin_id}').status_code==403
    assert client.put(f'/api/users/{admin_id}',json={'username':'admin2','display_name':'New'}).status_code==403
    assert client.post(f'/api/users/{admin_id}/password',json={'password':'ChangedPassword123!'}).status_code==403
    client.post('/api/login',json={'username':'support.secure','password':'Password123!'})
    assert client.delete(f'/api/users/{target}').status_code==403
    assert client.put(f'/api/users/{target}',json={'username':'other','display_name':'Other'}).status_code==403
    assert client.post(f'/api/users/{target}/password',json={'password':'ChangedPassword123!'}).status_code==403
