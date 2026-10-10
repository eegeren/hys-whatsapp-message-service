"""Continuous Railway service; PostgreSQL is the durable queue, Redis coordinates workers."""
import signal,time,json
from sqlalchemy import select
from app.core import Session,now,settings
from app.deployment import validate_production,redis_client
from app.worker import dispatch_local,finalize
from app.queue_health import HEARTBEAT,STATE,worker_snapshot

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
    waiting=False
    state='ready'
    print(json.dumps({'event':'worker_started','dispatch_enabled':settings.bulk_dispatch_enabled,'send_locked':settings.deployment_send_lock}),flush=True)
    try:
        while not stopping:
            try:
                if not owned:
                    owned=lease.acquire(blocking=False)
                    if not owned and not waiting:
                        print(json.dumps({'event':'worker_waiting_for_lease','notice':'Başka bir worker kilidi tutuyor; bu süreç gönderim yapmıyor.'}),flush=True)
                        waiting=True
                    elif owned:
                        waiting=False
                        print(json.dumps({'event':'worker_lease_acquired'}),flush=True)
                if owned:
                    lease.extend(120,replace_ttl=True)
                    cache.set(HEARTBEAT,now().isoformat(),ex=90)
                    cache.set(STATE,worker_snapshot(state),ex=90)
            except Exception:
                print(json.dumps({'event':'worker_check_failed','phase':'lease_or_heartbeat','details':'hidden'}),flush=True)
                if owned:
                    try:lease.release()
                    except Exception:pass
                owned=False
            if owned:
                try:
                    if settings.bulk_dispatch_enabled and not settings.deployment_send_lock:dispatch_local(limit=1)
                    else:finalize()
                    state='ready'
                except Exception:
                    # Queue failure does not relinquish an otherwise healthy lease.
                    state='error'
                    print(json.dumps({'event':'worker_dispatch_failed','details':'hidden'}),flush=True)
                try:cache.set(STATE,worker_snapshot(state),ex=90)
                except Exception:pass
            time.sleep(1)
    finally:
        if owned:
            try:cache.delete(HEARTBEAT,STATE)
            except Exception:pass
            try:lease.release()
            except Exception:pass
        try:cache.close()
        except Exception:pass
        print(json.dumps({'event':'worker_stopped'}),flush=True)

if __name__=='__main__':
    try:run()
    except Exception:
        print(json.dumps({'event':'worker_start_failed','details':'hidden'}),flush=True)
        raise SystemExit(1)
