"""Compatibility checks for SQL inbox summaries; no real Meta calls."""
from datetime import timedelta
from sqlalchemy import event,select
from app.core import Session,Message,now
from app.messaging import conversation_key


def test_sql_summary_matches_previous_window_and_tie_order(client):
    timestamp=now()
    with Session() as db:
        # More than the legacy window, mixed directions, identical timestamps,
        # and IDs which are not chronological by created time.
        db.execute(Message.__table__.insert(),[
            {'phone':f'+90555000{i%7:04d}','body':str(i),'direction':'in' if i%3 else 'out',
             'status':'received' if i%3 else 'read','unread':i%2==0,
             'created':timestamp-timedelta(seconds=i//5)} for i in range(10020)])
        db.commit()
        expected={}
        for m in db.scalars(select(Message).order_by(Message.created.desc(),Message.id.desc()).limit(10000)):
            row=expected.setdefault(m.phone,{'key':conversation_key(m.phone),'phone':m.phone,'last_body':m.body,'last_direction':m.direction,'last_status':m.status,'last_at':m.created.isoformat(),'unread':0,'last_incoming_id':0})
            if m.direction=='in':row['last_incoming_id']=max(row['last_incoming_id'],m.id)
            if m.direction=='in' and m.unread:row['unread']+=1
    loaded=[]
    def on_load(target,context):loaded.append(target.id)
    event.listen(Message,'load',on_load)
    try:
        result=client.get('/api/conversations')
        assert result.status_code==200
        actual=[{k:v for k,v in row.items() if k!='operations'} for row in result.json()]
        assert actual==list(expected.values())
        assert loaded==[] # Inbox summaries never hydrate Message ORM instances.
        key=actual[0]['key']
        detail=client.get('/api/conversations/'+key)
        assert detail.status_code==200 and len(detail.json()['items'])==100
        assert len(loaded)==100 # Only the displayed conversation page is hydrated.
    finally:event.remove(Message,'load',on_load)


def test_empty_and_outgoing_only_inbox(client):
    assert client.get('/api/conversations').json()==[]
    with Session() as db:
        db.add(Message(phone='+905550001111',direction='out',body='Only outgoing',unread=True));db.commit()
    row=client.get('/api/conversations').json()[0]
    assert row['unread']==0 and row['last_incoming_id']==0
    assert client.get('/api/conversations/'+'0'*64).status_code==404


def test_dashboard_counts_match_eligibility_without_loading_contacts(client):
    from app.core import Contact,eligible
    variants=[{}, {'active':False},{'opted_out':True},{'preference':'sms'},
              {'consent':'unverified'},{'scope':'staff'},{'source':''},{'evidence':''},{'consent_date':''},
              {'source':' '},{'evidence':' '},{'consent_date':' '},
              {'iys_status':'external_verified','source':'HYS harici satış programı','evidence':'external_marketing_export:123','consent_date':''},
              {'iys_status':'external_verified','source':'HYS harici satış programı','evidence':'externalXmarketingXexport:123'},
              {'iys_status':'external_verified','source':'Other','evidence':'external_marketing_export:123'},
              {'iys_status':'not_checked'},{'iys_status':'external_verified','evidence':''}]
    defaults=dict(kind='customer',first_name='Synthetic',active=True,opted_out=False,preference='whatsapp',consent='verified',scope='marketing',iys_status='manual_verified',source='source',evidence='evidence',consent_date='2026-01-01')
    with Session() as db:
        rows=[Contact(**{**defaults,**changes,'phone':f'+90555111{i:04d}'}) for i,changes in enumerate(variants)]
        rows.append(Contact(kind='staff',first_name='Staff',phone='+905559991111'))
        db.add_all(rows);db.commit()
        expected=sum(c.kind=='customer' and eligible(c) for c in rows)
    loaded=[]
    def on_load(target,context):loaded.append(target.id)
    event.listen(Contact,'load',on_load)
    try:
        response=client.get('/api/dashboard')
        assert response.status_code==200
        data=response.json()
        assert data['customers']==len(variants) and data['staff']==1 and data['eligible']==expected
        assert loaded==[] # Dashboard counters never fetch entire contact records.
    finally:event.remove(Contact,'load',on_load)
