"""Operations permission boundaries and reports. Meta is never called."""
import json
from datetime import datetime,timedelta
import pytest
from sqlalchemy import select,func,insert,delete
from app.core import Session,Message,User,Store,Contact,ConversationOps,InternalNote,OperationEvent,OperatorScope,now
from app.operations_access import key_for

A='+905321111111';B='+905322222222';C='+905323333333'

def seed(client):
    for name in ['alpha','beta']:
        r=client.post('/api/users',json={'username':name,'display_name':name.title(),'password':'TestPassword123!','role':'operator'});assert r.status_code==200,r.text
    with Session() as db:
        users={u.username:u.id for u in db.scalars(select(User))}
        sa=Store(name='Bir',city='İstanbul');sb=Store(name='İki',city='Ankara');db.add_all([sa,sb]);db.flush()
        db.add_all([Contact(kind='customer',phone=A,first_name='Bir müşteri',store='Bir'),Contact(kind='customer',phone=B,first_name='İki müşteri',store='İki')])
        # Core insert deliberately represents historical messages without new metadata.
        db.execute(insert(Message),[{'phone':p,'body':'Eski içerik','direction':'in','status':'received','created':now(),'unread':True} for p in [A,B,C]])
        db.commit();return users,sa.id,sb.id

def login(client,name):
    client.post('/api/logout');assert client.post('/api/login',json={'username':name,'password':'TestPassword123!'}).status_code==200

def detail(client,p=A):return client.get('/api/operations/conversations/'+key_for(p))
def edit(client,p=A,**values):
    d=detail(client,p);assert d.status_code==200,d.text
    return client.patch('/api/operations/conversations/'+key_for(p),json={'version':d.json()['version'],**values})

def test_legacy_read_does_not_backfill_or_modify_messages(client):
    seed(client)
    d=detail(client).json();assert d['status'] is None and d['assignee_id'] is None and d['message_count']==1
    assert d['customer_name']=='Bir müşteri' and d['conversation_count']==1
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(ConversationOps))==0
        assert all(m.sender_user_id is None and m.body=='Eski içerik' for m in db.scalars(select(Message)))
    assert len(client.get('/api/conversations').json())==3

def test_assignment_transfer_version_and_history(client):
    u,_,_=seed(client);login(client,'alpha')
    assert edit(client,assignee_id=u['beta']).status_code==403
    r=edit(client,assignee_id=u['alpha'],status='in_progress');assert r.status_code==200,r.text
    version=r.json()['version']
    assert client.patch('/api/operations/conversations/'+key_for(A),json={'version':version-1,'status':'resolved'}).status_code==409
    assert edit(client,status='invalid').status_code==422
    assert edit(client,assignee_id=u['beta']).status_code==200
    assert edit(client,status='resolved').status_code==403
    assert client.post('/api/conversations/send',json={'phone':A,'body':'must not send'}).status_code==403
    login(client,'beta');assert edit(client,status='resolved').status_code==200
    history=detail(client).json()['history'];assert any(e['action']=='assignment' for e in history)
    login(client,'admin');assert edit(client,assignee_id=None).status_code==200

def test_internal_notes_are_never_messages_or_meta_payloads(client,monkeypatch):
    import app.messaging as messaging
    monkeypatch.setattr(messaging,'graph',lambda *a,**kw:pytest.fail('No Meta calls permitted'))
    u,_,_=seed(client);edit(client,assignee_id=u['alpha'])
    login(client,'alpha');r=client.post('/api/operations/conversations/'+key_for(A)+'/notes',json={'body':'SECRET internal note'});assert r.status_code==201,r.text
    note=r.json()['id'];assert detail(client).json()['notes'][0]['author']=='Alpha'
    login(client,'beta');assert detail(client).json()['notes']==[]
    assert client.post('/api/operations/conversations/'+key_for(A)+'/notes',json={'body':'denied'}).status_code==403
    assert client.delete('/api/operations/notes/'+str(note)).status_code==403
    login(client,'admin');assert client.delete('/api/operations/notes/'+str(note)).status_code==200
    assert detail(client).json()['notes']==[]
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(Message))==3
        assert db.get(InternalNote,note).deleted
        events=db.scalars(select(OperationEvent)).all();assert 'SECRET' not in str([(e.old_value,e.new_value) for e in events])

