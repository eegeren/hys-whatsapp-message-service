"""Isolated local UI sandbox. Never uses the real database, token or queue."""
import json,os,socket,subprocess,tempfile,time
from pathlib import Path
import httpx

root=Path(__file__).resolve().parents[1]
temp=Path(tempfile.mkdtemp(prefix='hys-ui-preview-'))
logs=root/'test-results';logs.mkdir(exist_ok=True)
for port in (3002,5174):
    with socket.socket() as sock:sock.bind(('127.0.0.1',port))
env={**os.environ,'DATABASE_URL':'sqlite:///'+str(temp/'preview.db').replace('\\','/'),
     'APP_ENVIRONMENT':'local','DRY_RUN':'true','LIVE_SEND_ENABLED':'false','LOCAL_WORKER':'false',
     'DEPLOYMENT_SEND_LOCK':'true','BULK_DISPATCH_ENABLED':'false','HYS_UI_SANDBOX_MOCK':'1',
     'BOOTSTRAP_TOKEN':'local-ui-preview-bootstrap-only','META_ACCESS_TOKEN':'local-ui-fake-token',
     'META_APP_SECRET':'local-ui-fake-secret','META_VERIFY_TOKEN':'local-ui-fake-verify'}
env.pop('RAILWAY_ENVIRONMENT_ID',None)
python=root/'.venv'/'Scripts'/'python.exe'
children=[]
try:
    with (logs/'ui-preview-migrations.log').open('w') as log:
        subprocess.run([str(python),'-m','alembic','upgrade','head'],cwd=root/'backend',env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
    seed="from app.core import Session,Message; db=Session(); db.add_all([Message(phone='+905321234567',direction='in',body='UI önizleme kaydı: giriş ve sohbet görünümünü burada deneyebilirsiniz. Gerçek müşteri mesajı değildir.',status='received'),Message(phone='+905321234567',direction='out',body='UI önizleme kaydı: gönderim kapalıdır. Bu mesaj hiçbir telefona gönderilmedi.',status='dry_run'),Message(phone='+905331234567',direction='in',body='UI önizleme kaydı: mobilde sohbet listesine dönmeyi test edebilirsiniz.',status='received')]); db.commit(); db.close()"
    subprocess.run([str(python),'-c',seed],cwd=root/'backend',env=env,check=True,capture_output=True)
    api=subprocess.Popen([str(python),'-m','uvicorn','tests.ui_server:app','--host','127.0.0.1','--port','3002','--no-access-log'],cwd=root/'backend',env=env,stdout=(logs/'ui-preview-api.log').open('w'),stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
    children.append(api)
    for _ in range(60):
        try:
            if httpx.get('http://127.0.0.1:3002/api/health',timeout=1).status_code==200:break
        except httpx.HTTPError:pass
        if api.poll() is not None:raise RuntimeError('Isolated API failed to start')
        time.sleep(.25)
    else:raise RuntimeError('Isolated API not ready')
    result=httpx.post('http://127.0.0.1:3002/api/setup',headers={'X-HYS-Request':'1'},json={'username':'localpreview','password':'Preview123!','bootstrap_token':'local-ui-preview-bootstrap-only'})
    if result.status_code!=200:raise RuntimeError('Preview account not created')
    vite=subprocess.Popen(['node',str(root/'frontend'/'node_modules'/'vite'/'bin'/'vite.js'),'--mode','ui-preview','--host','127.0.0.1','--port','5174','--strictPort'],cwd=root/'frontend',env=env,stdout=(logs/'ui-preview-vite.log').open('w'),stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
    children.append(vite)
    for _ in range(60):
        try:
            if httpx.get('http://127.0.0.1:5174',timeout=1).status_code==200:break
        except httpx.HTTPError:pass
        if vite.poll() is not None:raise RuntimeError('Vite preview failed to start')
        time.sleep(.25)
    else:raise RuntimeError('Vite preview not ready')
    (logs/'ui-preview.json').write_text(json.dumps({'api_pid':api.pid,'frontend_pid':vite.pid,'url':'http://127.0.0.1:5174','database':str(temp/'preview.db')}),encoding='utf-8')
    print('Isolated preview ready on http://127.0.0.1:5174',flush=True)
    while all(child.poll() is None for child in children):time.sleep(2)
finally:
    for child in children:
        if child.poll() is None:child.terminate()
