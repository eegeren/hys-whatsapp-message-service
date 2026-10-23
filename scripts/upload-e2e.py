"""Real Chromium -> HTTP -> FastAPI upload regression, isolated DB, no WhatsApp."""
import os,tempfile,subprocess,time,json,hashlib,socket
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright
root=Path(__file__).resolve().parents[1]
temp=Path(tempfile.mkdtemp(prefix='hys-upload-e2e-'))
env={**os.environ,'HYS_UPLOAD_E2E':'1','DATABASE_URL':'sqlite:///'+str(temp/'test.db').replace('\\','/'),'DRY_RUN':'true','LIVE_SEND_ENABLED':'false','DEPLOYMENT_SEND_LOCK':'true','LOCAL_WORKER':'false','BOOTSTRAP_TOKEN':'upload-e2e-only','APP_ENVIRONMENT':'local','STAFF_UPLOAD_ORIGIN':'','VIDEO_PROCESSING_ENABLED':'true'}
module=root/'test-results/upload-api.mjs'
subprocess.run(['node','--input-type=module','-e',"import ts from 'typescript';import fs from 'node:fs';fs.writeFileSync('../test-results/upload-api.mjs',ts.transpile(fs.readFileSync('src/api.ts','utf8'),{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext}));"],cwd=root/'frontend',check=True)
with socket.socket() as sock:
    sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
base=f'http://127.0.0.1:{port}'
logpath=root/'test-results/upload-e2e.log'
with logpath.open('w',encoding='utf-8') as logs:
    server=subprocess.Popen([str(root/'.venv/Scripts/python.exe'),'-m','uvicorn','tests.upload_e2e_server:app','--host','127.0.0.1','--port',str(port),'--no-access-log'],cwd=root/'backend',env=env,stdout=logs,stderr=logs,creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        for _ in range(80):
            if server.poll() is not None:raise RuntimeError('Isolated test server exited')
            try:
                if httpx.get(base+'/api/health',timeout=1).status_code==200:break
            except httpx.HTTPError:pass
            time.sleep(.25)
        else:raise RuntimeError('Local test server did not start')
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='msedge',headless=True)
            page=browser.new_page();page.goto(base+'/api/health')
            result=page.evaluate(r"""async code=>{
                const m=await import('data:text/javascript;base64,'+btoa(unescape(encodeURIComponent(code))));
                await m.api('/setup','POST',{username:'tester',password:'UploadTest123!',bootstrap_token:'upload-e2e-only'});
                await m.api('/login','POST',{username:'tester',password:'UploadTest123!'});
                const raw=new Uint8Array(9670000);raw.set([0,0,0,24,102,116,121,112,105,115,111,109]);raw[raw.length-1]=117;
                const file=new File([raw],'fixture.mp4',{type:'video/mp4'});
                const created=await m.api('/video/jobs','POST',{filename:file.name,size:file.size});
                await m.uploadBinary(created.upload_url,file);
                await fetch('/_test/process',{method:'POST'});
                const job=await m.api('/video/jobs/'+created.id);
                const ready=await m.preparedVideoFile(job);
                const probe=new FormData();probe.append('file',ready);probe.append('browser_bytes',String(ready.size));
                const inspected=await m.api('/media/inspect','POST',probe);
                // Dispatch is replaced by byte capture in this test-only server.
                const single=new FormData();single.append('file',ready);single.append('data',JSON.stringify({phone:'+905321234567'}));
                // Production endpoint rejects DRY_RUN before dispatch, proving it stays locked.
                let singleLocked=false;try{await m.api('/conversations/send-with-media','POST',single)}catch(e){singleLocked=String(e).includes('DRY_RUN')}
                const a=await m.api('/staff/announcements','POST',{name:'Upload fixture'});
                const pdf=new FormData();pdf.append('file',new File(['%PDF-1.7'],'test.pdf',{type:'application/pdf'}));
                await m.api('/staff/announcements/'+a.id+'/assets','POST',pdf);
                const staff=new FormData();staff.append('file',ready);
                await m.api('/staff/announcements/'+a.id+'/assets','POST',staff);
                const staffResult=await m.api('/staff/announcements/'+a.id);
                const permission=new FormData();permission.append('file',new File(['Telefon\n05321234567\n'],'p.csv',{type:'text/csv'}));permission.append('confirmed','true');
                await m.api('/bulk/permissions/import','POST',permission);
                const recipients=new FormData();recipients.append('file',new File(['Telefon\n05321234567\n'],'r.csv',{type:'text/csv'}));
                const preview=await m.api('/bulk/preview','POST',recipients);
                const tid=await (await fetch('/_test/template')).json();
                const bulk=new FormData();bulk.append('file',ready);bulk.append('data',JSON.stringify({token:preview.token,template_id:tid.id}));
                const campaign=await m.api('/bulk/campaign-with-media','POST',bulk);
                const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await ready.arrayBuffer()))).map(x=>x.toString(16).padStart(2,'0')).join('');
                return {browser_bytes:file.slice().size,prepared_bytes:ready.slice().size,inspected,staff_files:staffResult.files.length,bulk_status:campaign.campaign.status,single_locked:singleLocked,sha256:digest};
            }""",module.read_text(encoding='utf-8'))
            assert result['browser_bytes']==result['prepared_bytes']==result['inspected']['received_bytes']==9670000,result
            raw=b'\x00\x00\x00\x18ftypisom'+b'\x00'*(9670000-13)+b'u'
            assert result['sha256']==hashlib.sha256(raw).hexdigest(),result
            assert result['staff_files']==2 and result['bulk_status']=='draft' and result['single_locked'],result
            browser.close()
            (root/'test-results/upload-e2e.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(result,ensure_ascii=False))
    finally:
        server.terminate();server.wait(timeout=10)
text=logpath.read_text(encoding='utf-8')
assert 'received_bytes=9670000 http_status=200' in text,text[-2000:]
assert 'upload-e2e-only' not in text and 'UploadTest123!' not in text
print('Browser HTTP upload E2E passed; no WhatsApp messages sent.')
