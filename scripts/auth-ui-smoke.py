"""Headless account screens with fake API responses; no real accounts or messages."""
import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright

root=Path(__file__).resolve().parents[1]
class Handler(SimpleHTTPRequestHandler):
    def log_message(self,*args):pass

server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(root/'frontend'/'dist')))
threading.Thread(target=server.serve_forever,daemon=True).start()
state={'first':False,'role':'admin'}
calls=[]
def mock(route):
    request=route.request
    path=request.url.split('/api',1)[1]
    calls.append((request.method,path))
    status=200
    if path=='/setup' and request.method=='GET':body={'required':state['first'],'bootstrap_required':True}
    elif path=='/me':status=401;body={'detail':'Oturum yok'}
    elif path=='/login':body={'username':'fake-user','role':state['role']}
    elif path in ('/setup','/users','/logout'):body={'ok':True}
    else:raise AssertionError('Unexpected API endpoint')
    route.fulfill(status=status,content_type='application/json',body=json.dumps(body))

try:
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='msedge',headless=True)
        def screen():
            page=browser.new_page()
            page.route('**/api/**',mock)
            page.goto(f'http://127.0.0.1:{server.server_port}/')
            return page
        page=screen()
        page.get_by_role('button',name='Yeni hesap oluştur',exact=True).click()
        page.get_by_label('Kullanıcı adı *',exact=True).fill('fake-operator')
        page.get_by_label('Parola *',exact=True).fill('FakeStrongPassword123!')
        page.get_by_label('Yönetici kullanıcı adı *',exact=True).fill('fake-admin')
        page.get_by_label('Yönetici parolası *',exact=True).fill('FakeAdminPassword123!')
        page.get_by_role('button',name='Hesap oluştur',exact=True).click()
        page.get_by_role('status').wait_for()
        page.get_by_role('button',name='Giriş yap',exact=True).wait_for()
        assert calls[-3:]==[('POST','/login'),('POST','/users'),('POST','/logout')]
        page.close()

        state['role']='operator';calls.clear();page=screen()
        page.get_by_role('button',name='Yeni hesap oluştur',exact=True).click()
        page.get_by_label('Kullanıcı adı *',exact=True).fill('fake-operator')
        page.get_by_label('Parola *',exact=True).fill('FakeStrongPassword123!')
        page.get_by_label('Yönetici kullanıcı adı *',exact=True).fill('fake-operator')
        page.get_by_label('Yönetici parolası *',exact=True).fill('FakeAdminPassword123!')
        page.get_by_role('button',name='Hesap oluştur',exact=True).click()
        page.get_by_role('alert').wait_for()
        assert ('POST','/users') not in calls
        page.close()

        state['first']=True;calls.clear();page=screen()
        page.get_by_label('Kullanıcı adı *',exact=True).fill('fake-admin')
        page.get_by_label('Parola *',exact=True).fill('FakeStrongPassword123!')
        page.get_by_label('Kurulum anahtarı *',exact=True).fill('fake-bootstrap-only')
        page.get_by_role('button',name='Hesap oluştur',exact=True).click()
        page.get_by_role('status').wait_for()
        assert ('POST','/setup') in calls and ('POST','/users') not in calls
        assert all(path not in ('/messages','/messaging/send') for _,path in calls)
        browser.close()
        print('3 account UI flows passed with mock API; no real accounts or messages.')
finally:
    server.shutdown();server.server_close()
