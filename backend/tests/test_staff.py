import io,json,hashlib,hmac
from datetime import timedelta
from types import SimpleNamespace
import pytest
from openpyxl import Workbook
from sqlalchemy import select,func
from app.core import *
from app import staff

@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbid(*a,**k):pytest.fail('Gerçek Meta API çağrısı yasak')
    monkeypatch.setattr(staff,'graph',forbid);monkeypatch.setattr(staff,'upload_media',forbid)
    monkeypatch.setattr(settings,'staff_dispatch_enabled',False)

@pytest.fixture
def prepared(client,monkeypatch):
    with Session() as db:
        db.add_all([Contact(kind='staff',first_name='Ali',phone='+905321234567',store='A'),Contact(kind='staff',first_name='Ayşe',phone='+905321234568',store='B'),Contact(kind='customer',first_name='Müşteri',phone='+905321234569')])
        doc=Template(name='hys_personel_belge',body='Personel duyurusu ektedir.',status='APPROVED',category='UTILITY',components=json.dumps([{'type':'HEADER','format':'DOCUMENT'},{'type':'BODY','text':'Personel duyurusu ektedir.'}]))
        video=Template(name='hys_personel_video',body='Personel videosu ektedir.',status='APPROVED',category='UTILITY',components=json.dumps([{'type':'HEADER','format':'VIDEO'},{'type':'BODY','text':'Personel videosu ektedir.'}]))
        db.add_all([doc,video]);db.commit();templates=(doc.id,video.id)
    a=client.post('/api/staff/announcements',json={'name':'Test'}).json()['id'];base=f'/api/staff/announcements/{a}'
    assert client.post(base+'/assets',files={'file':('duyuru.pdf',b'%PDF-1.7 test','application/pdf')}).status_code==200
    for i in range(2):
        with Session() as db:
            owner=db.scalar(select(User.id));job=VideoJob(id=f'fixture-video-{i}',owner_id=owner,filename=f'video{i}.mp4',status='ready',ticket_hash='fake',source_size=13,output_size=13,output=b'\x00\x00\x00\x18ftypisom'+bytes([i]),expires=now()+timedelta(hours=24));db.add(job);db.commit()
        assert client.post(base+'/videos',json={'video_job_id':f'fixture-video-{i}'}).status_code==200
    return a,base,{'document_template':templates[0],'video_template':templates[1],'target':'all'}

def approve(client,prepared,live=False):
    a,base,cfg=prepared;p=client.post(base+'/preview',json=cfg)
    assert p.status_code==200,p.text
    r=client.post(base+'/send',json={'token':p.json()['token'],'confirm_live':live})
    assert r.status_code==200,r.text
    return p.json()

def live(monkeypatch):
    monkeypatch.setattr(settings,'dry_run',False);monkeypatch.setattr(settings,'live_send_enabled',True);monkeypatch.setattr(settings,'staff_dispatch_enabled',True);monkeypatch.setattr(settings,'deployment_send_lock',False)
    monkeypatch.setattr(staff,'connection_ok',lambda db:True);monkeypatch.setattr('app.worker.reserve_bulk_slot',lambda db:True)

def webhook(client,mid,status):
    payload={'entry':[{'id':settings.meta_waba_id,'changes':[{'value':{'metadata':{'phone_number_id':settings.meta_phone_number_id},'statuses':[{'id':mid,'status':status,'timestamp':'123'}]}}]}]}
    raw=json.dumps(payload).encode();sig='sha256='+hmac.new(settings.meta_app_secret.encode(),raw,hashlib.sha256).hexdigest()
    assert client.post('/api/webhook',content=raw,headers={'X-Hub-Signature-256':sig,'Content-Type':'application/json'}).status_code==200

def test_simulation_and_idempotent_approval(client,prepared):
    p=approve(client,prepared);assert p['people']==2 and p['files']==3 and p['paid_messages']==6
    assert client.post(prepared[1]+'/send',json={'token':p['token']}).json()['duplicate']
    staff.dispatch_staff(10)
    d=client.get(prepared[1]).json();assert len(d['recipients'])==2
    assert all(p['status']=='dry_run' for p in d['recipients'])
    with Session() as db:assert len(list(db.scalars(select(StaffDelivery))))==6;assert not list(db.scalars(select(Campaign)))

