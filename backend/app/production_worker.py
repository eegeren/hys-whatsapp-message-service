"""Continuous Railway service; PostgreSQL is the durable queue, Redis coordinates workers."""
import signal,time,json
from sqlalchemy import select
from app.core import Session,now,settings
from app.deployment import validate_production,redis_client
from app.worker import dispatch_local,finalize

stopping=False
def stop(*args):
    global stopping
    stopping=True

def run():
    validate_production('worker')
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    cache=redis_client()
    with Session() as db:db.execute(select(1))
    cache.ping()
    lease=cache.lock('hys:production-worker:lease',timeout=120,blocking=False)
    owned=False
    print(json.dumps({'event':'worker_started','dispatch_enabled':settings.bulk_dispatch_enabled,'send_locked':settings.deployment_send_lock}),flush=True)
    try:
        while not stopping:
            try:
                if not owned:owned=lease.acquire(blocking=False)
                if owned:
                    lease.extend(120,replace_ttl=True)
                    cache.set('hys:production-worker:heartbeat',now().isoformat(),ex=90)
                    if settings.bulk_dispatch_enabled and not settings.deployment_send_lock:dispatch_local(limit=1)
                    else:finalize()
            except Exception:
                print(json.dumps({'event':'worker_check_failed','details':'hidden'}),flush=True)
                owned=False
            time.sleep(1)
    finally:
        if owned:
            try:lease.release()
            except Exception:pass
        print(json.dumps({'event':'worker_stopped'}),flush=True)

if __name__=='__main__':
    try:run()
    except Exception:
        print(json.dumps({'event':'worker_start_failed','details':'hidden'}),flush=True)
        raise SystemExit(1)
