import os,runpy,json,importlib.util
from datetime import timedelta
from pathlib import Path
import pytest
from fastapi import HTTPException
from app.core import settings,database_dsn,Session,Campaign,Message
from sqlalchemy import select

def cloud(monkeypatch):
    monkeypatch.setattr(settings,'app_environment','production')
    monkeypatch.setattr(settings,'panel_origin','https://panel-test.vercel.app')
    monkeypatch.setattr(settings,'panel_proxy_secret','fake-proxy-secret-only-for-tests-32chars')
    monkeypatch.setattr(settings,'bootstrap_token','fake-bootstrap-secret-for-tests-32chars')

def proxy_headers():
    return {'Origin':settings.panel_origin,'X-HYS-Request':'1','X-HYS-Proxy-Secret':settings.panel_proxy_secret}

def test_production_api_requires_proxy_session_origin_and_csrf(client,monkeypatch):
    cloud(monkeypatch)
    assert client.get('/api/messages').status_code==403
    assert client.get('/api/messages',headers=proxy_headers()).status_code==200
    assert client.get('/api/messages',headers={**proxy_headers(),'Origin':'https://evil.vercel.app'}).status_code==403
    assert client.post('/api/logout',headers={**proxy_headers(),'X-HYS-Request':'0'}).status_code==403
    assert client.post('/api/logout',headers=proxy_headers()).status_code==200
    assert client.get('/api/messages',headers=proxy_headers()).status_code==401
    # Webhook is public, but its own signature validation remains mandatory.
    assert client.post('/api/webhook',json={}).status_code==403
    assert client.get('/api/health').status_code==200

def test_production_cookie_is_secure_and_short_password_is_rejected(client,monkeypatch):
    cloud(monkeypatch)
    response=client.post('/api/login',headers=proxy_headers(),json={'username':'admin','password':'TestPassword123!'})
    assert response.status_code==200
    cookie=response.headers['set-cookie']
    assert 'Secure' in cookie and 'HttpOnly' in cookie and 'SameSite=strict' in cookie
    assert client.post('/api/login',headers=proxy_headers(),json={'username':'hys','password':'hys'}).status_code==401

def test_deployment_lock_prevents_even_direct_graph_message_call(monkeypatch):
    from app.meta import graph
    monkeypatch.setattr(settings,'deployment_send_lock',True)
    monkeypatch.setattr('app.meta.httpx.Client',lambda **k:pytest.fail('No network call is allowed'))
    with pytest.raises(HTTPException) as e:graph('POST','1353767504488829/messages',{})
    assert e.value.status_code==403

def test_dispatch_disabled_keeps_existing_queue_untouched(client,monkeypatch):
    from tests.test_bulk_friendly import prepare,fake_live
    from app.worker import dispatch_local,process_one
    cid,_,_=prepare(client);calls=fake_live(monkeypatch)
    client.post(f'/api/bulk/campaign/{cid}/start',json={'confirmed':True})
    monkeypatch.setattr(settings,'bulk_dispatch_enabled',False)
    with Session() as db:ids=list(db.scalars(select(Message.id)))
    dispatch_local()
    for id in ids:process_one(id)
    assert calls==[]
    with Session() as db:assert all(db.get(Message,id).status=='queued' for id in ids)

def test_port_entry_point_uses_railway_port(monkeypatch):
    monkeypatch.setenv('PORT','12345')
    monkeypatch.setattr('app.deployment.validate_production',lambda *a:None)
    calls=[];monkeypatch.setattr('uvicorn.run',lambda *a,**k:calls.append(k))
    with pytest.raises(SystemExit) as exc:
        runpy.run_module('app.serve',run_name='__main__')
    assert exc.value.code==0
    assert calls[0]['port']==12345 and calls[0]['host']=='0.0.0.0'
    assert not calls[0]['access_log']

@pytest.mark.parametrize('port',['invalid-secret-value','0','65536'])
def test_invalid_port_exits_without_disclosing_value(monkeypatch,capsys,port):
    from app.serve import run
    monkeypatch.setenv('PORT',port)
    monkeypatch.setattr('uvicorn.run',lambda *a,**k:pytest.fail('Server must not start'))
    assert run()==1
    output=capsys.readouterr().out
    assert 'Başlangıç durdu' in output
    if port=='invalid-secret-value':assert port not in output
    assert 'PORT' in output

