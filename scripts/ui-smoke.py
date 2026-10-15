"""UI smoke test against a separate temporary database; never seeds user data."""
import os,sys,tempfile,subprocess,time,json,hashlib,hmac
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright
root=Path(__file__).resolve().parents[1];temp=Path(tempfile.mkdtemp(prefix='hys-ui-'))
env={**os.environ,'DATABASE_URL':'sqlite:///'+str(temp/'ui.db').replace('\\','/'),'DRY_RUN':'true','LIVE_SEND_ENABLED':'false','BOOTSTRAP_TOKEN':'ui-smoke-only-bootstrap','HYS_UI_SANDBOX_MOCK':'1'}
python=root/'.venv/Scripts/python.exe';backend=root/'backend'
subprocess.run([str(python),'-m','alembic','upgrade','head'],cwd=backend,env=env,check=True)
process=subprocess.Popen([str(python),'-m','uvicorn','tests.ui_server:app','--host','127.0.0.1','--port','3001'],cwd=backend,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
try:
    for _ in range(60):
        try:
            if httpx.get('http://127.0.0.1:3001/api/health').status_code==200:break
        except httpx.HTTPError:pass
        time.sleep(.3)
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='msedge',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1050})
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto('http://127.0.0.1:3001');page.get_by_text('Yönetim merkezinizi kurun',exact=True).wait_for()
        page.locator('input').nth(0).fill('testadmin');page.locator('input').nth(1).fill('UITestPassword123!');page.get_by_label('Kurulum anahtarı *',exact=True).fill('ui-smoke-only-bootstrap');page.get_by_role('button',name='Yönetici hesabı oluştur',exact=True).click()
        page.get_by_role('heading',name='Genel Bakış',exact=True).wait_for()
        output=root/'test-results';output.mkdir(exist_ok=True)
        page.screenshot(path=str(output/'dashboard.png'),full_page=True)
        for name in ['Müşteriler','Müşteri İzinleri','Müşteri Kampanyaları','Personeller','Mağazalar','Personel Duyuruları','Mesaj Şablonları','Gelen Mesajlar','Gönderim Geçmişi','Raporlar','WhatsApp API Ayarları','Sistem Ayarları']:
            page.locator('nav').get_by_role('button',name=name,exact=True).click();page.get_by_role('heading',name=name,exact=True).wait_for();page.wait_for_timeout(150)
            assert page.locator('[role=alert]').count()==0,name
        payload={'object':'whatsapp_business_account','entry':[{'id':'654321','changes':[{'field':'messages','value':{'metadata':{'phone_number_id':'123456'},'messages':[{'id':'wamid.ui-inbound','from':'905329999999','type':'text','text':{'body':'Webhook UI gelen mesaj testi'}}]}}]}]}
        raw=json.dumps(payload).encode();signature='sha256='+hmac.new(b'ui-test-only-secret',raw,hashlib.sha256).hexdigest()
        assert httpx.post('http://127.0.0.1:3001/api/webhook',content=raw,headers={'X-Hub-Signature-256':signature}).status_code==200
        page.locator('nav').get_by_role('button',name='Gelen Mesajlar',exact=True).click()
        page.get_by_text('Webhook UI gelen mesaj testi',exact=True).wait_for()
        page.screenshot(path=str(output/'incoming-webhook.png'),full_page=True)
        page.locator('nav').get_by_role('button',name='Müşteriler',exact=True).click()
        page.get_by_role('button',name='Müşteri ekle',exact=True).click()
        dialog=page.get_by_role('dialog');dialog.get_by_label('Ad *',exact=True).fill('UI Test');dialog.get_by_label('Telefon (+90…) *',exact=True).fill('05321234567');dialog.get_by_role('button',name='Kaydet',exact=True).click()
        page.get_by_text('UI Test',exact=True).wait_for();page.reload();page.locator('nav').get_by_role('button',name='Müşteriler',exact=True).click();page.get_by_text('UI Test',exact=True).wait_for()
        page.screenshot(path=str(output/'customers.png'),full_page=True)
        page.get_by_role('button',name='İzin',exact=True).click();dialog=page.get_by_role('dialog')
        dialog.get_by_label('İzin kanıtını inceleyerek doğruladım',exact=True).check();dialog.get_by_label('İzin kaynağı *',exact=True).fill('UI test formu');dialog.get_by_label('İzin kanıtı / belge referansı *',exact=True).fill('Yalnızca ayrı test veritabanı');dialog.get_by_label('İzin tarihi *',exact=True).fill('2026-10-08');dialog.get_by_label('İYS onay belgesini manuel doğruladım (API sorgusu değildir)',exact=True).check();dialog.get_by_role('button',name='Kaydet',exact=True).click();page.get_by_text('Uygun',exact=True).wait_for()
        page.locator('nav').get_by_role('button',name='Mesaj Şablonları',exact=True).click();page.get_by_role('button',name='Şablon oluştur',exact=True).click();dialog=page.get_by_role('dialog')
        dialog.get_by_label('Şablon adı (küçük harf / alt çizgi) *',exact=True).fill('ui_test');dialog.get_by_label('Mesaj metni / değişkenler *',exact=True).fill('Merhaba {{musteri_adi}}');dialog.get_by_role('button',name='Kaydet',exact=True).click();page.get_by_text('ui_test',exact=True).wait_for()
        page.locator('nav').get_by_role('button',name='Müşteri Kampanyaları',exact=True).click();page.get_by_role('button',name='Yeni kampanya',exact=True).click();dialog=page.get_by_role('dialog');dialog.get_by_label('Kampanya adı *',exact=True).fill('UI test kampanyası');dialog.get_by_label('Mesaj şablonu *',exact=True).select_option(label='ui_test · Yerel taslak');dialog.get_by_role('button',name='Kaydet',exact=True).click();page.get_by_text('UI test kampanyası',exact=True).wait_for()
        page.get_by_role('button',name='Önizle',exact=True).click();dialog=page.get_by_role('dialog');dialog.get_by_text('1 uygun alıcı',exact=True).wait_for();dialog.get_by_role('button',name='Simülasyonu kuyruğa al',exact=True).click()
        subprocess.run([str(python),'-c','from app.worker import dispatch_local; dispatch_local()'],cwd=backend,env=env,check=True)
        page.locator('nav').get_by_role('button',name='Gönderim Geçmişi',exact=True).click();page.get_by_role('table').get_by_text('DRY_RUN',exact=True).wait_for()
        page.locator('nav').get_by_role('button',name='WhatsApp API Ayarları',exact=True).click()
        page.get_by_role('heading',name='Test Mesajı Gönder',exact=True).wait_for()
        page.get_by_label('Test ekranındaki Phone Number ID',exact=True).fill('123456')
        page.get_by_label('Test ekranındaki WABA ID',exact=True).fill('654321')
        page.get_by_label('Bu iki kimliği Meta Developers test ekranında elle karşılaştırdım.',exact=True).check()
        page.get_by_label('Bu numara Meta tarafından sağlanan geliştirme test numarasıdır; işletmenin üretim numarası değildir.',exact=True).check()
        page.get_by_role('button',name='Meta test kimliklerini onayla',exact=True).click()
        page.get_by_label('Test alıcı numarası (E.164)',exact=True).fill('+905321234567')
        page.get_by_label('Bu kendi telefon numaramdır ve Meta test ekranında ekleyip doğruladım.',exact=True).check()
        page.get_by_role('button',name='Kendi numaramı test izin listesine kaydet',exact=True).click()
        page.get_by_text('Kendi test numaranız yerel META_TEST_RECIPIENTS izin listesine kaydedildi. Mesaj gönderilmedi; yeniden başlatma gerekmez.',exact=True).wait_for()
        page.get_by_role('button',name='Test Mesajı Gönder',exact=True).click()
        dialog=page.get_by_role('dialog',name='Test mesajı gönderimini onayla',exact=True)
        dialog.wait_for()
        assert dialog.get_by_role('button',name='Onayla ve test mesajını gönder',exact=True).is_disabled()
        dialog.get_by_label('Bu alıcıyı Meta panelinde test alıcısı olarak ekleyip doğruladım.',exact=True).check()
        assert dialog.get_by_role('button',name='Onayla ve test mesajını gönder',exact=True).is_disabled()
        dialog.get_by_label('Bu numaraya gerçek bir test mesajı gönderilmesini onaylıyorum.',exact=True).check()
        dialog.get_by_role('button',name='Onayla ve test mesajını gönder',exact=True).click()
        page.get_by_role('table').get_by_text('wamid.ui-test-only',exact=True).wait_for()
        page.get_by_role('table').get_by_text('Bilinmiyor · webhook bekleniyor',exact=True).wait_for()
        page.screenshot(path=str(output/'test-message.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':844});page.reload();page.get_by_role('heading',name='Genel Bakış',exact=True).wait_for();page.screenshot(path=str(output/'mobile.png'),full_page=True)
        assert not errors,errors
        browser.close();print('UI PASS: kurulum, 13 ekran, kayit/yenileme, izin, sablon, kampanya, DRY_RUN, ayri test mesaji/onaylari/maketi, mobil; konsol hatasi yok; gercek Meta cagrisi yok')
finally:
    process.terminate();process.wait(timeout=15)
