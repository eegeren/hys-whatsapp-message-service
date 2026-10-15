"""Run ONLY on an explicitly isolated disposable DB; never on production."""
import json,os,subprocess,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
if os.environ.get('HYS_VIDEO_DEPLOYMENT_TEST')!='1' or '/hys_video_test' not in os.environ.get('DATABASE_URL',''):
    raise SystemExit('An isolated hys_video_test database and explicit test flag are required.')
subprocess.run([sys.executable,'-m','alembic','upgrade','004'],check=True)
from app.core import Session,SystemValue,VideoJob,settings
with Session() as db:db.add(SystemValue(key='video-migration-sentinel',value='preserved'));db.commit()
subprocess.run([sys.executable,'-m','alembic','upgrade','head'],check=True)
from app.main import app
from app import messaging,staff,meta,media_templates
from app.video_jobs import process_next_video
from fastapi.testclient import TestClient

def forbid(*a,**k):raise AssertionError('No Meta calls permitted in deployment tests')
for module in (messaging,staff,meta,media_templates):
    module.graph=forbid
    if hasattr(module,'upload_media'):module.upload_media=forbid
with tempfile.TemporaryDirectory(prefix='hys-container-test-') as directory:
    path=Path(directory)/'sample.mov'
    subprocess.run([settings.ffmpeg_path,'-hide_banner','-loglevel','error','-y','-f','lavfi','-i','testsrc2=size=160x120:rate=15:duration=2','-f','lavfi','-i','sine=frequency=500:duration=2','-c:v','mpeg4','-c:a','pcm_s16le','-shortest',str(path)],check=True,timeout=30)
    raw=path.read_bytes()
    with TestClient(app) as c:
        c.headers['X-HYS-Request']='1'
        credentials={'username':'deployment-test','password':'SyntheticTest123!','bootstrap_token':settings.bootstrap_token}
        assert c.post('/api/setup',json=credentials).status_code==200
        assert c.post('/api/login',json=credentials).status_code==200
        job=c.post('/api/video/jobs',json={'filename':'sample.mov','size':len(raw)}).json()
        assert c.put(job['upload_url'],content=raw).status_code==200
        assert process_next_video()
        ready=c.get('/api/video/jobs/'+job['id']).json();assert ready['status']=='ready',ready
        assert ready['info']['result']['video_codec']=='h264' and ready['info']['result']['audio_codec']=='aac' and ready['info']['result']['pixel_format']=='yuv420p'
        assert c.get(ready['preview_url'],headers={'Range':'bytes=0-99'}).status_code==206
        announcement=c.post('/api/staff/announcements',json={'name':'Container test'}).json()['id']
        assert c.post(f'/api/staff/announcements/{announcement}/assets',files={'file':('sample.pdf',b'%PDF-1.7','application/pdf')}).status_code==200
        assert c.post(f'/api/staff/announcements/{announcement}/videos',json={'video_job_id':job['id']}).status_code==200
        assert c.post('/api/conversations/send',json={'phone':'+905321234567','video_job_id':job['id']}).status_code==403
    with Session() as db:
        assert db.get(SystemValue,'video-migration-sentinel').value=='preserved'
        assert db.get(VideoJob,job['id']).source is None
print('PASS: PostgreSQL 004→005 preserves data; real Railway-image FFmpeg/FFprobe MOV→H264/yuv420p/AAC conversion, signed range preview, staff attachment, source cleanup; no Meta calls.')
