// Run against tests.staff_ui_server in a temporary database; no real Meta calls.
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.PLAYWRIGHT_MODULE_PATH||'playwright');
const browser=await chromium.launch({headless:true,...(process.env.CHROME_EXECUTABLE?{executablePath:process.env.CHROME_EXECUTABLE}:{})});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(String(e)));
 await page.goto(process.env.STAFF_UI_URL||'http://127.0.0.1:3011');
 await page.locator('input[name="username"]').fill('uiadmin');await page.locator('input[name="password"]').fill('UITestPassword123!');await page.getByRole('button',{name:'Giriş yap',exact:true}).click();
 await page.getByRole('button',{name:'Personel Duyuruları',exact:true}).click();
 await page.getByRole('heading',{name:'Personel Duyuruları',exact:true}).waitFor();
 await page.getByText('Henüz Excel yüklenmedi.',{exact:false}).waitFor();assert.equal(await page.locator('.staff-choice').count(),0);await page.getByRole('button',{name:'Kayıtlı personelleri kullan',exact:true}).click();
 await page.getByLabel('PDF yükle').setInputFiles({name:'duyuru.pdf',mimeType:'application/pdf',buffer:Buffer.from('%PDF-1.7 staff ui')});
 await page.getByText('1. duyuru.pdf',{exact:false}).waitFor();
 if(process.env.VIDEO_UI_SAMPLE){
  await page.getByLabel('Video seç ve WhatsApp için hazırla').setInputFiles(process.env.VIDEO_UI_SAMPLE);
  await page.getByText('Video hazır',{exact:true}).waitFor({timeout:60000});
  await page.locator('video').first().evaluate(video=>new Promise((resolve,reject)=>{if(video.readyState>=1)return resolve(true);video.addEventListener('loadedmetadata',()=>resolve(true),{once:true});video.addEventListener('error',()=>reject(Error('Video preview failed')),{once:true})}));
  await page.screenshot({path:'/tmp/hys-video-ready.png',fullPage:true});
  await page.getByRole('button',{name:'Önizlediğim videoyu duyuruya ekle',exact:true}).click();
  await page.getByText('2. hys-ui-sample.mp4',{exact:false}).waitFor();
 }
 await page.getByRole('button',{name:'Şablon onayları',exact:true}).click();
 await page.locator('.staff-approval-summary article').last().getByRole('button').click();
 await page.getByText('Henüz örnek video eklenmedi',{exact:true}).waitFor();
 assert(await page.getByRole('button',{name:'Devam · Mesaj metni',exact:true}).isDisabled());
 await page.getByRole('button',{name:'Dosya eklemeye git',exact:true}).click();
 await page.getByRole('heading',{name:'2. PDF Yükle',exact:true}).waitFor();
 await page.getByRole('button',{name:'Şablon onayları',exact:true}).click();
 await page.locator('.staff-approval-summary article').first().getByRole('button').click();
 await page.waitForFunction(()=>Array.from(document.querySelectorAll('.staff-approval-wizard select')).some(el=>el.value));
 assert.notEqual(await page.getByLabel('Meta incelemesi için örnek dosya').inputValue(),'');
 await page.getByRole('button',{name:'Devam · Mesaj metni',exact:true}).click();
 await page.getByText('Şablon adı ve gelişmiş ayarlar',{exact:true}).click();
 await page.getByLabel(/^Şablon adı/).fill('hys_ui_belge_basvuru');
 await page.screenshot({path:'/tmp/hys-staff-approval-desktop.png',fullPage:true});
 await page.getByRole('button',{name:'Başvuruyu önizle',exact:true}).click();
 assert(await page.getByRole('button',{name:'Simülasyon taslağını kaydet',exact:true}).isDisabled());
 await page.getByLabel('Bu şablonun simülasyon taslağı olarak kaydedilmesini onaylıyorum.').check();
 if(process.env.TEMPLATE_FAILURE_TEST){
  await page.route('**/api/templates/media-review',route=>route.fulfill({status:502,contentType:'application/json',body:JSON.stringify({detail:{message:'Örnek dosya Meta yüklemesi başarısız. Test token yetkisini kontrol edin.',phase:'uploading',safe_to_retry:true,code:190}})}));
  await page.getByRole('button',{name:'Simülasyon taslağını kaydet',exact:true}).click();
  await page.getByRole('alert').filter({hasText:'Test token yetkisini kontrol edin.'}).waitFor();
  assert.equal(await page.getByRole('button',{name:'Simülasyon taslağını kaydet',exact:true}).isDisabled(),true);
  await page.unroute('**/api/templates/media-review');
  await page.getByLabel('Bu şablonun simülasyon taslağı olarak kaydedilmesini onaylıyorum.').check();
 }
 await page.getByRole('button',{name:'Simülasyon taslağını kaydet',exact:true}).click();
 await page.getByText('Simülasyon taslağı kaydedildi.',{exact:false}).waitFor();
 await page.getByRole('button',{name:'Duyuru hazırla',exact:true}).click();
 await page.locator('.staff-message-settings>summary').click();
 await page.getByLabel('Belge başlıklı onaylı şablon').selectOption({label:'hys_personel_document · tr'});
 if(process.env.VIDEO_UI_SAMPLE)await page.getByLabel('Video başlıklı onaylı şablon').selectOption({label:'hys_personel_video · tr'});
 if(process.env.STAFF_READINESS_TEST){
  await page.route(/\/api\/staff\/announcements\/\d+\/preview$/,async route=>{const response=await route.fetch();const data=await response.json();await route.fulfill({response,json:{...data,simulation:false,send_blockers:['API servisinde personel duyurusu kuyruğu kapalı (STAFF_DISPATCH_ENABLED=false).']}})});
  await page.getByRole('button',{name:'Önizle',exact:true}).click();await page.getByRole('alert').filter({hasText:'STAFF_DISPATCH_ENABLED=false'}).waitFor();
  await page.getByLabel('Bu alıcı listesine gerçek WhatsApp gönderimini onaylıyorum.').check();assert(await page.getByRole('button',{name:'Gönder',exact:true}).isDisabled());
  await page.unroute(/\/api\/staff\/announcements\/\d+\/preview$/);
 }
 await page.getByRole('button',{name:'Önizle',exact:true}).click();await page.getByText(process.env.VIDEO_UI_SAMPLE?'1 personel · 2 dosya · 2 toplam mesaj':'1 personel · 1 dosya · 1 toplam mesaj',{exact:true}).waitFor();
 await page.locator('.staff-files-card').screenshot({path:'/tmp/hys-staff-files-clean.png'});await page.locator('.staff-send-card').screenshot({path:'/tmp/hys-staff-send-clean.png'});
 await page.setViewportSize({width:390,height:844});await page.locator('.staff-send-card').screenshot({path:'/tmp/hys-staff-send-clean-mobile.png'});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await page.setViewportSize({width:1440,height:1000});
 await page.getByRole('button',{name:'Gönder · Simülasyon',exact:true}).click();await page.getByRole('button',{name:'Duraklat',exact:true}).waitFor();
 await page.getByRole('button',{name:'Duraklat',exact:true}).click();await page.getByRole('button',{name:'Devam et',exact:true}).waitFor();
 await page.getByRole('button',{name:'Kalanları iptal et',exact:true}).click();await page.getByText('İptal edildi',{exact:true}).first().waitFor();
 await page.screenshot({path:'/tmp/hys-staff-desktop.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:'Şablon onayları',exact:true}).click();await page.screenshot({path:'/tmp/hys-staff-approval-mobile.png',fullPage:true});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await page.getByRole('button',{name:'Duyuru hazırla',exact:true}).click();await page.screenshot({path:'/tmp/hys-staff-mobile.png',fullPage:true});
 assert.deepEqual(errors,[]);assert.equal(await page.getByRole('alert').count(),0);
 console.log('Staff UI PASS: login, navigation, direct PDF upload, preview, single send, pause, cancel, desktop/mobile; no browser errors.');
}finally{await browser.close()}
