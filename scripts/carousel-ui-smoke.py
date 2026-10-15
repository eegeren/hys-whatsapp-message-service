"""Carousel UI checks. All API requests mocked; no real upload/send allowed."""
import base64,json,threading
from pathlib import Path
from functools import partial
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from playwright.sync_api import sync_playwright,expect

root=Path(__file__).resolve().parents[1]
out=root/'test-results';out.mkdir(exist_ok=True)
class Handler(SimpleHTTPRequestHandler):
    def log_message(self,*args):pass
server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(root/'frontend'/'dist')))
threading.Thread(target=server.serve_forever,daemon=True).start()
components=[{'type':'BODY','text':'HYS {{1}}'}, {'type':'CAROUSEL','cards':[
    {'components':[{'type':'HEADER','format':'IMAGE'},{'type':'BODY','text':'Kart {{1}}'},
                   {'type':'BUTTONS','buttons':[{'type':'URL','text':'Site','url':'https://example.com'}]}]}
    for _ in range(2)]}]
template={'id':77,'name':'mock_personel_carousel','body':'HYS {{1}}','language':'tr','category':'MARKETING','status':'APPROVED','components':json.dumps(components)}
nine_components=[components[0],{'type':'CAROUSEL','cards':[components[1]['cards'][0] for _ in range(9)]}]
nine_template={**template,'id':88,'name':'mock_nine_cards','components':json.dumps(nine_components)}
requests=[];drafts=[];reviews=[]
def mock(route):
    path=route.request.url.split('/api',1)[1].split('?',1)[0];requests.append(path)
    status=200;body={}
    if path=='/setup':body={'required':False}
    elif path=='/me':status=401;body={'detail':'Oturum yok'}
    elif path=='/login':body={'username':'mock-admin','role':'admin'}
    elif path=='/dashboard':body={'dry_run':True,'connection':False}
    elif path in ('/settings','/settings/client-status'):body={'dry_run':True,'live_enabled':False,'verified':False}
    elif path=='/settings/webhook':body={}
    elif path=='/conversations':body=[]
    elif path=='/templates/sync':body={'synced':1}
    elif path=='/templates':body=[template,nine_template]
    elif path=='/bulk/preview':
        assert 'staff' in route.request.post_data
        body={'token':'mock-preview-token','columns':[{'index':0,'name':'Telefon'}],'phone_column':0,'needs_column':False,
              'eligible_count':1,'unique_count':1,'duplicate_count':0,'invalid_count':0,'excluded_count':0,'skipped_count':0,
              'eligible_preview':[{'phone':'+905321234567'}],'excluded_rows':[],'invalid_rows':[],
              'permission_notice':'Mock: personel izinleri eşleştirildi.'}
    elif path=='/templates/carousel-review':
        data=route.request.post_data_buffer.decode('utf-8',errors='replace');reviews.append(data)
        assert 'mock_review_carousel' in data and 'one.png' in data and 'two.png' in data
        assert '"confirmed":true' in data
        body={'id':55,'name':'mock_review_carousel','status':'PENDING','notice':'Mock başvuru iletildi; hiçbir mesaj gönderilmedi.'}
    elif path=='/bulk/campaign-with-carousel':
        data=route.request.post_data_buffer.decode('utf-8',errors='replace');drafts.append(data)
        assert 'one.png' in data and 'two.png' in data and '[0,1]' in data
        assert '"card_index"' not in data  # Server generates Meta component/card positions.
        body={'campaign':{'id':987,'name':'Mock carousel','status':'draft'},'count':1,'recipients':['+905321234567'],
              'recipient_kind':'staff','cost_notice':'Mock maliyet bilinmiyor','dry_run':True}
    elif path=='/bulk/campaign/987':
        body={'campaign':{'id':987,'name':'Mock carousel','status':'draft','kind':'staff','first_approval':None,'second_approval':None},
              'total':0,'waiting':0,'failures':[],'recipients':[],'dry_run_enabled':True}
    else:raise AssertionError('Unexpected API call, no real send permitted: '+path)
    route.fulfill(status=status,content_type='application/json',body=json.dumps(body))

