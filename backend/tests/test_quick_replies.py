from datetime import timedelta
import pytest
from sqlalchemy import select
from app.core import Session,User,QuickReply,Message,now,settings
from app.quick_replies import DEFAULT_REPLIES

def create(client,**changes):return client.post('/api/quick-replies',json={'title':'Karşılama','category':'Genel','body':'Merhaba {{personel_adi}}','sort_order':0,'category_order':0,**changes})
def operator(client,name='operator'):
    assert client.post('/api/users',json={'username':name,'password':'TestPassword123!','role':'operator'}).status_code==200
    with Session() as db:return db.scalar(select(User.id).where(User.username==name))
def login(client,name):assert client.post('/api/login',json={'username':name,'password':'TestPassword123!'}).status_code==200

def test_profile_and_dynamic_name_follow_current_user(client):
    assert client.patch('/api/profile',json={'display_name':'Ayşe Yılmaz'}).status_code==200
    assert client.get('/api/me').json()['display_name']=='Ayşe Yılmaz'
    row=create(client).json();assert row['rendered_body']=='Merhaba Ayşe'
    client.patch('/api/profile',json={'display_name':'Ege'})
    assert client.get('/api/quick-replies').json()[0]['rendered_body']=='Merhaba Ege'
    login(client,'admin');assert client.get('/api/me').json()['display_name']=='Ege'
    with Session() as db:assert db.get(QuickReply,row['id']).body=='Merhaba {{personel_adi}}'

def test_scope_privacy_and_admin_permissions(client):
    first=operator(client);second=operator(client,'operator2')
    common=create(client,title='Ortak').json();private=create(client,title='Özel',owner_id=first).json();other=create(client,title='Diğer',owner_id=second).json()
    assert len(client.get('/api/quick-replies?manage=true').json())==3
    assert len(client.get('/api/quick-replies').json())==1
    login(client,'operator')
    assert {r['id'] for r in client.get('/api/quick-replies').json()}=={common['id'],private['id']}
    for path in ['/api/quick-replies?manage=true','/api/quick-replies/users']:assert client.get(path).status_code==403
    assert create(client).status_code==403
    assert client.put('/api/quick-replies/'+str(other['id']),json={'title':'X','category':'X','body':'X'}).status_code==403
    assert client.delete('/api/quick-replies/'+str(other['id'])).status_code==403
    assert client.post('/api/quick-replies/reorder',json={'ids':[common['id']]}).status_code==403
    client.patch('/api/profile',json={'display_name':'Operatör Bir'})
    assert client.get('/api/quick-replies').json()[0]['rendered_body']=='Merhaba Operatör'

@pytest.mark.parametrize('body',['{{musteri_adi}}','{{personel_adi }}','{{personel_adi','Hello }}',' ','{{personel_adi}}'*50])
def test_invalid_variables_rejected(client,body):assert create(client,body=body).status_code==422
@pytest.mark.parametrize('name',[' ','{{personel_adi}}','Ad\nSoyad'])
def test_bad_profile_name(client,name):assert client.patch('/api/profile',json={'display_name':name}).status_code==422

def test_edit_category_reorder_delete_persistence(client):
    a=create(client,title='A').json();b=create(client,title='B',sort_order=1).json()
    assert client.post('/api/quick-replies/reorder',json={'ids':[b['id'],a['id']]}).status_code==200
    assert [r['title'] for r in client.get('/api/quick-replies').json()]==['B','A']
    assert client.post('/api/quick-replies/reorder',json={'ids':[a['id'],a['id']]}).status_code==422
    assert client.post('/api/quick-replies/reorder',json={'ids':[a['id'],99999]}).status_code==409
    assert client.put('/api/quick-replies/'+str(a['id']),json={'title':'Güncel','category':'Yeni kategori','body':'İyi günler','category_order':2,'sort_order':5}).status_code==200
    with Session() as db:
        row=db.get(QuickReply,a['id']);assert row.category=='Yeni kategori' and row.body=='İyi günler'
    assert client.delete('/api/quick-replies/'+str(b['id'])).status_code==200
    assert len(client.get('/api/quick-replies').json())==1
    assert create(client,owner_id=99999).status_code==422

def test_defaults_do_not_send_or_use_meta_templates(client,monkeypatch):
    monkeypatch.setattr('app.messaging.graph',lambda *a,**k:pytest.fail('No real Meta calls'))
    for title,body in DEFAULT_REPLIES:assert create(client,title=title,category=title,body=body).status_code==201
    assert len(client.get('/api/quick-replies').json())==6
    with Session() as db:assert db.scalar(select(Message.id)) is None

def test_closed_window_guard_still_applies(client,monkeypatch):
    monkeypatch.setattr(settings,'dry_run',False);monkeypatch.setattr(settings,'live_send_enabled',True)
    monkeypatch.setattr('app.messaging.connection_ok',lambda db:True)
    monkeypatch.setattr('app.messaging.graph',lambda *a,**k:pytest.fail('Closed window must not call Meta'))
    row=create(client).json()
    with Session() as db:db.add(Message(phone='+905550000001',body='Merhaba',direction='in',created=now()-timedelta(hours=25)));db.commit()
    result=client.post('/api/conversations/send',json={'phone':'+905550000001','body':row['rendered_body']})
    assert result.status_code==403 and '24 saatlik' in result.json()['detail']

def test_authentication_required(client):
    client.cookies.clear();assert client.get('/api/quick-replies').status_code==401
    assert client.patch('/api/profile',json={'display_name':'Someone'}).status_code==401

def test_category_order_moves_entire_category_including_private_replies(client):
    person=operator(client)
    a=create(client,title='Ortak',category='Destek',category_order=3).json()
    b=create(client,title='Kişisel',category='Destek',owner_id=person,category_order=3).json()
    assert client.put('/api/quick-replies/'+str(a['id']),json={'title':'Ortak','category':'Destek','body':'Merhaba','category_order':7}).status_code==200
    rows=client.get('/api/quick-replies?manage=true').json()
    assert {r['category_order'] for r in rows}=={7}