def test_mock_meta_upload_reuse_window_and_order(client,prepared,monkeypatch):
    live(monkeypatch);uploads=[];calls=[]
    monkeypatch.setattr(staff,'upload_media',lambda *args:uploads.append(args[0]) or str(100+len(uploads)))
    def send(*args):calls.append(args[2]);return {'messages':[{'id':f'wamid.mock{len(calls)}'}]}
    monkeypatch.setattr(staff,'graph',send)
    with Session() as db:db.add(Message(phone='+905321234567',direction='in',body='Merhaba',created=now(),status='received'));db.commit()
    p=approve(client,prepared,True);assert p['paid_messages']==3
    staff.dispatch_staff(10);assert len(calls)==2 and len(uploads)==1
    assert calls[0]['type']=='document';assert calls[1]['type']=='template'
    assert calls[1]['template']['components'][0]['parameters'][0]['document']['id']==calls[0]['document']['id']
    staff.dispatch_staff(10);assert len(calls)==2
    webhook(client,'wamid.mock1','delivered');webhook(client,'wamid.mock2','read')
    staff.dispatch_staff(10);assert len(calls)==4 and len(uploads)==2
    assert calls[2]['type']=='video';assert calls[3]['template']['components'][0]['parameters'][0]['type']=='video'
    webhook(client,'wamid.mock3','read');webhook(client,'wamid.mock4','delivered')
    staff.dispatch_staff(10);assert len(calls)==6 and len(uploads)==3
    for i in (5,6):webhook(client,f'wamid.mock{i}','read')
    staff.dispatch_staff(10)
    assert client.get(prepared[1]).json()['announcement']['status']=='completed'
    with Session() as db:assert all(f.content is None for f in db.scalars(select(StaffAsset)))

def test_pause_cancel_no_resend(client,prepared):
    approve(client,prepared)
    assert client.post(prepared[1]+'/pause',json={}).status_code==200
    staff.dispatch_staff(10);assert all(x['status']=='queued' for p in client.get(prepared[1]).json()['recipients'] for x in p['messages'])
    assert client.post(prepared[1]+'/resume',json={}).status_code==200
    assert client.post(prepared[1]+'/cancel',json={}).status_code==200
    staff.dispatch_staff(10)
    assert all(p['status']=='cancelled' for p in client.get(prepared[1]).json()['recipients'])
    with Session() as db:assert all(f.content is None for f in db.scalars(select(StaffAsset)))

def test_live_requires_panel_approval(client,prepared,monkeypatch):
    live(monkeypatch);p=client.post(prepared[1]+'/preview',json=prepared[2]).json()
    assert client.post(prepared[1]+'/send',json={'token':p['token']}).status_code==403
    with Session() as db:assert not list(db.scalars(select(StaffDelivery)))

def test_uncertain_stops_sequence(client,prepared,monkeypatch):
    live(monkeypatch);monkeypatch.setattr(staff,'upload_media',lambda *args:'100')
    from fastapi import HTTPException
    calls=[]
    def timeout(*args):calls.append(args);raise HTTPException(502,'timeout')
    monkeypatch.setattr(staff,'graph',timeout);approve(client,prepared,True)
    staff.dispatch_staff(10);staff.dispatch_staff(10)
    assert len(calls)==2
    statuses=[m['status'] for p in client.get(prepared[1]).json()['recipients'] for m in p['messages']]
    assert statuses.count('uncertain')==2 and statuses.count('failed')==4

def test_import_and_permissions(client):
    wb=Workbook();wb.active.append(['Ad Soyad','Telefon','Mağaza']);wb.active.append(['Ali Veli','05321234567','A']);wb.active.append(['Tekrar','05321234567','B']);wb.active.append(['Hata','abc','C']);f=io.BytesIO();wb.save(f)
    r=client.post('/api/staff/import',files={'file':('personel.xlsx',f.getvalue())}).json()
    assert r['imported']==1 and r['duplicates']==1 and r['errors'][0]['row']==4
    with Session() as db:
        c=db.scalar(select(Contact));c.opted_out=True;c.consent='revoked';db.commit()
    assert client.post('/api/staff/import',files={'file':('personel.xlsx',f.getvalue())}).status_code==200
    assert client.get('/api/staff/people').json()[0]['blocked']
    assert client.post('/api/users',json={'username':'operator','password':'TestPassword123!','role':'operator'}).status_code==200
    client.post('/api/logout',json={});client.post('/api/login',json={'username':'operator','password':'TestPassword123!'})
    for url in ('/people','/announcements','/announcements/1'):assert client.get('/api/staff'+url).status_code==403
    assert client.post('/api/staff/import',files={'file':('p.xlsx',f.getvalue())}).status_code==403

