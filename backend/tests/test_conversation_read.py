from sqlalchemy import select
from app.core import Session,Message
from app.messaging import conversation_key

def test_read_only_displayed_incoming_and_preserve_concurrent_arrival(client,monkeypatch):
    monkeypatch.setattr('app.messaging.graph',lambda *a,**k:(_ for _ in ()).throw(AssertionError('No Meta calls')))
    with Session() as db:
        rows=[Message(phone='+905550000001',body='A',direction='in',unread=True),Message(phone='+905550000001',body='B',direction='out',unread=True),Message(phone='+905550000002',body='C',direction='in',unread=True)]
        db.add_all(rows);db.commit();through=rows[0].id
        fresh=Message(phone='+905550000001',body='New concurrent message',direction='in',unread=True);db.add(fresh);db.commit();new_id=fresh.id
    key=conversation_key('+905550000001')
    assert client.get('/api/conversations/'+key).status_code==200
    with Session() as db:assert db.get(Message,through).unread # GET never marks read.
    result=client.post('/api/conversations/'+key+'/read',json={'through_id':through})
    assert result.status_code==200 and result.json()['unread']==1
    with Session() as db:
        assert not db.get(Message,through).unread
        assert db.get(Message,new_id).unread
        assert db.scalar(select(Message).where(Message.body=='C')).unread
        assert db.scalar(select(Message).where(Message.body=='B')).unread
    assert client.post('/api/conversations/'+key+'/read',json={'through_id':new_id}).json()['unread']==0

def test_read_rejects_other_conversation_and_requires_session(client):
    with Session() as db:
        m=Message(phone='+905550000002',body='Unread',direction='in',unread=True);db.add(m);db.commit();id=m.id
    assert client.post('/api/conversations/'+conversation_key('+905550000001')+'/read',json={'through_id':id}).status_code==404
    client.cookies.clear()
    assert client.post('/api/conversations/'+conversation_key('+905550000002')+'/read',json={'through_id':id}).status_code==401

def test_incoming_watermark_ignores_outgoing_messages(client):
    with Session() as db:
        a=Message(phone='+905550000001',body='Inbound',direction='in');b=Message(phone='+905550000001',body='Outbound',direction='out');db.add_all([a,b]);db.commit();id=a.id
    assert client.get('/api/conversations').json()[0]['last_incoming_id']==id