def test_unexpected_configuration_error_hides_credentials(monkeypatch,capsys):
    from app.serve import run
    def broken(*args):raise RuntimeError('postgresql://user:fake-private-password@host/db')
    monkeypatch.setattr('app.deployment.validate_production',broken)
    monkeypatch.setattr('uvicorn.run',lambda *a,**k:pytest.fail('Server must not start'))
    assert run()==1
    assert 'fake-private-password' not in capsys.readouterr().out

def test_malformed_database_url_does_not_leak_import_exception():
    import subprocess,sys
    env={**os.environ,'DATABASE_URL':'not-a-dsn-with-fake-private-password','PORT':'12345'}
    result=subprocess.run([sys.executable,'-m','app.serve'],cwd=Path(__file__).resolve().parents[1],env=env,capture_output=True,text=True,timeout=15)
    assert result.returncode==1
    assert 'fake-private-password' not in result.stdout+result.stderr
    assert 'DATABASE_URL' in result.stdout
    assert 'Traceback' not in result.stderr

def test_railway_defaults_are_production_and_locked():
    import subprocess,sys
    env={**os.environ,'RAILWAY_ENVIRONMENT_ID':'fake-environment'}
    for name in ('APP_ENVIRONMENT','LOCAL_WORKER','DEPLOYMENT_SEND_LOCK','BULK_DISPATCH_ENABLED'):env.pop(name,None)
    code='from app.core import settings; assert settings.app_environment=="production"; assert not settings.local_worker; assert settings.deployment_send_lock; assert not settings.bulk_dispatch_enabled'
    result=subprocess.run([sys.executable,'-c',code],cwd=Path(__file__).resolve().parents[1],env=env,capture_output=True,timeout=15)
    assert result.returncode==0

def test_postgres_connection_and_pool_have_timeouts():
    from app.core import database_engine_options
    options=database_engine_options('postgresql+psycopg://user:fake@localhost/db')
    assert options['pool_timeout']==5
    assert options['connect_args']['connect_timeout']==5
    assert 'options' not in options['connect_args'] # Do not impose a timeout on migrations or business queries.

def test_railway_cannot_start_in_local_mode(monkeypatch):
    from app.deployment import validate_production
    monkeypatch.setenv('RAILWAY_ENVIRONMENT_ID','fake-environment')
    monkeypatch.setattr(settings,'app_environment','local')
    with pytest.raises(RuntimeError,match='APP_ENVIRONMENT=production'):validate_production()

@pytest.mark.parametrize('failure',['database','migration','redis',None])
def test_production_startup_readonly_checks_hide_secrets(monkeypatch,capsys,failure):
    from app.deployment import check_startup_dependencies
    cloud(monkeypatch)
    queries=[]
    class Result:
        def scalars(self):return ['002' if failure=='migration' else '003']
    class Connection:
        def __enter__(self):
            if failure=='database':raise RuntimeError('fake-private-password')
            return self
        def __exit__(self,*args):pass
        def execute(self,sql):queries.append(str(sql));return Result()
    class Engine:
        def connect(self):return Connection()
    class Cache:
        closed=False
        def ping(self):
            if failure=='redis':raise RuntimeError('fake-private-password')
            return True
        def close(self):self.closed=True
    cache=Cache()
    monkeypatch.setattr('app.core.engine',Engine())
    monkeypatch.setattr('app.deployment.redis_client',lambda:cache)
    if failure:
        with pytest.raises(RuntimeError) as exc:check_startup_dependencies()
        assert 'fake-private-password' not in str(exc.value)
    else:check_startup_dependencies()
    assert all(query.startswith('SELECT ') or query=="SET LOCAL statement_timeout = '5s'" for query in queries)
    output=capsys.readouterr().out
    assert 'fake-private-password' not in output
    assert ('API hazır' in output)==(failure is None)
    if failure in ('redis',None):assert cache.closed