def test_preview_invalidation_targets_and_expiry(client,prepared):
    cfg={**prepared[2],'target':'stores','stores':['B']};p=client.post(prepared[1]+'/preview',json=cfg).json();assert p['people']==1
    with Session() as db:
        c=db.scalar(select(Contact).where(Contact.store=='B'));c.phone='+905321234570';db.commit()
    assert client.post(prepared[1]+'/send',json={'token':p['token']}).status_code==409
    with Session() as db:
        a=db.get(StaffAnnouncement,prepared[0]);a.preview_expires=now()-timedelta(seconds=1);db.commit()
    assert client.post(prepared[1]+'/send',json={'token':p['token']}).status_code==409

def test_bad_upload_and_codec(client,prepared,monkeypatch):
    base=prepared[1]
    assert client.post(base+'/assets',files={'file':('bad.exe',b'MZ')}).status_code==422
    assert client.post(base+'/assets',files={'file':('again.pdf',b'%PDF-1.7')}).status_code==422
    assert client.post(base+'/assets',files={'file':('bad.mp4',b'not mp4')}).status_code==422
    assert client.post(base+'/assets',files={'file':('large.mp4',b'\0'*(16*1024*1024+1))}).status_code==413

def test_early_webhook_and_monotonic_status(client,prepared,monkeypatch):
    live(monkeypatch);monkeypatch.setattr(staff,'upload_media',lambda *a:'100')
    def send(*args):
        with Session() as db:db.add(WebhookItem(id='early',kind='status',phone_number_id=settings.meta_phone_number_id,meta_id='wamid.early',payload=json.dumps({'id':'wamid.early','status':'read'})));db.commit()
        return {'messages':[{'id':'wamid.early'}]}
    monkeypatch.setattr(staff,'graph',send);approve(client,prepared,True);staff.dispatch_staff(1)
    webhook(client,'wamid.early','sent');webhook(client,'wamid.early','failed')
    with Session() as db:assert db.scalar(select(StaffDelivery).where(StaffDelivery.meta_id=='wamid.early')).status=='read'

def test_simulation_never_becomes_live(client,prepared,monkeypatch):
    approve(client,prepared);live(monkeypatch);staff.dispatch_staff(10)
    assert all(p['status']=='dry_run' for p in client.get(prepared[1]).json()['recipients'])

def test_direct_upload_single_use_expiry_and_size(client):
    id=client.post('/api/staff/announcements',json={'name':'Direct'}).json()['id'];base=f'/api/staff/announcements/{id}'
    raw=b'%PDF-1.7 private'
    ticket=client.post(base+'/upload-ticket',json={'filename':'a.pdf','size':len(raw)}).json()['url']
    assert client.put(ticket,content=raw).status_code==200
    assert client.put(ticket,content=raw).status_code==403
    assert client.put('/api/staff-upload/invalid',content=raw).status_code==403
    assert client.post(base+'/upload-ticket',json={'filename':'big.mp4','size':17*1024*1024}).status_code==413
    ticket=client.post(base+'/upload-ticket',json={'filename':'b.pdf','size':1}).json()['url']
    assert client.put(ticket,content=raw).status_code==413
    ticket=client.post(base+'/upload-ticket',json={'filename':'b.pdf','size':len(raw)}).json()['url']
    with Session() as db:
        key='staff_upload:'+hashlib.sha256(ticket.rsplit('/',1)[1].encode()).hexdigest();g=db.get(SystemValue,key);data=json.loads(g.value);data['expires']=(now()-timedelta(seconds=1)).isoformat();g.value=json.dumps(data);db.commit()
    assert client.put(ticket,content=raw).status_code==403

def test_direct_upload_production_origin_guard(client,monkeypatch):
    id=client.post('/api/staff/announcements',json={'name':'Direct'}).json()['id']
    ticket=client.post(f'/api/staff/announcements/{id}/upload-ticket',json={'filename':'a.pdf','size':10}).json()['url']
    monkeypatch.setattr(settings,'app_environment','production');monkeypatch.setattr(settings,'panel_origin','https://panel.vercel.app')
    assert client.put(ticket,content=b'%PDF-1.7xx',headers={'Origin':'https://evil.example'}).status_code==403
    assert client.put(ticket,content=b'%PDF-1.7xx',headers={'Origin':'https://panel.vercel.app'}).status_code==200