try:
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='msedge',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000});errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)));page.route('**/api/**',mock)
        page.goto(f'http://127.0.0.1:{server.server_port}/')
        page.get_by_label('Kullanıcı adı *',exact=True).fill('mock-admin')
        page.get_by_label('Parola *',exact=True).fill('Preview123!')
        page.get_by_role('button',name='Giriş yap',exact=True).click()
        page.get_by_role('button',name='Toplu mesaj',exact=True).click()
        page.get_by_label('Alıcı listesi').select_option('staff')
        assert page.locator('.bulk-permissions').count()==0
        page.locator('.upload-drop input').set_input_files({'name':'staff.csv','mimeType':'text/csv','buffer':b'Telefon\n05321234567\n'})
        page.get_by_label('Onaylı mesaj şablonu').select_option('77')
        page.get_by_label('Onaylı mesaj şablonu').select_option('88')
        expect(page.locator('.bulk-grid .carousel-card')).to_have_count(9)
        for width,height in ((1920,1000),(1440,1000),(1024,900),(390,844)):
            page.set_viewport_size({'width':width,'height':height})
            assert page.evaluate('''()=>{
                const area=document.querySelector('.bulk-page');
                const cards=[...document.querySelectorAll('.bulk-grid .carousel-card')];
                const grid=document.querySelector('.bulk-grid');
                const upload=grid.firstElementChild.getBoundingClientRect();
                return area.scrollWidth<=area.clientWidth+1 && document.documentElement.scrollWidth<=innerWidth+1
                    && upload.width>=Math.min(290,grid.clientWidth)
                    && cards.every(card=>card.scrollWidth<=card.clientWidth+1 && card.getBoundingClientRect().width>=Math.min(270,grid.clientWidth-45));
            }'''),f'Carousel layout overflow or compressed cards at {width}'
            page.screenshot(path=str(out/f'carousel-nine-{width}.png'),full_page=True)
        page.set_viewport_size({'width':1440,'height':1000})
        page.get_by_label('Onaylı mesaj şablonu').select_option('77')
        expect(page.locator('.bulk-grid .carousel-card')).to_have_count(2)
        check=page.get_by_role('button',name='Alıcıları ve mesajı kontrol et',exact=True)
        expect(check).to_be_disabled()
        png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aVZkAAAAASUVORK5CYII=')
        page.get_by_label('Tüm kartların dosyalarını seçin').set_input_files([
            {'name':'one.png','mimeType':'image/png','buffer':png},
            {'name':'two.png','mimeType':'image/png','buffer':png}])
        for i,field in enumerate(page.get_by_label('Değişken 1',exact=True).all()):field.fill('Mock '+str(i))
        expect(check).to_be_enabled()
        expect(page.locator('.carousel-card img')).to_have_count(2)
        page.screenshot(path=str(out/'carousel-desktop.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(out/'carousel-mobile.png'),full_page=True)
        check.click()
        expect(page.locator('.bulk-confirm-modal')).to_be_visible()
        expect(page.locator('.bulk-confirm-modal .carousel-card')).to_have_count(2)
        page.locator('.bulk-confirm-modal').get_by_role('button',name='Vazgeç',exact=True).click()
        page.locator('.carousel-create summary').click()
        creator=page.locator('.carousel-create')
        creator.get_by_label('Şablon adı').fill('mock_review_carousel')
        creator.get_by_label('Ana mesaj metni').fill('HYS {{1}}')
        creator.get_by_label('Ana metin değişken 1 için örnek').fill('Duyuru')
        creator.get_by_label('Görsel kartı sayısı').select_option('2')
        creator.get_by_label('Kart 1 açıklaması').fill('Birinci görsel')
        creator.get_by_label('Kart 2 açıklaması').fill('İkinci görsel')
        creator.get_by_label('Tüm kartların örnek görsellerini seçin').set_input_files([
            {'name':'one.png','mimeType':'image/png','buffer':png},
            {'name':'two.png','mimeType':'image/png','buffer':png}])
        creator.get_by_role('button',name='Başvuruyu kontrol et',exact=True).click()
        review=page.get_by_role('dialog',name='Carousel şablon başvurusunu onayla')
        expect(review).to_be_visible()
        expect(review.get_by_role('button',name='Meta onayına gönder',exact=True)).to_be_disabled()
        assert not reviews
        review.locator('input[type=checkbox]').check()
        page.screenshot(path=str(out/'carousel-review-confirm.png'),full_page=True)
        review.get_by_role('button',name='Meta onayına gönder',exact=True).click()
        expect(creator.get_by_role('status')).to_contain_text('PENDING')
        assert len(reviews)==1
        assert len(drafts)==1 and not errors,errors
        assert not any(path.endswith(('/start','/test','/send')) for path in requests)
        browser.close()
    print('Carousel UI passed: personel list, multi-file cards, inputs, previews, confirmation, mobile, explicit Meta review confirmation; no real send.')
finally:server.shutdown();server.server_close()