def test_production_volume_permission_failure_is_safe(monkeypatch,tmp_path):
    from app.deployment import validate_production
    cloud(monkeypatch)
    monkeypatch.setattr(settings,'database_url','postgresql+psycopg://user:fake@localhost/db')
    monkeypatch.setenv('RAILWAY_VOLUME_MOUNT_PATH',str(tmp_path))
    monkeypatch.setattr(settings,'bulk_media_dir',str(tmp_path/'media'))
    def denied(*args,**kwargs):raise PermissionError('fake-sensitive-path')
    monkeypatch.setattr(Path,'mkdir',denied)
    with pytest.raises(RuntimeError,match='Kalıcı medya diski yazılabilir değil') as exc:validate_production()
    assert 'fake-sensitive-path' not in str(exc.value)

def test_postgres_railway_dsn_uses_installed_psycopg_driver():
    assert database_dsn('postgresql://user:password@postgres/db').startswith('postgresql+psycopg://')
    assert database_dsn('postgres://user:password@postgres/db').startswith('postgresql+psycopg://')

def test_production_validation_requires_persistent_media_volume(monkeypatch,tmp_path):
    from app.deployment import validate_production
    cloud(monkeypatch)
    monkeypatch.setattr(settings,'database_url','postgresql+psycopg://user:fake@localhost/db')
    monkeypatch.setenv('RAILWAY_VOLUME_MOUNT_PATH',str(tmp_path))
    monkeypatch.setattr(settings,'bulk_media_dir',str(tmp_path/'media'))
    validate_production('api');assert (tmp_path/'media').is_dir()
    monkeypatch.setattr(settings,'bulk_media_dir',str(tmp_path.parent/'ephemeral'))
    with pytest.raises(RuntimeError):validate_production('api')

def test_transfer_plan_preserves_success_cancel_and_pauses_active_jobs():
    path=Path(__file__).resolve().parents[1]/'tools'/'transfer_sqlite.py'
    spec=importlib.util.spec_from_file_location('hys_transfer',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    assert module.transform('campaigns',{'status':'running'})['status']=='paused'
    assert module.transform('campaigns',{'status':'cancelled'})['status']=='cancelled'
    for status in ('accepted','delivered','read','cancelled'):
        assert module.transform('messages',{'status':status})['status']==status
    assert module.transform('messages',{'status':'sending'})['status']=='uncertain'
    assert module.transform('sessions',{'id':'old-session'}) is None
    assert module.transform('system_values',{'key':'meta_verified','value':'old'}) is None

def test_future_scheduled_campaign_does_not_block_single_selection_worker(client,monkeypatch):
    from tests.test_bulk_friendly import prepare
    from app.core import now
    from app.worker import dispatch_local
    cid,_,tid=prepare(client)
    with Session() as db:
        old=db.get(Campaign,cid);old.status='scheduled';old.scheduled=now()+timedelta(days=1)
        db.add(Message(campaign_id=cid,phone='+905321234567',body='Future'))
        active=Campaign(kind='customer',name='Active',template_id=tid,status='running');db.add(active);db.flush()
        m=Message(campaign_id=active.id,phone='+905331234567',body='Ready');db.add(m);db.commit();mid=m.id
    seen=[];monkeypatch.setattr('app.worker.process_one',lambda id:seen.append(id))
    dispatch_local(limit=1);assert seen==[mid]

def test_locked_railway_worker_only_emits_heartbeat(client,monkeypatch):
    import app.production_worker as worker
    monkeypatch.setattr(worker,'stopping',False)
    monkeypatch.setattr(worker,'validate_production',lambda *a:None)
    monkeypatch.setattr(settings,'deployment_send_lock',True)
    monkeypatch.setattr(worker,'dispatch_local',lambda **k:pytest.fail('Locked worker must not dispatch'))
    monkeypatch.setattr(worker,'finalize',lambda:None)
    monkeypatch.setattr(worker.time,'sleep',lambda *a:None)
    class Lease:
        released=False
        def acquire(self,**k):return True
        def extend(self,*a,**k):pass
        def release(self):self.released=True
    lease=Lease();heartbeats=[]
    class Cache:
        def ping(self):return True
        def lock(self,*a,**k):return lease
        def set(self,key,value,**k):heartbeats.append(key);worker.stop()
    monkeypatch.setattr(worker,'redis_client',lambda:Cache())
    worker.run()
    assert heartbeats==['hys:production-worker:heartbeat'];assert lease.released
