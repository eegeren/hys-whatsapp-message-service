"""Isolated database + mocked Meta only. Never send real WhatsApp messages."""
import json
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from app.core import Session, Contact, Template, Campaign, Message, SystemValue, settings
from app.messaging import DirectMessage
from app.template_components import build_template
from app.worker import process_one, finalize
from tests.test_bulk_friendly import permit, upload, fake_live
from tests.test_template_components import template_id

PNG=b'\x89PNG\r\n\x1a\nmock-image'

def carousel(kind='IMAGE'):
    return [{'type':'BODY','text':'HYS {{1}}'}, {'type':'CAROUSEL','cards':[
        {'components':[{'type':'HEADER','format':kind},
                       {'type':'BODY','text':'Kart {{1}}'},
                       {'type':'BUTTONS','buttons':[{'type':'URL','text':'İncele','url':'https://example.com/{{1}}'}]}]}
        for _ in range(2)]}]

def fields():
    return {'variables':{'1':'Personel'},'cards':[
        {'variables':{'1':str(i+1)},'button_variables':{'0':f'card-{i+1}'}} for i in range(2)]}

def draft(client,monkeypatch,tmp_path,staff=False):
    monkeypatch.setattr('app.bulk.MEDIA_DIR',tmp_path)
    if staff:
        with Session() as db:
            db.add(Contact(kind='staff',phone='+905321234567',first_name='Mock personel',consent='verified',scope='staff',
                           source='Mock İK',evidence='Mock izin',consent_date='2026-01-01',legal_basis='Mock personel izni'))
            db.commit()
        r=client.post('/api/bulk/preview',data={'recipient_kind':'staff'},files={'file':('staff.csv',b'Telefon\n05321234567\n','text/csv')})
        assert r.status_code==200,r.text
        preview=r.json()
    else:
        assert permit(client).status_code==200
        preview=upload(client)
    tid=template_id(carousel(),body='HYS {{1}}')
    with Session() as db:db.get(Template,tid).meta_id='carousel-777';db.commit()
    payload={'token':preview['token'],'template_id':tid,**fields()}
    r=client.post('/api/bulk/campaign-with-carousel',data={'data':json.dumps(payload),'card_indexes':'[0,1]'},
                  files=[('files',('one.png',PNG,'image/png')),('files',('two.png',PNG+b'2','image/png'))])
    assert r.status_code==200,r.text
    return r.json()['campaign']['id'],payload

def test_card_parameter_order_language_and_links():
    tid=template_id(carousel(),body='HYS {{1}}',language='tr')
    data=fields()
    for i,c in enumerate(data['cards']):c['header_media']={'link':f'https://example.com/{i}.png'}
    with Session() as db:result,preview,kind=build_template(db.get(Template,tid),DirectMessage(**data))
    assert result['language']=={'code':'tr'} and kind=='carousel'
    cards=result['components'][1]['cards']
    assert [c['card_index'] for c in cards]==[0,1]
    assert cards[1]['components'][0]['parameters'][0]['image']['link']=='https://example.com/1.png'
    assert cards[1]['components'][1]['parameters'][0]['text']=='2'
    assert cards[1]['components'][2]['parameters'][0]['text']=='card-2'
    assert 'Kart 2' in preview

def test_bulk_uploads_only_on_confirmation_and_one_message_per_recipient(client,monkeypatch,tmp_path):
    uploads=[]
    monkeypatch.setattr('app.bulk.upload_media',lambda *a:uploads.append(a) or f'media-{len(uploads)}')
    cid,_=draft(client,monkeypatch,tmp_path)
    assert not uploads
    with Session() as db:assert db.scalar(select(Message.id)) is None
    calls=fake_live(monkeypatch)
    assert client.post(f'/api/bulk/campaign/{cid}/start',json={'confirmed':False}).status_code==422
    r=client.post(f'/api/bulk/campaign/{cid}/start',json={'confirmed':True})
    assert r.status_code==200,r.text
    assert r.json()['queued']==2 and len(uploads)==2
    with Session() as db:ids=list(db.scalars(select(Message.id)))
    for mid in ids:process_one(mid);process_one(mid)
    assert len(calls)==2
    for call in calls:
        cards=call['template']['components'][1]['cards']
        assert [c['components'][0]['parameters'][0]['image']['id'] for c in cards]==['media-1','media-2']
    assert client.post(f'/api/bulk/campaign/{cid}/start',json={'confirmed':True}).status_code==409
    assert list(tmp_path.iterdir())==[]

