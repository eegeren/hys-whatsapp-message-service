"""Local visual/interaction checks. Every API request is intercepted; no real sends."""
import json
import base64
import threading
from datetime import datetime,timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright,expect

root=Path(__file__).resolve().parents[1]
out=root/'test-results';out.mkdir(exist_ok=True)
class Handler(SimpleHTTPRequestHandler):
    def log_message(self,*args):pass
server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(root/'frontend'/'dist')))
threading.Thread(target=server.serve_forever,daemon=True).start()
now=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
requests=[]
state={'sync_error':True,'role':'admin'}
def mock(route):
    path=route.request.url.split('/api',1)[1].split('?',1)[0]
    requests.append(path)
    body={};status=200
    if path=='/setup':body={'required':False,'bootstrap_required':True}
    elif path=='/me':status=401;body={'detail':'Oturum yok'}
    elif path=='/login':body={'username':'ui-preview','role':state['role']}
    elif path=='/dashboard':body={'dry_run':True,'connection':False}
    elif path in ('/settings','/settings/client-status'):body={'dry_run':True,'live_enabled':False,'verified':False}
    elif path=='/settings/webhook':body={'https_configured':False}
    elif path=='/settings/test':body={'ok':True,'notice':'Meta bağlantı testi tamamlandı; mesaj gönderilmedi.'}
    elif path=='/templates':body=[]
    elif path=='/templates/sync':
        status=503 if state['sync_error'] else 200
        body={'detail':'Önizleme: Meta şablonları alınamadı. Daha sonra yeniden deneyin.'} if state['sync_error'] else {'synced':0}
    elif path=='/conversations':body=[{'key':'preview','phone':'+905321234567','last_body':'UI önizleme mesajı','last_at':now,'last_direction':'in','unread':0},{'key':'other','phone':'+905331234567','last_body':'İkinci UI önizleme kaydı','last_at':now,'last_direction':'in','unread':0}]
    elif path=='/conversations/other':body={'items':[{'id':2,'direction':'in','body':'İkinci UI önizleme kaydı','created':now}]}
    elif path=='/conversations/preview':body={'items':[{'id':1,'direction':'in','body':'UI önizleme mesajı. Gerçek müşteri kaydı değildir.','created':now}]}
    elif path=='/conversations/eligibility':body={'phone':'+905321234567','service_window_open':True,'sender_ready':False,'opted_out':False}
    else:raise AssertionError('Unexpected API request: '+path)
    route.fulfill(status=status,content_type='application/json',body=json.dumps(body))
