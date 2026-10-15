"""Video conversion thread/service; no Meta API operations."""
import json,logging,signal,threading,uuid
from app.core import settings,Session,SystemValue,now
from app.video_jobs import process_next_video


def heartbeat(stop,identity,state):
    while not stop.is_set():
        try:
            with Session() as db:
                db.merge(SystemValue(key=identity,value=json.dumps({'seen':now().isoformat(),'state':state[0],'enabled':settings.video_processing_enabled})));db.commit()
        except Exception as exc:logging.getLogger('hys.video').error('video_heartbeat_failure exception=%s',type(exc).__name__)
        stop.wait(5)


def loop(stop):
    identity='video_worker:'+str(uuid.uuid4());state=['ready']
    pulse=threading.Thread(target=heartbeat,args=(stop,identity,state),daemon=True,name='hys-video-heartbeat');pulse.start()
    try:
        while not stop.is_set():
            try:
                process_next_video(stop);state[0]='ready'
            except Exception as exc:
                state[0]='error';logging.getLogger('hys.video').error('video_queue_failure exception=%s',type(exc).__name__)
            stop.wait(1)
    finally:
        stop.set();pulse.join(timeout=6)
        try:
            with Session() as db:
                row=db.get(SystemValue,identity)
                if row:db.delete(row);db.commit()
        except Exception:pass


def start_video_thread():
    stop=threading.Event()
    thread=threading.Thread(target=loop,args=(stop,),name='hys-video',daemon=True)
    if settings.video_processing_enabled:thread.start()
    return stop,thread


if __name__=='__main__':
    from app.deployment import validate_production
    validate_production('worker')
    logging.basicConfig(level=logging.INFO)
    stop=threading.Event()
    signal.signal(signal.SIGTERM,lambda *_:stop.set());signal.signal(signal.SIGINT,lambda *_:stop.set())
    if settings.video_processing_enabled:loop(stop)
    else:raise SystemExit('VIDEO_PROCESSING_ENABLED=false; video worker is disabled.')
