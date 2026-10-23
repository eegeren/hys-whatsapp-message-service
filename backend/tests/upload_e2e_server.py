"""Isolated browser upload fixture. All outbound Meta access is forbidden."""
import os,json,hashlib
if os.environ.get('HYS_UPLOAD_E2E')!='1' or 'hys-upload-e2e-' not in os.environ.get('DATABASE_URL',''):
    raise RuntimeError('Requires isolated upload E2E database')
from fastapi import Request
from app.core import Base,engine,settings,Session,Template
settings.dry_run=True
settings.live_send_enabled=False
settings.local_worker=False
settings.deployment_send_lock=True
from app.main import app
from app import meta,messaging,bulk,staff,video_jobs
Base.metadata.create_all(engine)
from starlette.routing import Mount
app.router.routes[:]=[r for r in app.router.routes if not isinstance(r,Mount)]
def forbidden(*a,**k):raise AssertionError('Outbound Meta access forbidden')
for module in (meta,messaging,bulk,staff):
    if hasattr(module,'graph'):module.graph=forbidden
    if hasattr(module,'upload_media'):module.upload_media=forbidden

def prepared(raw,name,*args,**kwargs):
    return raw,{'converted':False,'source_size':len(raw),'output_size':len(raw),'original':{'video_codec':'h264','audio_codec':'aac'},'result':{'video_codec':'h264','audio_codec':'aac'}}
video_jobs.prepare_video=prepared
from app import video_processing
video_processing.prepare_video=prepared
# Replace dispatch before any endpoint runs: validate bytes, never send a message.
def capture(data,user,db,upload=None):
    assert upload is not None
    return {'received_bytes':len(upload.content),'sha256':hashlib.sha256(upload.content).hexdigest(),'message_sent':False}
messaging.send_direct_message=capture
@app.post('/_test/process')
def process():
    assert video_jobs.process_next_video()
    return {'ok':True}
@app.get('/_test/template')
def template():
    with Session() as db:
        t=Template(name='upload_e2e',status='APPROVED',category='MARKETING',language='tr',body='Test',components=json.dumps([{'type':'HEADER','format':'VIDEO'},{'type':'BODY','text':'Test'}]))
        db.add(t);db.commit();return {'id':t.id}
