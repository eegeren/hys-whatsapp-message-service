"""Video conversion thread/service; no Meta API operations."""
import logging,signal,threading
from app.core import settings
from app.video_jobs import process_next_video

def loop(stop):
    while not stop.is_set():
        try:processed=process_next_video(stop)
        except Exception as exc:
            logging.getLogger('hys.video').error('video_queue_failure exception=%s',type(exc).__name__);processed=False
        if not processed:stop.wait(1)

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
    loop(stop)