@pytest.mark.parametrize('include_unassigned',[False,True])
def test_store_isolation_every_customer_entry_point(client,include_unassigned):
    u,sa,sb=seed(client)
    assert client.put('/api/operations/access/'+str(u['alpha']),json={'store_ids':[sa],'include_unassigned':include_unassigned}).status_code==200
    login(client,'alpha')
    rows=client.get('/api/conversations').json();assert {r['phone'] for r in rows}==({A,C} if include_unassigned else {A})
    assert {m['phone'][-4:] for m in client.get('/api/messages').json()['items']}==({'1111','3333'} if include_unassigned else {'1111'})
    assert detail(client,B).status_code==403
    assert client.get('/api/conversations/'+key_for(B)).status_code in (403,404)
    assert client.get('/api/conversations/eligibility',params={'phone_number':B}).status_code==403
    assert client.post('/api/conversations/open',json={'phone':B}).status_code==403
    assert client.post('/api/conversations/send',json={'phone':B,'body':'no'}).status_code==403
    assert client.post('/api/conversations/send-with-media',data={'data':json.dumps({'phone':B,'body':'no'})}).status_code==403
    with Session() as db:mid=db.scalar(select(Message.id).where(Message.phone==B))
    assert client.post(f'/api/messages/{mid}/read').status_code==403
    assert client.post(f'/api/messages/{mid}/reply',json={'body':'no'}).status_code==403
    assert client.get(f'/api/messages/{mid}/media').status_code==403
    assert edit(client,store_id=sb).status_code==403
    assert client.get('/api/operations/audit').status_code==403
    assert client.get('/api/operations/access').status_code==403
    assert client.get('/api/operations/reports').status_code==403
    assert client.get('/api/campaigns').status_code==403
    assert client.get('/api/dashboard').status_code==200
    assert [s['id'] for s in client.get('/api/stores').json()]==[sa]
    login(client,'admin');assert len(client.get('/api/conversations').json())==3


def test_customer_override_and_target_store_permission(client):
    u,sa,sb=seed(client)
    client.put('/api/operations/access/'+str(u['beta']),json={'store_ids':[sb]})
    assert edit(client,assignee_id=u['beta']).status_code==422
    r=edit(client,store_id=sb,assignee_id=u['beta'],customer_name='Yeni isim',tags=['VIP','VIP',' teslimat ']);assert r.status_code==200,r.text
    assert r.json()['tags']==['VIP','teslimat']
    with Session() as db:assert db.scalar(select(Contact).where(Contact.phone==A)).first_name=='Bir müşteri'
    login(client,'beta');assert detail(client).status_code==200
    assert edit(client,store_id=None).status_code==403
    login(client,'admin');assert edit(client,store_id=None,assignee_id=None).status_code==200
    login(client,'beta');assert detail(client).status_code==403


def test_auto_reopen_observer_default_off_preserves_owner_and_history(client):
    u,_,_=seed(client);edit(client,assignee_id=u['alpha'],status='resolved')
    def incoming(p):
        with Session() as db:db.add(Message(phone=p,body='new event',direction='in',status='received'));db.commit()
    incoming(A);assert detail(client).json()['status']=='resolved'
    assert client.put('/api/operations/config',json={'auto_reopen':True}).status_code==200
    incoming(A);d=detail(client).json();assert d['status']=='new' and d['assignee_id']==u['alpha']
    assert any(h['action']=='auto_reopen' for h in d['history'])
    incoming('+905324444444');assert detail(client,'+905324444444').json()['status']=='new'
    incoming(B);assert detail(client,B).json()['status'] is None


def test_observer_attribution_is_request_actor_not_owner_and_ignores_bulk(client):
    u,sa,_=seed(client);edit(client,assignee_id=u['beta'])
    with Session() as db:
        db.info.update(ops_actor_id=u['alpha'],ops_store_id=sa)
        m=Message(phone=A,body='accepted',direction='out',status='accepted');db.add(m);db.commit()
        assert m.sender_user_id==u['alpha'] and m.operation_store_id==sa
    with Session() as db:
        m=Message(phone=A,body='unattributed legacy',direction='out',status='accepted');db.add(m);db.commit();assert m.sender_user_id is None


