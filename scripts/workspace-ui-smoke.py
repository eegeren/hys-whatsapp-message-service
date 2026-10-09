"""Isolated browser smoke test for the simplified three-section workspace."""
import os
import json
import base64
import subprocess
import tempfile
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[1]
temp = Path(tempfile.mkdtemp(prefix='hys-ui-workspace-'))
env = {
    **os.environ,
    'DATABASE_URL': 'sqlite:///' + str(temp / 'workspace.db').replace('\\', '/'),
    'DRY_RUN': 'true',
    'APP_ENVIRONMENT':'local',
    'LOCAL_WORKER':'false',
    'DEPLOYMENT_SEND_LOCK':'true',
    'BULK_DISPATCH_ENABLED':'false',
    'LIVE_SEND_ENABLED': 'false',
    'BOOTSTRAP_TOKEN': 'workspace-ui-only-bootstrap',
    'HYS_UI_SANDBOX_MOCK': '1',
}
python = root / '.venv' / 'Scripts' / 'python.exe'
backend = root / 'backend'
subprocess.run([str(python), '-m', 'alembic', 'upgrade', 'head'], cwd=backend, env=env, check=True)
print('Temporary test database ready', flush=True)
process = subprocess.Popen(
    [str(python), '-m', 'uvicorn', 'tests.ui_server:app', '--host', '127.0.0.1', '--port', '3001'],
    cwd=backend, env=env, stdout=(temp / 'ui.log').open('w'), stderr=subprocess.STDOUT,
    creationflags=subprocess.CREATE_NO_WINDOW,
)
try:
    for _ in range(60):
        try:
            if httpx.get('http://127.0.0.1:3001/api/health', timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            pass
        if process.poll() is not None:
            raise RuntimeError((temp / 'ui.log').read_text(encoding='utf-8', errors='replace')[-4000:])
        time.sleep(.3)
    else:
        raise RuntimeError((temp / 'ui.log').read_text(encoding='utf-8', errors='replace')[-4000:])
    print('Temporary UI API ready', flush=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='msedge', headless=True)
        print('Browser launched', flush=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto('http://127.0.0.1:3001')
        page.get_by_role('heading', name='Yeni hesap oluştur', exact=True).wait_for()
        page.locator('input').nth(0).fill('workspaceadmin')
        page.locator('input').nth(1).fill('WorkspacePassword123!')
        page.get_by_label('Kurulum anahtarı *', exact=True).fill('workspace-ui-only-bootstrap')
        page.get_by_role('button', name='Hesap oluştur', exact=True).click()
        page.get_by_role('status').wait_for()
        page.get_by_label('Kullanıcı adı *',exact=True).fill('workspaceadmin')
        page.get_by_label('Parola *',exact=True).fill('WorkspacePassword123!')
        page.get_by_role('button',name='Giriş yap',exact=True).click()
        page.locator('h1').get_by_text('Mesajlar', exact=True).wait_for()
        print('Workspace login ready', flush=True)
        output = root / 'test-results'
        output.mkdir(exist_ok=True)
        rail = page.locator('.simple-rail')
        assert rail.is_visible() and rail.locator('button').count() == 4
        assert rail.bounding_box()['height'] >= 500
        page.wait_for_timeout(150)
        page.screenshot(path=str(output / 'workspace-messages.png'), full_page=True)

        assert page.get_by_role('button', name='Mesajlar').count() == 1
        assert page.get_by_role('button', name='Toplu mesaj').count() == 1
        assert page.get_by_role('button', name='Ayarlar').count() == 1
        assert page.get_by_text('Gerçek webhook mesajları burada görünür.', exact=True).count() == 1
        assert page.get_by_role('button', name='Gönder', exact=True).count() == 0

        # Template fixtures are browser-local; opening the modal never reaches Meta.
        templates = [
            {'id':1,'name':'one_field','body':'Merhaba {{1}}','status':'APPROVED','category':'MARKETING','language':'tr'},
            {'id':2,'name':'two_fields','body':'{{2}}: {{ 1 }} / {{1}}','status':'APPROVED','category':'MARKETING','language':'tr'},
            {'id':3,'name':'no_fields','body':'HYS mesajı','status':'APPROVED','category':'MARKETING','language':'tr'},
            {'id':4,'name':'media_buttons','body':'Merhaba {{1}}','status':'APPROVED','category':'MARKETING','language':'tr','components':json.dumps([
                {'type':'HEADER','format':'IMAGE'},{'type':'BODY','text':'Merhaba {{1}}'},
                {'type':'FOOTER','text':'HYS bilgilendirme'},
                {'type':'BUTTONS','buttons':[{'type':'PHONE_NUMBER','text':'Ara','phone_number':'+905321234567'},
                    {'type':'URL','text':'Sipariş','url':'https://example.test/order/{{1}}'},
                    {'type':'QUICK_REPLY','text':'STOP'}]},
            ])},
            {'id':5,'name':'video_header','body':'Video mesajı','status':'APPROVED','category':'MARKETING','language':'tr','components':json.dumps([{'type':'HEADER','format':'VIDEO'},{'type':'BODY','text':'Video mesajı'}])},
            {'id':6,'name':'document_header','body':'Belge mesajı','status':'APPROVED','category':'MARKETING','language':'tr','components':json.dumps([{'type':'HEADER','format':'DOCUMENT'},{'type':'BODY','text':'Belge mesajı'}])},
            {'id':7,'name':'text_header','body':'Gövde {{1}}','status':'APPROVED','category':'MARKETING','language':'tr','components':json.dumps([{'type':'HEADER','format':'TEXT','text':'Başlık {{1}}'},{'type':'BODY','text':'Gövde {{1}}'}])},
        ]
        page.route('**/api/templates',lambda route:route.fulfill(content_type='application/json',body=json.dumps(templates)))
        page.route('**/api/templates/sync',lambda route:route.fulfill(content_type='application/json',body='{"synced":7}'))
        page.route('https://example.test/**',lambda route:route.fulfill(status=404,body=''))
        sends=[]
        def block_send(route):
            sends.append(route.request.url)
            route.abort()
        page.route('**/api/conversations/send',block_send)
        page.route('**/api/conversations/send-with-media',block_send)
        page.get_by_role('button',name='Yeni Mesaj',exact=True).click()
        dialog=page.get_by_role('dialog',name='Yeni mesaj')
        select=dialog.locator('select')
        select.select_option('1')
        assert dialog.locator('.template-variable-field').count()==1
        dialog.get_by_label('Değişken 1',exact=True).fill('Ayşe "Hanım"')
        assert dialog.locator('.template-preview p').inner_text()=='Merhaba Ayşe "Hanım"'
        select.select_option('2')
        assert dialog.locator('.template-variable-field').count()==2
        assert dialog.get_by_label('Değişken 1',exact=True).input_value()==''
        dialog.get_by_label('Değişken 1',exact=True).fill('Ali')
        dialog.get_by_label('Değişken 2',exact=True).fill('İstanbul')
        assert dialog.locator('.template-preview p').inner_text()=='İstanbul: Ali / Ali'
        assert dialog.get_by_role('button',name='Gönder',exact=True).is_disabled()
        page.screenshot(path=str(output/'workspace-template-fields.png'),full_page=True)
        dialog.get_by_role('button',name='Mevcut sohbeti yanıtla',exact=True).click()
        dialog.get_by_label('Görsel veya video ekle',exact=True).set_input_files({
            'name':'reply.png','mimeType':'image/png','buffer':base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j0l8AAAAASUVORK5CYII='),
        })
        dialog.locator('.service-media img').wait_for()
        assert dialog.locator('.service-media img').get_attribute('src').startswith('blob:')
        assert not sends
        dialog.get_by_role('button',name='Yeni sohbet başlat',exact=True).click()
        select.select_option('3')
        assert dialog.locator('.template-variable-field').count()==0
        assert dialog.locator('.template-preview p').inner_text()=='HYS mesajı'
        select.select_option('4')
        dialog.get_by_label('Değişken 1',exact=True).fill('Ali')
        dialog.get_by_label('URL butonu 2 değişkeni',exact=True).fill('ORD-42')
        dialog.get_by_label('Veya görsel dosyası seçin',exact=True).set_input_files({
            'name':'preview.png','mimeType':'image/png',
            'buffer':base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j0l8AAAAASUVORK5CYII='),
        })
        dialog.locator('.template-preview-media').wait_for()
        assert dialog.locator('.template-preview-media').get_attribute('src').startswith('blob:')
        assert dialog.locator('.template-preview p').inner_text()=='Merhaba Ali'
        assert dialog.locator('.template-preview-footer').inner_text()=='HYS bilgilendirme'
        assert dialog.locator('.template-preview-button').count()==3
        assert 'https://example.test/order/ORD-42' in dialog.locator('.template-preview-buttons').inner_text()
        assert not sends,'Selecting a file must never submit a message or upload media'
        page.screenshot(path=str(output/'workspace-media-template.png'),full_page=True)
        select.select_option('5')
        dialog.get_by_label('Video bağlantısı',exact=True).fill('https://example.test/video.mp4')
        assert dialog.locator('video').count()==1
        assert dialog.locator('video').get_attribute('preload')=='none'
        select.select_option('6')
        dialog.get_by_label('Belge bağlantısı',exact=True).fill('https://example.test/file.pdf')
        dialog.get_by_label('Belge adı (isteğe bağlı)',exact=True).fill('katalog.pdf')
        assert dialog.locator('.template-preview-document').inner_text().endswith('katalog.pdf')
        select.select_option('7')
        dialog.get_by_label('Başlık değişkeni 1',exact=True).fill('H')
        dialog.get_by_label('Değişken 1',exact=True).fill('B')
        assert dialog.locator('.template-preview-header').inner_text()=='Başlık H'
        assert dialog.locator('.template-preview p').inner_text()=='Gövde B'
        assert not sends
        dialog.get_by_role('button',name='Kapat',exact=True).click()

        page.locator('.round-green').click()
        page.locator('.new-chat-box input').fill('05321234567')
        page.get_by_role('button',name='Sohbet aç',exact=True).click()
        composer=page.locator('.template-compose')
        composer.locator('select').select_option('2')
        composer.get_by_label('Değişken 1',exact=True).fill('Ali')
        composer.get_by_label('Değişken 2',exact=True).fill('Ankara')
        assert composer.locator('.template-preview p').inner_text()=='Ankara: Ali / Ali'
        assert not sends,'No automatic message submission is allowed'

        page.get_by_role('button', name='Toplu mesaj').click()
        page.locator('h1').get_by_text('Toplu mesaj', exact=True).wait_for()
        page.screenshot(path=str(output / 'workspace-bulk.png'), full_page=True)
        page.locator('.upload-drop input[type=file]').set_input_files({
            'name': 'alici.csv', 'mimeType': 'text/csv', 'buffer': b'telefon\n05321234567\n05331234567\n,\n+905321234567\nabc\n',
        })
        page.get_by_text('Uygun', exact=True).wait_for()
        assert page.get_by_role('button', name='Alıcıları ve mesajı kontrol et', exact=True).is_disabled()
        assert page.get_by_text('Değişkenler (JSON)',exact=True).count()==0
        # Seed only the isolated UI database; all Graph queries are mocked.
        for t in templates:
            r=page.request.post('http://127.0.0.1:3001/api/templates',headers={'X-HYS-Request':'1'},data={
                'name':t['name'],'body':t['body'],'category':'MARKETING','language':'tr',
                'components':json.loads(t.get('components','[]')),
            })
            assert r.status==200
        assert page.request.post('http://127.0.0.1:3001/api/templates/sync',headers={'X-HYS-Request':'1'}).status==200
        page.locator('.bulk-permissions summary').click()
        permission_file=page.get_by_label('Doğrulanmış izinli liste',exact=True)
        with page.expect_file_chooser() as chooser:
            permission_file.click()
        chooser.value.set_files({
            'name':'permissions.csv','mimeType':'text/csv','buffer':b'phone\n05321234567\n05331234567\n',
        })
        assert page.get_by_role('button',name='İzinli numaraları eşleştir',exact=True).is_disabled()
        page.locator('.bulk-checkbox input').check()
        with page.expect_file_chooser() as chooser:
            permission_file.click()
        chooser.value.set_files({'name':'updated-permissions.csv','mimeType':'text/csv','buffer':b'phone\n05321234567\n05331234567\n'})
        assert not page.locator('.bulk-checkbox input').is_checked()
        page.locator('.bulk-checkbox input').check()
        page.get_by_role('button',name='İzinli numaraları eşleştir',exact=True).click()
        page.get_by_role('status').get_by_text('2 izinli numara',exact=False).wait_for()
        assert permission_file.evaluate('el=>el.files.length')==0
        notices=page.locator('.notification-card').all()
        assert page.locator('.notification-stack').count()==1
        if len(notices)>1:
            boxes=[n.bounding_box() for n in notices]
            assert all(a['y']+a['height']<=b['y'] for a,b in zip(boxes,boxes[1:]))
        page.wait_for_timeout(250)
        page.screenshot(path=str(output/'workspace-file-controls.png'),full_page=True)
        page.locator('.bulk-grid .simple-card').nth(1).locator('select').select_option('1')
        page.get_by_label('Değişken 1',exact=True).fill('Ayşe')
        assert page.locator('.bulk-friendly .template-preview p').inner_text()=='Merhaba Ayşe'
        page.locator('.bulk-grid .simple-card').nth(1).locator('select').select_option('4')
        page.get_by_label('Değişken 1',exact=True).fill('HYS')
        page.get_by_label('URL butonu 2 değişkeni',exact=True).fill('KAMPANYA')
        page.get_by_label('Veya görsel dosyası seçin',exact=True).set_input_files({
            'name':'campaign.png','mimeType':'image/png','buffer':base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j0l8AAAAASUVORK5CYII='),
        })
        page.locator('.bulk-grid .template-preview-media').wait_for()
        assert not sends
        page.get_by_role('button',name='Alıcıları ve mesajı kontrol et',exact=True).click()
        confirmation=page.locator('.bulk-confirm-modal')
        confirmation.get_by_text('2 benzersiz ve izinli numara',exact=True).wait_for()
        assert confirmation.locator('img.template-preview-media').get_attribute('src').startswith('blob:')
        assert page.request.get('http://127.0.0.1:3001/api/messages').json()['total']==0
        page.screenshot(path=str(output/'workspace-bulk-confirm.png'),full_page=True)
        confirmation.get_by_role('button',name='Simülasyonu başlat',exact=True).click()
        page.locator('.campaign-progress').wait_for()
        page.get_by_role('button',name='Duraklat',exact=True).click()
        page.get_by_role('button',name='Devam ettir',exact=True).wait_for()
        page.get_by_role('button',name='Devam ettir',exact=True).click()
        page.get_by_role('button',name='Duraklat',exact=True).wait_for()
        page.once('dialog',lambda dialog:dialog.accept())
        page.get_by_role('button',name='Durdur',exact=True).click()
        page.locator('.campaign-progress').get_by_text('Durduruldu',exact=True).first.wait_for()
        assert not sends

        page.get_by_role('button', name='Ayarlar').click()
        page.locator('h1').get_by_text('Ayarlar', exact=True).wait_for()
        page.get_by_text('DRY_RUN · gerçek gönderim kapalı', exact=True).wait_for()
        page.screenshot(path=str(output / 'workspace-settings.png'), full_page=True)
        assert page.get_by_text('Gizli API bilgileri bu ekranda gösterilmez.', exact=True).count() == 1
        assert not errors, errors
        browser.close()
    print('UI PASS: HEADER/BODY/FOOTER/BUTTONS, medya dosya/link alanları, önizleme, CSV akışı; otomatik gönderim ve gerçek Meta isteği yok')
finally:
    process.terminate()
    process.wait(timeout=15)
