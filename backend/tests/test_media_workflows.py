import json
from datetime import timedelta
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from app.core import *
from tests.test_template_components import sender,template_id
from tests.test_bulk_friendly import permit,upload,fake_live
from app.worker import process_one,finalize

PNG=b'\x89PNG\r\n\x1a\nmock-image'
MP4=b'\x00\x00\x00\x18ftypisom'+b'video'
def media_post(client,kind='IMAGE',body='',id=None,content=None):
    return client.post('/api/conversations/send-with-media',data={'data':json.dumps({'phone':'+905321234567','template_id':id,'body':body,'variables':{}})},files={'file':('photo.png' if kind=='IMAGE' else 'clip.mp4',content if content is not None else PNG if kind=='IMAGE' else MP4,'image/png' if kind=='IMAGE' else 'video/mp4')})

@pytest.mark.parametrize('kind,type',[('IMAGE','image'),('VIDEO','video')])
def test_service_media_upload_payload_and_caption(client,sender,kind,type):
    with Session() as db:db.add(Message(phone='+905321234567',body='Merhaba',direction='in',status='received',created=now()-timedelta(minutes=1)));db.commit()
    r=media_post(client,kind,'Katalog')
    assert r.status_code==200,r.text
    assert r.json()['status']=='accepted';assert r.json()['delivery_status']=='unknown'
    assert sender[0][0]=='upload';assert sender[1][1]['type']==type
    assert sender[1][1][type]=={'id':'987654321','caption':'Katalog'}

def test_service_media_requires_window_optout_and_real_file_validation(client,sender):
    assert media_post(client).status_code==403;assert sender==[]
    with Session() as db:db.add(Message(phone='+905321234567',direction='in',status='received',body='Merhaba'));db.commit()
    assert media_post(client,content=b'not-png').status_code==422;assert sender==[]
    with Session() as db:db.add(Contact(kind='customer',phone='+905321234567',first_name='',opted_out=True));db.commit()
    assert media_post(client).status_code==403;assert sender==[]

def test_first_media_requires_marketing(client,sender):
    tid=template_id([{'type':'HEADER','format':'IMAGE'},{'type':'BODY','text':'Merhaba'}])
    with Session() as db:db.get(Template,tid).category='UTILITY';db.commit()
    assert media_post(client,id=tid).status_code==403;assert sender==[]

def prepare_media(client,monkeypatch,tmp_path,kind='IMAGE'):
    monkeypatch.setattr('app.bulk.MEDIA_DIR',tmp_path)
    assert permit(client).status_code==200;p=upload(client)
    tid=template_id([{'type':'HEADER','format':kind},{'type':'BODY','text':'Merhaba {{1}}'}])
    # The body and components agree, and variables retain their Meta parameter order.
    with Session() as db:t=db.get(Template,tid);t.body='Merhaba {{1}}';t.meta_id='media-777';db.commit()
    r=client.post('/api/bulk/campaign-with-media',data={'data':json.dumps({'token':p['token'],'template_id':tid,'variables':{'1':'HYS'}})},files={'file':('image.png' if kind=='IMAGE' else 'clip.mp4',PNG if kind=='IMAGE' else MP4,'image/png' if kind=='IMAGE' else 'video/mp4')})
    assert r.status_code==200,r.text
    return r.json()['campaign']['id']

@pytest.mark.parametrize('kind,expected',[('IMAGE','image'),('VIDEO','video')])
def test_bulk_stages_without_meta_then_uploads_once_and_sends_all(client,monkeypatch,tmp_path,kind,expected):
    uploads=[]
    monkeypatch.setattr('app.bulk.upload_media',lambda *a:uploads.append(a) or '888')
    cid=prepare_media(client,monkeypatch,tmp_path,kind)
    assert uploads==[]
    with Session() as db:assert db.scalar(select(Message.id)) is None
    calls=fake_live(monkeypatch)
    assert client.post(f'/api/bulk/campaign/{cid}/start',json={'confirmed':False}).status_code==422
    assert uploads==[]
    r=client.post(f'/api/bulk/campaign/{cid}/start',json={'confirmed':True})
    assert r.status_code==200,r.text;assert r.json()['queued']==2;assert len(uploads)==1
    with Session() as db:ids=list(db.scalars(select(Message.id)))
    for mid in ids:process_one(mid)
    assert len(calls)==2
    for call in calls:
        assert call['template']['components'][0]['parameters'][0]=={'type':expected,expected:{'id':'888'}}
        assert call['template']['components'][1]['parameters'][0]['text']=='HYS'
    assert client.post(f'/api/bulk/campaign/{cid}/start',json={'confirmed':True}).status_code==409
    assert len(uploads)==1

def test_bulk_dry_run_never_uploads_and_failed_upload_never_enqueues(client,monkeypatch,tmp_path):
    def forbidden(*a):raise AssertionError('No real upload in dry run')
    monkeypatch.setattr('app.bulk.upload_media',forbidden)
    cid=prepare_media(client,monkeypatch,tmp_path)
    assert client.post(f'/api/bulk/campaign/{cid}/start',json={'confirmed':True}).status_code==200

def test_upload_failure_and_cancel_during_upload_never_enqueues(client,monkeypatch,tmp_path):
    cid=prepare_media(client,monkeypatch,tmp_path);calls=fake_live(monkeypatch)
    def failed(*a):raise HTTPException(502,{'code':131053,'message':'Medya reddedildi'})
    monkeypatch.setattr('app.bulk.upload_media',failed)
    assert client.post(f'/api/bulk/campaign/{cid}/start',json={'confirmed':True}).status_code==502
    with Session() as db:assert db.scalar(select(Message.id)) is None;assert db.get(Campaign,cid).status=='draft'
    def cancel(*a):
        assert client.post(f'/api/campaigns/{cid}/cancel').status_code==200
        return '888'
    monkeypatch.setattr('app.bulk.upload_media',cancel)
    assert client.post(f'/api/bulk/campaign/{cid}/start',json={'confirmed':True}).status_code==409
    with Session() as db:assert db.scalar(select(Message.id)) is None;assert db.get(Campaign,cid).status=='cancelled'
    assert calls==[]

def test_sample_and_bulk_reuse_one_uploaded_media(client,monkeypatch,tmp_path):
    cid=prepare_media(client,monkeypatch,tmp_path);calls=fake_live(monkeypatch);uploads=[]
    monkeypatch.setattr('app.bulk.upload_media',lambda *a:uploads.append(a) or '888')
    assert client.post(f'/api/bulk/campaign/{cid}/test',json={'confirmed':True,'phone':'05321234567'}).status_code==200
    with Session() as db:mid=db.scalar(select(Message.id))
    process_one(mid);finalize()
    assert client.post(f'/api/bulk/campaign/{cid}/start',json={'confirmed':True}).json()['queued']==1
    assert len(uploads)==1