def test_additive_migration_preserves_existing_data(tmp_path):
    import os,subprocess,sys
    from sqlalchemy import create_engine,text,inspect
    url='sqlite:///'+str(tmp_path/'migration.db');env={**os.environ,'DATABASE_URL':url}
    subprocess.run([sys.executable,'-m','alembic','upgrade','003'],env=env,cwd=__import__('pathlib').Path(__file__).resolve().parents[1],check=True,capture_output=True)
    e=create_engine(url)
    with e.begin() as c:c.execute(text("INSERT INTO system_values (key,value) VALUES ('sentinel','preserved')"))
    subprocess.run([sys.executable,'-m','alembic','upgrade','head'],env=env,cwd=__import__('pathlib').Path(__file__).resolve().parents[1],check=True,capture_output=True)
    with e.connect() as c:
        assert c.execute(text("SELECT value FROM system_values WHERE key='sentinel'")).scalar()=='preserved'
        assert c.execute(text('SELECT version_num FROM alembic_version')).scalar()=='008'
    assert {'contacts','messages','campaigns','staff_announcements','staff_assets','staff_deliveries'}<=set(inspect(e).get_table_names())

def test_large_audience_status_pagination(client,prepared):
    with Session() as db:
        for i in range(53):db.add(Contact(kind='staff',first_name=f'Personel {i}',phone='+'+str(905321200000+i),store='A'))
        db.commit()
    approve(client,prepared)
    first=client.get(prepared[1]).json();second=client.get(prepared[1]+'?page=2').json()
    assert first['recipient_total']==55 and first['pages']==2
    assert len(first['recipients'])==50 and len(second['recipients'])==5
    assert not ({p['phone'] for p in first['recipients']}&{p['phone'] for p in second['recipients']})
    assert 'config' not in client.get('/api/staff/announcements').json()[0]
    assert 'preview_token' not in first['announcement']

@pytest.mark.parametrize('headers,row',[
    (['Telefon'],['05321234567']),
    (['Telefon','Ad Soyad'],['05321234567','Ali Veli']),
    (['Telefon','Mağaza'],['05321234567','A']),
    (['Ad Soyad','Telefon','Mağaza'],[None,'05321234567',None]),
])
def test_import_optional_staff_fields(client,headers,row):
    wb=Workbook();wb.active.append(headers);wb.active.append(row);f=io.BytesIO();wb.save(f)
    response=client.post('/api/staff/import',files={'file':('staff.xlsx',f.getvalue())})
    assert response.status_code==200,response.text
    assert response.json()['imported']==1 and response.json()['errors']==[]
    p=client.get('/api/staff/people').json()[0]
    assert p['phone']=='+905321234567'
    assert p['name']==('Ali Veli' if 'Ali Veli' in row else '')
    assert p['store']==('A' if 'A' in row else '')

def test_phone_only_import_preserves_existing_metadata_and_ret(client):
    with Session() as db:
        db.add(Contact(kind='staff',first_name='Ali',last_name='Veli',phone='+905321234567',store='A',opted_out=True,consent='revoked'));db.commit()
    for raw in (b'Telefon\n05321234567\n',b'Telefon;Ad Soyad;Ma\xc4\x9faza\n05321234567;;\n'):
        r=client.post('/api/staff/import',files={'file':('staff.csv',raw)});assert r.status_code==200,r.text
    p=client.get('/api/staff/people').json()[0]
    assert p['name']=='Ali Veli' and p['store']=='A' and p['blocked']

def test_import_still_requires_phone_column_and_valid_phone(client):
    r=client.post('/api/staff/import',files={'file':('staff.csv',b'Ad Soyad\nAli Veli\n')});assert r.status_code==422
    r=client.post('/api/staff/import',files={'file':('staff.csv',b'Telefon\ninvalid\n')})
    assert r.status_code==200 and r.json()['imported']==0 and len(r.json()['errors'])==1

@pytest.mark.parametrize('cause,expected',[
    ('staff_dispatch_enabled','STAFF_DISPATCH_ENABLED=false'),
    ('deployment_send_lock','DEPLOYMENT_SEND_LOCK=true'),
    ('live_send_enabled','LIVE_SEND_ENABLED=false'),
    ('connection','doğrulamanın süresi dolmuş'),
    ('confirmation','kutuyu işaretleyin'),
])
def test_live_approval_names_actual_blocker_without_enqueuing(client,prepared,monkeypatch,cause,expected):
    live(monkeypatch)
    if cause=='connection':monkeypatch.setattr(staff,'connection_ok',lambda db:False)
    elif cause!='confirmation':monkeypatch.setattr(settings,cause,cause=='deployment_send_lock')
    _,base,cfg=prepared
    preview=client.post(base+'/preview',json=cfg);assert preview.status_code==200,preview.text
    if cause!='confirmation':assert any(expected in reason for reason in preview.json()['send_blockers'])
    response=client.post(base+'/send',json={'token':preview.json()['token'],'confirm_live':cause!='confirmation'})
    assert response.status_code==403 and expected in response.json()['detail']
    with Session() as db:
        assert db.get(StaffAnnouncement,prepared[0]).status=='draft'
        assert db.scalar(select(func.count()).select_from(StaffDelivery))==0