def test_reports_real_timestamps_no_guessing_and_transfer_attribution(client):
    u,sa,_=seed(client)
    t=datetime(2026,10,15,8)
    with Session() as db:
        db.execute(delete(Message));db.execute(delete(ConversationOps))
        rows=[(0,'in',None,'received'),(2,'in',None,'received'),(5,'out',u['alpha'],'accepted'),(10,'in',None,'received'),(14,'out',u['beta'],'delivered'),(15,'out',None,'accepted'),(16,'out',u['alpha'],'failed')]
        db.execute(insert(Message),[{'phone':A,'body':'test','direction':direction,'status':status,'sender_user_id':sender,'operation_store_id':sa,'created':t+timedelta(minutes=minute),'unread':False} for minute,direction,sender,status in rows])
        db.add(ConversationOps(key=key_for(A),phone=A,assignee_id=u['beta'],store_id=sa,store_linked=True,status='in_progress'))
        db.add(OperationEvent(actor_id=u['alpha'],action='status',conversation_key=key_for(A),store_id=sa,old_value='{}',new_value='{"status":"resolved"}',created=t+timedelta(minutes=20)))
        db.add(OperationEvent(actor_id=u['admin'],action='assignment',conversation_key=key_for(A),store_id=sa,old_value='{}',new_value=json.dumps({'assignee_id':u['beta']}),created=t))
        db.commit()
    r=client.get('/api/operations/reports?start=2026-10-15&end=2026-10-15').json();people={p['id']:p for p in r['people']};a=people[u['alpha']];b=people[u['beta']]
    assert a['sent_messages']==1 and b['sent_messages']==1
    assert a['first_response_seconds']==300 and a['average_response_seconds']==180
    assert b['first_response_seconds'] is None and b['average_response_seconds']==240
    assert a['resolved_conversations']==1 and b['open_conversations']==1 and b['assigned_conversations']==1
    assert r['legacy_unattributed_messages']==1
    assert client.get('/api/operations/reports?start=bad').status_code==422
    assert client.get('/api/operations/reports?start=2025-01-01&end=2026-10-15').status_code==422
    filtered=client.get(f'/api/operations/reports?start=2026-10-15&end=2026-10-15&person_id={u["alpha"]}&store_id={sa}').json();assert len(filtered['people'])==1 and len(filtered['stores'])==1


def test_audit_admin_only_and_values_exclude_sensitive_bodies(client):
    u,sa,_=seed(client);edit(client,assignee_id=u['alpha'],status='waiting_customer',customer_name='Sensitive customer',tags=['secret tag'])
    r=client.get('/api/operations/audit').json();assert r['total']>=3
    text=json.dumps(r);assert 'Sensitive customer' not in text and 'secret tag' not in text and 'TestPassword' not in text
    login(client,'alpha');assert client.get('/api/operations/audit').status_code==403
    assert client.put('/api/operations/config',json={'auto_reopen':True}).status_code==403


def test_upgrade_007_to_008_preserves_existing_rows_and_nullable_attribution(tmp_path):
    import os,subprocess,sys
    from pathlib import Path
    from sqlalchemy import create_engine,text,inspect
    url='sqlite:///'+str(tmp_path/'operations-migration.db');env={**os.environ,'DATABASE_URL':url}
    cwd=Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable,'-m','alembic','upgrade','007'],cwd=cwd,env=env,check=True,capture_output=True)
    engine=create_engine(url)
    with engine.begin() as conn:
        conn.execute(insert(User.__table__).values(id=1,username='legacy',password='hash',role='admin'))
        conn.execute(insert(Store.__table__).values(id=1,name='Legacy store',city='İstanbul'))
        conn.execute(insert(Contact.__table__).values(id=1,kind='customer',phone=A,first_name='Legacy customer',store='Legacy store'))
        conn.execute(insert(Message.__table__).values(id=1,phone=A,body='Original incoming message',direction='in',status='received'))
    subprocess.run([sys.executable,'-m','alembic','upgrade','head'],cwd=cwd,env=env,check=True,capture_output=True)
    with engine.connect() as conn:
        assert conn.execute(text('SELECT body FROM messages WHERE id=1')).scalar()=='Original incoming message'
        assert conn.execute(text('SELECT username FROM users WHERE id=1')).scalar()=='legacy'
        assert conn.execute(text('SELECT first_name FROM contacts WHERE id=1')).scalar()=='Legacy customer'
        assert conn.execute(text('SELECT sender_user_id,operation_store_id FROM messages WHERE id=1')).one()==(None,None)
        assert conn.execute(text('SELECT COUNT(*) FROM conversation_ops')).scalar()==0
        assert conn.execute(text('SELECT version_num FROM alembic_version')).scalar()=='008'
    cols={c['name']:c for c in inspect(engine).get_columns('messages')};assert cols['sender_user_id']['nullable'] and cols['operation_store_id']['nullable']
    engine.dispose()