try:
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='msedge',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000})
        page.clock.install()
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.route('**/api/**',mock)
        page.goto(f'http://127.0.0.1:{server.server_port}/')
        password=page.get_by_label('Parola *',exact=True)
        password.fill('Preview123!')
        page.get_by_role('button',name='Parola göster',exact=True).click()
        expect(password).to_have_attribute('type','text')
        page.get_by_role('button',name='Parola gizle',exact=True).click()
        expect(password).to_have_attribute('type','password')
        page.screenshot(path=str(out/'ui-login-desktop.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(out/'ui-login-mobile.png'),full_page=True)
        page.set_viewport_size({'width':1440,'height':1000})
        page.get_by_label('Kullanıcı adı *',exact=True).fill('ui-preview')
        page.get_by_role('button',name='Giriş yap',exact=True).click()
        page.locator('.chat-head').wait_for()
        expect(page.locator('.bubble-text')).to_contain_text('UI önizleme mesajı')
        page.screenshot(path=str(out/'ui-conversation-desktop.png'),full_page=True)
        held=[]
        page.route('**/api/conversations/preview',lambda route:held.append(route))
        page.locator('.conversation-row').nth(0).click()
        page.locator('.conversation-row').nth(1).click()
        expect(page.locator('.bubble-text')).to_contain_text('İkinci UI önizleme kaydı')
        assert held
        for route in held:route.fulfill(content_type='application/json',body=json.dumps({'items':[{'id':3,'direction':'in','body':'STALE RESPONSE MUST NOT APPEAR','created':now}]}))
        expect(page.locator('.bubble-text')).to_contain_text('İkinci UI önizleme kaydı')
        assert page.get_by_text('STALE RESPONSE MUST NOT APPEAR',exact=True).count()==0
        page.unroute('**/api/conversations/preview')
        page.locator('.conversation-row').nth(0).click()
        expect(page.locator('.bubble-text')).to_contain_text('UI önizleme mesajı')
        page.get_by_role('button',name='Yeni Mesaj',exact=True).click()
        dialog=page.get_by_role('dialog',name='Yeni mesaj')
        dialog.wait_for()
        alert=page.get_by_role('alert')
        expect(alert).to_contain_text('Meta şablonları alınamadı')
        assert alert.evaluate('el=>Number(getComputedStyle(el.parentElement).zIndex)')>100
        assert not alert.inner_text().startswith('Error:')
        page.wait_for_timeout(250)
        page.screenshot(path=str(out/'ui-notification-modal.png'),full_page=True)
        page.get_by_role('button',name='Hata bildirimini kapat').click()
        expect(alert).to_have_count(0)
        state['sync_error']=False
        dialog.get_by_role('button',name='Meta şablonlarını yenile',exact=True).click()
        status=page.locator('.notification-success')
        expect(status).to_be_visible()
        status.hover()
        page.clock.fast_forward(11000)
        expect(status).to_be_visible()
        page.mouse.move(10,10)
        page.clock.fast_forward(11000)
        expect(status).to_have_count(0)
        dialog.locator('button:not([disabled])').last.focus()
        page.keyboard.press('Tab')
        assert dialog.evaluate('el=>el.contains(document.activeElement)')
        page.keyboard.press('Escape')
        expect(dialog).to_have_count(0)
        expect(page.get_by_role('button',name='Yeni Mesaj',exact=True)).to_be_focused()
        page.set_viewport_size({'width':390,'height':844})
        page.get_by_role('button',name='Konuşma listesine dön').click()
        expect(page.locator('.conversation-list')).to_be_visible()
        page.wait_for_timeout(5500) # polling must not reopen the conversation
        expect(page.locator('.conversation-list')).to_be_visible()
        page.locator('.conversation-row').nth(0).click()
        expect(page.locator('.chat-head')).to_be_visible()
        expect(page.locator('.bubble-text')).to_contain_text('UI önizleme mesajı')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(out/'ui-conversation-mobile.png'),full_page=True)
        # Long media templates must never push history or Send out of view.
        long_body='HYS önizleme kampanyası\n\n'+('Uzun şablon satırı; gerçek müşteri mesajı değildir.\n'*45)
        template={'id':50,'name':'long_media_preview','body':long_body,'status':'APPROVED','category':'MARKETING','language':'tr','components':json.dumps([{'type':'HEADER','format':'IMAGE'},{'type':'BODY','text':long_body}])}
        layout=browser.new_page(viewport={'width':1920,'height':960})
        layout.route('**/api/**',mock)
        layout.route('**/api/templates',lambda r:r.fulfill(content_type='application/json',body=json.dumps([template])))
        layout.route('**/api/conversations/preview',lambda r:r.fulfill(content_type='application/json',body=json.dumps({'items':[{'id':7,'direction':'out','body':'Eski gönderim; UI önizlemesi','created':now,'status':'accepted'}]})))
        layout.goto(f'http://127.0.0.1:{server.server_port}/')
        layout.get_by_label('Kullanıcı adı *',exact=True).fill('ui-preview')
        layout.get_by_label('Parola *',exact=True).fill('Preview123!')
        layout.get_by_role('button',name='Giriş yap',exact=True).click()
        layout.get_by_label('Onaylı şablon',exact=True).select_option('50')
        layout.get_by_label('Veya görsel dosyası seçin',exact=True).set_input_files({'name':'synthetic.png','mimeType':'image/png','buffer':base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j0l8AAAAASUVORK5CYII=')})
        for width,height in [(1920,960),(1280,720),(390,844),(390,600)]:
            layout.set_viewport_size({'width':width,'height':height})
            layout.wait_for_timeout(100)
            history=layout.locator('.chat-history').bounding_box()
            send=layout.locator('.compose-area .send-button').bounding_box()
            assert history['height']>=100,(width,height,history)
            assert 0<=send['y'] and send['y']+send['height']<=height,(width,height,send)
            form=layout.locator('.template-compose').bounding_box()
            assert form['y']+form['height']<=send['y'],(width,height,form,send)
            assert layout.locator('.template-compose').evaluate('el=>el.scrollHeight>el.clientHeight')
            layout.locator('.template-compose').evaluate('el=>el.scrollTop=el.scrollHeight')
            assert layout.locator('.compose-area .send-button').bounding_box()['y']==send['y']
            assert layout.evaluate('document.documentElement.scrollWidth<=innerWidth')
            layout.screenshot(path=str(out/f'ui-long-template-{width}-{height}.png'),full_page=True)
        layout.close()
        # Selecting a local file does not grant permission-import privileges.
        state['role']='operator'
        operator=browser.new_page(viewport={'width':1440,'height':1000})
        operator.route('**/api/**',mock)
        operator.goto(f'http://127.0.0.1:{server.server_port}/')
        operator.get_by_label('Kullanıcı adı *',exact=True).fill('ui-preview')
        operator.get_by_label('Parola *',exact=True).fill('Preview123!')
        operator.get_by_role('button',name='Giriş yap',exact=True).click()
        operator.get_by_role('button',name='Toplu mesaj',exact=True).click()
        operator.locator('.bulk-permissions summary').click()
        picker=operator.get_by_label('Doğrulanmış izinli liste',exact=True)
        expect(picker).to_be_enabled()
        with operator.expect_file_chooser() as chooser:
            picker.click()
        chooser.value.set_files({'name':'synthetic-permissions.csv','mimeType':'text/csv','buffer':b'phone\n05321234567\n'})
        expect(operator.get_by_role('button',name='İzinli numaraları eşleştir',exact=True)).to_be_disabled()
        expect(operator.locator('.bulk-checkbox input')).to_be_disabled()
        expect(operator.get_by_text('Dosya seçebilirsiniz;',exact=False)).to_be_visible()
        assert picker.evaluate('el=>getComputedStyle(el,"::file-selector-button").backgroundColor')=='rgb(20, 125, 82)'
        operator.screenshot(path=str(out/'ui-file-controls-operator.png'),full_page=True)
        operator.get_by_role('button',name='Ayarlar',exact=True).click()
        connection_test=operator.get_by_role('button',name='Gizli bilgileri göstermeden bağlantıyı test et',exact=True)
        expect(connection_test).to_be_enabled()
        expect(operator.get_by_role('button',name='Meta şablonlarını yenile',exact=True)).to_be_disabled()
        connection_test.click()
        expect(operator.get_by_role('status').get_by_text('Meta bağlantı testi tamamlandı; mesaj gönderilmedi.',exact=True)).to_be_visible()
        operator.close()
        assert not errors,errors
        assert all('/send' not in path and '/start' not in path for path in requests)
        browser.close()
    print('UI PASS: desktop/mobile, password visibility, modal error, focus/escape, mobile back/polling. All API responses mocked; no messages sent.')
finally:
    server.shutdown();server.server_close()