def test_review_examples_and_json_order_do_not_pause_staff_send(client,prepared,monkeypatch):
    live(monkeypatch);approve(client,prepared,True)
    with Session() as db:
        t=db.get(Template,prepared[2]['document_template']);parts=json.loads(t.components)
        parts[0]['example']={'header_handle':['4::new-review-only-handle']};parts.reverse();t.components=json.dumps(parts,indent=2)
        db.commit();delivery=db.scalar(select(StaffDelivery.id).order_by(StaffDelivery.id))
    calls=[]
    monkeypatch.setattr(staff,'upload_media',lambda *args:'123456')
    monkeypatch.setattr(staff,'graph',lambda *args:calls.append(args) or {'messages':[{'id':'wamid.canonical.staff'}]})
    assert staff.process_staff(delivery)
    assert len(calls)==1
    with Session() as db:
        assert db.get(StaffAnnouncement,prepared[0]).status=='running'
        assert db.get(StaffDelivery,delivery).status=='accepted'


@pytest.mark.parametrize('cause,code',[
    ('body','template_changed'),('sender','sender_changed'),('expired','media_expired'),('status','template_unavailable'),
])
def test_automatic_staff_pause_explains_blocker_and_never_sends(client,prepared,monkeypatch,cause,code):
    live(monkeypatch);approve(client,prepared,True)
    with Session() as db:
        row=db.scalar(select(StaffDelivery).order_by(StaffDelivery.id));delivery=row.id
        if cause=='body':db.get(Template,prepared[2]['document_template']).body+=' Changed'
        if cause=='status':db.get(Template,prepared[2]['document_template']).status='PAUSED'
        if cause=='sender':db.get(StaffAnnouncement,prepared[0]).sender_id='999999'
        if cause=='expired':db.get(StaffAsset,row.asset_id).expires=now()-timedelta(seconds=1)
        db.commit()
    assert not staff.process_staff(delivery)
    detail=client.get(prepared[1]).json();assert detail['announcement']['status']=='paused'
    assert detail['announcement']['pause_code']==code and detail['announcement']['pause_reason']
    assert detail['recipients'][0]['messages'][0]['status']=='queued'
    assert detail['recipients'][0]['messages'][0]['error']
    assert client.post(prepared[1]+'/resume',json={}).status_code==200
    assert not staff.process_staff(delivery)
    assert client.get(prepared[1]).json()['announcement']['pause_code']==code


def test_import_returns_only_current_file_ids_and_preview_excludes_saved_people(client,prepared):
    raw='Ad Soyad,Telefon,Mağaza\nYeni Personel,05321234570,A\nYeni Personel,05321234570,A\nHatalı,invalid,A\n'
    response=client.post('/api/staff/import',files={'file':('current.csv',raw.encode(),'text/csv')})
    assert response.status_code==200,response.text
    imported=response.json();assert imported['imported']==1 and len(imported['contact_ids'])==1
    assert imported['duplicates']==1 and len(imported['errors'])==1
    _,base,cfg=prepared
    scoped=client.post(base+'/preview',json={**cfg,'source_people':imported['contact_ids']})
    assert scoped.status_code==200,scoped.text
    assert scoped.json()['people']==1 and scoped.json()['recipients'][0]['phone']=='+905321234570'
    # A malicious/stale explicit selection cannot escape this upload's scope.
    with Session() as db:old_id=db.scalar(select(Contact.id).where(Contact.phone=='+905321234567',Contact.kind=='staff'))
    denied=client.post(base+'/preview',json={**cfg,'source_people':imported['contact_ids'],'target':'people','people':[old_id]})
    assert denied.status_code==422
    assert client.post(base+'/preview',json={**cfg,'source_people':[]}).status_code==422
    # Explicitly opting into stored people retains the existing supported behavior.
    assert client.post(base+'/preview',json={**cfg,'source_people':None}).json()['people']==3


def test_reimport_ids_include_existing_records_without_restoring_opted_out_people(client,prepared):
    with Session() as db:
        person=db.scalar(select(Contact).where(Contact.phone=='+905321234567',Contact.kind=='staff'));person.opted_out=True;old_id=person.id;db.commit()
    response=client.post('/api/staff/import',files={'file':('current.csv',b'Telefon\n05321234567\n','text/csv')})
    assert response.status_code==200 and response.json()['contact_ids']==[old_id]
    _,base,cfg=prepared
    assert client.post(base+'/preview',json={**cfg,'source_people':[old_id]}).status_code==422
    with Session() as db:assert db.get(Contact,old_id).opted_out