def test_mock_direct_send_uses_session_actor_without_altering_payload(client,monkeypatch):
    from app.core import settings
    import app.messaging as messaging
    u,sa,_=seed(client);edit(client,assignee_id=u['alpha']);login(client,'alpha')
    payloads=[]
    def fake_graph(method,path,payload=None,**kw):
        payloads.append(payload);return {'messages':[{'id':'wamid.operations.mock'}]}
    monkeypatch.setattr(messaging,'graph',fake_graph);monkeypatch.setattr(messaging,'connection_ok',lambda db:True)
    monkeypatch.setattr(settings,'dry_run',False);monkeypatch.setattr(settings,'live_send_enabled',True)
    r=client.post('/api/conversations/send',json={'conversation_key':key_for(A),'body':'Mock reply'});assert r.status_code==200,r.text
    assert payloads[0]['type']=='text' and payloads[0]['text']['body']=='Mock reply'
    assert 'sender_user_id' not in payloads[0] and 'operation_store_id' not in payloads[0]
    with Session() as db:
        m=db.scalar(select(Message).where(Message.meta_id=='wamid.operations.mock'));assert m.sender_user_id==u['alpha'] and m.operation_store_id==sa


def test_postgres_migration_sql_is_additive_and_compiles_without_database():
    import os,subprocess,sys
    from pathlib import Path
    env={**os.environ,'DATABASE_URL':'postgresql+psycopg://offline:offline@127.0.0.1/offline'}
    r=subprocess.run([sys.executable,'-m','alembic','upgrade','007:008','--sql'],cwd=Path(__file__).resolve().parents[1],env=env,check=True,capture_output=True,text=True)
    sql=r.stdout.upper()
    assert 'CREATE TABLE CONVERSATION_OPS' in sql and 'ALTER TABLE MESSAGES ADD COLUMN SENDER_USER_ID' in sql
    assert 'DROP TABLE' not in sql and 'DELETE FROM MESSAGES' not in sql


def test_signed_webhook_reopens_once_without_assigning_or_sending(client,monkeypatch):
    from tests.test_webhook_production import post,envelope,message
    import app.messaging as messaging
    monkeypatch.setattr(messaging,'graph',lambda *a,**kw:pytest.fail('Webhook must never send'))
    u,_,_=seed(client);edit(client,assignee_id=u['alpha'],status='resolved')
    client.put('/api/operations/config',json={'auto_reopen':True})
    event=message('wamid.operations.signed');event['from']=A.lstrip('+');event['timestamp']=str(int(now().timestamp()))
    for _ in range(2):assert post(client,envelope([event])).status_code==200
    d=detail(client).json();assert d['status']=='new' and d['assignee_id']==u['alpha']
    assert len([e for e in d['history'] if e['action']=='auto_reopen'])==1
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(Message).where(Message.meta_id=='wamid.operations.signed'))==1
        assert db.scalar(select(func.count()).select_from(Message).where(Message.direction=='out'))==0


def test_proactive_message_is_not_counted_as_customer_reply(client):
    u,sa,_=seed(client);t=datetime(2026,10,15,8)
    with Session() as db:
        db.execute(delete(Message))
        rows=[(0,'out','accepted'),(5,'in','received'),(8,'out','accepted')]
        db.execute(insert(Message),[{'phone':A,'body':'test','direction':direction,'status':status,'sender_user_id':u['alpha'] if direction=='out' else None,'operation_store_id':sa,'created':t+timedelta(minutes=minute),'unread':False} for minute,direction,status in rows]);db.commit()
    r=client.get(f'/api/operations/reports?start=2026-10-15&end=2026-10-15&person_id={u["alpha"]}').json()['people'][0]
    assert r['sent_messages']==2 and r['answered_conversations']==1
    assert r['first_response_seconds']==180 and r['average_response_seconds']==180


def test_stale_metadata_key_cannot_bypass_phone_fallback_store_guard(client,monkeypatch):
    import app.messaging as messaging
    monkeypatch.setattr(messaging,'graph',lambda *a,**kw:pytest.fail('No cross-store send'))
    u,sa,_=seed(client)
    edit(client,store_id=sa)
    with Session() as db:db.execute(delete(Message).where(Message.phone==A));db.commit()
    client.put('/api/operations/access/'+str(u['alpha']),json={'store_ids':[sa]});login(client,'alpha')
    assert client.post('/api/conversations/send',json={'conversation_key':key_for(A),'phone':B,'body':'denied'}).status_code==403


def test_other_assignee_eligibility_does_not_offer_send(client):
    u,_,_=seed(client);edit(client,assignee_id=u['beta']);login(client,'alpha')
    r=client.get('/api/conversations/eligibility',params={'phone_number':A});assert r.status_code==200
    assert not r.json()['allowed'] and not r.json()['template_allowed'] and not r.json()['text_allowed']
    assert 'başka personele' in r.json()['blocked_reason']