def test_interrupted_upload_reuses_saved_card_and_never_enqueues_partial(client,monkeypatch,tmp_path):
    cid,_=draft(client,monkeypatch,tmp_path);calls=fake_live(monkeypatch);uploads=[]
    def media(*a):
        uploads.append(a)
        if len(uploads)==2:raise HTTPException(502,{'code':131053,'message':'Mock medya hatası'})
        return f'media-{len(uploads)}'
    monkeypatch.setattr('app.bulk.upload_media',media)
    assert client.post(f'/api/bulk/campaign/{cid}/start',json={'confirmed':True}).status_code==502
    with Session() as db:
        assert db.scalar(select(Message.id)) is None
        assert db.get(Campaign,cid).status=='draft'
    assert not calls
    assert client.post(f'/api/bulk/campaign/{cid}/start',json={'confirmed':True}).status_code==200
    assert len(uploads)==3  # First card was persisted, not uploaded twice.

def test_dry_run_never_uploads_and_personel_never_bypasses_two_admins(client,monkeypatch,tmp_path):
    cid,_=draft(client,monkeypatch,tmp_path,staff=True)
    monkeypatch.setattr('app.bulk.upload_media',lambda *a:pytest.fail('No upload without approval'))
    fake_live(monkeypatch)
    assert client.post(f'/api/bulk/campaign/{cid}/start',json={'confirmed':True}).status_code==403
    assert client.post(f'/api/campaigns/{cid}/approve').status_code==200
    assert client.post(f'/api/campaigns/{cid}/confirm').status_code==403
    monkeypatch.setattr(settings,'dry_run',True)
    assert client.post(f'/api/bulk/campaign/{cid}/start',json={'confirmed':True}).status_code==200
    with Session() as db:assert json.loads(db.get(SystemValue,f'bulk_config:{cid}').value)['single_approval'] is False

@pytest.mark.parametrize('indexes',['[0,0]','[0,2]','[true,1]','{}'])
def test_invalid_card_mapping_cannot_create_draft(client,monkeypatch,tmp_path,indexes):
    cid,payload=draft(client,monkeypatch,tmp_path)
    r=client.post('/api/bulk/campaign-with-carousel',data={'data':json.dumps(payload),'card_indexes':indexes},
                  files=[('files',('one.png',PNG,'image/png')),('files',('two.png',PNG,'image/png'))])
    assert r.status_code==422
    with Session() as db:assert len(list(db.scalars(select(Campaign.id))))==1

def test_staff_matching_excludes_missing_permission_and_cross_kind_optout(client):
    with Session() as db:
        db.add(Contact(kind='staff',phone='+905321234567',first_name='Mock',consent='verified',scope='staff',source='İK',evidence='İzin',consent_date='2026-01-01',legal_basis='İzin'))
        db.add(Contact(kind='customer',phone='+905321234567',first_name='Mock ret',opted_out=True))
        db.commit()
    r=client.post('/api/bulk/preview',data={'recipient_kind':'staff'},files={'file':('staff.csv',b'Telefon\n05321234567\n05331234567\n','text/csv')})
    assert r.status_code==200 and r.json()['eligible_count']==0 and r.json()['excluded_count']==2

def test_staff_confirmed_by_distinct_admins_sends_one_mock_carousel(client,monkeypatch,tmp_path):
    cid,_=draft(client,monkeypatch,tmp_path,staff=True);calls=fake_live(monkeypatch)
    monkeypatch.setattr('app.bulk.upload_media',lambda *a:'mock-media')
    assert client.post('/api/users',json={'username':'second-admin','password':'TestPassword123!','role':'admin'}).status_code==200
    assert client.post(f'/api/campaigns/{cid}/approve').status_code==200
    assert client.post('/api/login',json={'username':'second-admin','password':'TestPassword123!'}).status_code==200
    assert client.post(f'/api/campaigns/{cid}/confirm').status_code==200
    r=client.post(f'/api/bulk/campaign/{cid}/start',json={'confirmed':True})
    assert r.status_code==200,r.text
    with Session() as db:
        c=db.get(Campaign,cid);assert c.first_approval!=c.second_approval
        mid=db.scalar(select(Message.id))
    process_one(mid);process_one(mid)
    assert len(calls)==1 and calls[0]['template']['components'][1]['type']=='carousel'

def test_cancel_during_first_card_stops_remaining_upload_and_queue(client,monkeypatch,tmp_path):
    cid,_=draft(client,monkeypatch,tmp_path);fake_live(monkeypatch);uploads=[]
    def cancel(*args):
        uploads.append(args)
        assert client.post(f'/api/campaigns/{cid}/cancel').status_code==200
        return 'mock-media'
    monkeypatch.setattr('app.bulk.upload_media',cancel)
    assert client.post(f'/api/bulk/campaign/{cid}/start',json={'confirmed':True}).status_code==409
    assert len(uploads)==1
    with Session() as db:
        assert db.get(Campaign,cid).status=='cancelled'
        assert db.scalar(select(Message.id)) is None
