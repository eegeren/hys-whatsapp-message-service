"""Read-only queue diagnostics. Never dispatch work or expose credentials."""
import hashlib,json
from datetime import datetime
from redis import Redis
from app.core import settings,now

HEARTBEAT='hys:production-worker:heartbeat'
STATE='hys:production-worker:state'

def worker_fingerprint():
    values=[settings.database_url,settings.meta_access_token,settings.meta_phone_number_id,settings.meta_waba_id,settings.meta_environment]
    return hashlib.sha256(json.dumps(values).encode()).hexdigest()

def worker_snapshot(state='ready'):
    return json.dumps({'state':state,'fingerprint':worker_fingerprint(),
        'dispatch_enabled':settings.bulk_dispatch_enabled,'send_locked':settings.deployment_send_lock,
        'dry_run':settings.dry_run,'live_enabled':settings.live_send_enabled})

def worker_health():
    if settings.app_environment!='production':return {'state':'local' if settings.local_worker else 'missing'}
    cache=None
    try:
        cache=Redis.from_url(settings.redis_url,socket_timeout=.5,socket_connect_timeout=.5,decode_responses=True)
        heartbeat,raw=cache.mget([HEARTBEAT,STATE])
        if not heartbeat:return {'state':'missing'}
        age=(now()-datetime.fromisoformat(heartbeat)).total_seconds()
        if not 0<=age<90:return {'state':'missing'}
        if not raw:return {'state':'legacy'}
        data=json.loads(raw)
        if not isinstance(data,dict) or data.get('state') not in ('ready','error'):return {'state':'unknown'}
        # Explicit allowlist: never echo arbitrary Redis values or fingerprints.
        return {'state':data['state'],'configuration_matches':data.get('fingerprint')==worker_fingerprint(),
            **{k:data.get(k) if isinstance(data.get(k),bool) else None for k in ('dispatch_enabled','send_locked','dry_run','live_enabled')}}
    except Exception:return {'state':'unavailable'}
    finally:
        if cache:
            try:cache.close()
            except Exception:pass
