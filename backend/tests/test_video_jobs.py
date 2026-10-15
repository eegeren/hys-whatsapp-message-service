import hashlib,json,time
from datetime import timedelta
import pytest
from sqlalchemy import select
from app.core import *
from app import video_jobs

@pytest.fixture
def uploaded(client):
    raw=b'fake input, network-free tests'
    r=client.post('/api/video/jobs',json={'filename':'input.mov','size':len(raw)});assert r.status_code==200,r.text
    job=r.json();assert client.put(job['upload_url'],content=raw).status_code==200
    return job

def complete(monkeypatch):
    def prepare(raw,name,progress,stop):
        progress('converting',50)
        return b'prepared MP4',{'converted':True,'original':{'video_codec':'hevc','audio_codec':'pcm_s16le'},'result':{'video_codec':'h264','pixel_format':'yuv420p','audio_codec':'aac'}}
    monkeypatch.setattr(video_jobs,'prepare_video',prepare)

def test_upload_prepare_preview_and_expiry(client,uploaded,monkeypatch):
    complete(monkeypatch);assert video_jobs.process_next_video()
    j=client.get('/api/video/jobs/'+uploaded['id']).json();assert j['status']=='ready' and j['progress']==100
    assert j['info']['original']['video_codec']=='hevc'
    preview=client.get(j['preview_url']);assert preview.content==b'prepared MP4' and preview.headers['cache-control']=='private, no-store'
    partial=client.get(j['preview_url'],headers={'Range':'bytes=1-5'});assert partial.status_code==206 and partial.content==b'repar'
    assert client.get(j['preview_url'],headers={'Range':'bytes=1000-'}).status_code==416
    assert client.put(uploaded['upload_url'],content=b'not again').status_code==403
    with Session() as db:
        row=db.get(VideoJob,uploaded['id']);assert row.source is None
        row.expires=now()-timedelta(seconds=1);db.commit()
    assert client.get(j['preview_url']).status_code==410
    video_jobs.process_next_video()
    with Session() as db:assert db.get(VideoJob,uploaded['id']).output is None

def test_processing_failure_distinguishes_reason(client,uploaded,monkeypatch):
    from app.video_processing import VideoError
    def bad(*a):raise VideoError('ffprobe_missing','Sunucuda FFprobe eksik.')
    monkeypatch.setattr(video_jobs,'prepare_video',bad);video_jobs.process_next_video()
    row=client.get('/api/video/jobs/'+uploaded['id']).json();assert row['status']=='failed' and row['error_code']=='ffprobe_missing'
    with Session() as db:assert db.get(VideoJob,uploaded['id']).source is None

def test_ready_video_single_message_path_never_sends_in_dry_run(client,uploaded,monkeypatch):
    from app import messaging
    complete(monkeypatch);video_jobs.process_next_video()
    monkeypatch.setattr(messaging,'graph',lambda *a,**k:pytest.fail('No Meta calls'))
    r=client.post('/api/conversations/send',json={'phone':'+905321234567','video_job_id':uploaded['id']})
    assert r.status_code==403

def test_staff_attach_requires_ready_video_and_keeps_pdf(client,uploaded,monkeypatch):
    base='/api/staff/announcements/'+str(client.post('/api/staff/announcements',json={'name':'Duyuru'}).json()['id'])
    assert client.post(base+'/assets',files={'file':('a.pdf',b'%PDF-1.7','application/pdf')}).status_code==200
    assert client.post(base+'/videos',json={'video_job_id':uploaded['id']}).status_code==409
    complete(monkeypatch);video_jobs.process_next_video()
    assert client.post(base+'/videos',json={'video_job_id':uploaded['id']}).status_code==200
    files=client.get(base).json()['files'];assert files[0]['kind']=='document' and files[1]['filename']=='input.mp4'
    assert client.post(base+'/videos',json={'video_job_id':uploaded['id']}).status_code==409

def test_other_operator_cannot_access_or_use_video(client,uploaded,monkeypatch):
    complete(monkeypatch);video_jobs.process_next_video()
    client.post('/api/users',json={'username':'other','password':'TestPassword123!','role':'operator'});client.post('/api/logout',json={});client.post('/api/login',json={'username':'other','password':'TestPassword123!'})
    assert client.get('/api/video/jobs/'+uploaded['id']).status_code==403
    assert client.delete('/api/video/jobs/'+uploaded['id']).status_code==403
    assert client.post('/api/conversations/send',json={'phone':'+905321234567','video_job_id':uploaded['id']}).status_code==403

def test_direct_upload_bad_origin_and_size_and_preview_signature(client,monkeypatch):
    j=client.post('/api/video/jobs',json={'filename':'a.mov','size':10}).json()
    monkeypatch.setattr(settings,'app_environment','production');monkeypatch.setattr(settings,'panel_origin','https://panel.vercel.app')
    assert client.put(j['upload_url'],content=b'123',headers={'origin':'https://evil.example'}).status_code==403
    assert client.put(j['upload_url'],content=b'12345678901',headers={'origin':settings.panel_origin}).status_code==413
    assert client.get(f'/api/video-preview/{j["id"]}/{int(time.time())+60}/invalid').status_code==403

def test_prepared_output_reaches_single_message_api_only_after_send(client,uploaded,monkeypatch):
    from app import messaging
    complete(monkeypatch);video_jobs.process_next_video();calls=[]
    monkeypatch.setattr(settings,'dry_run',False);monkeypatch.setattr(settings,'live_send_enabled',True);monkeypatch.setattr(messaging,'connection_ok',lambda db:True)
    monkeypatch.setattr(messaging,'upload_media',lambda name,raw,mime:calls.append(('upload',name,raw,mime)) or '12345')
    monkeypatch.setattr(messaging,'graph',lambda method,path,payload:calls.append(('message',payload)) or {'messages':[{'id':'wamid.mock-prepared-video'}]})
    with Session() as db:db.add(Message(phone='+905321234567',body='Merhaba',direction='in',status='received'));db.commit()
    # Validate shared output signature as in a real ready job, without any external request.
    with Session() as db:
        job=db.get(VideoJob,uploaded['id']);job.output=b'\0\0\0\x18ftypisom';job.output_size=len(job.output);db.commit()
    assert calls==[]
    response=client.post('/api/conversations/send',json={'phone':'+905321234567','body':'Duyuru videosu','video_job_id':uploaded['id']})
    assert response.status_code==200,response.text
    assert calls[0]==('upload','input.mp4',b'\0\0\0\x18ftypisom','video/mp4')
    assert calls[1][1]['video']=={'id':'12345','caption':'Duyuru videosu'}
