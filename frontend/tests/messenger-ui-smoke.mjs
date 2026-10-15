// Isolated sandbox only; live Meta calls are forbidden by staff_ui_server.
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.PLAYWRIGHT_MODULE_PATH||'playwright');
const browser=await chromium.launch({headless:true,...(process.env.CHROME_EXECUTABLE?{executablePath:process.env.CHROME_EXECUTABLE}:{})});
try{
 const page=await browser.newPage({viewport:{width:1440,height:900}});const errors=[];page.on('pageerror',e=>errors.push(String(e)));
 await page.goto(process.env.STAFF_UI_URL||'http://127.0.0.1:3012');
 await page.locator('input[name=username]').fill('uiadmin');await page.locator('input[name=password]').fill('UITestPassword123!');await page.getByRole('button',{name:'Giriş yap',exact:true}).click();
 await page.getByLabel('Mesaj yaz',{exact:true}).waitFor();
 const geometry=()=>page.evaluate(()=>({composer:document.querySelector('.wa-composer').getBoundingClientRect().height,history:document.querySelector('.chat-history').getBoundingClientRect().height,overflow:document.documentElement.scrollWidth>innerWidth}));
 let g=await geometry();assert(g.composer<120);assert(g.history>500);assert(!g.overflow);
 assert.equal(await page.getByLabel('Görsel ekle',{exact:true}).isVisible(),false);
 await page.getByLabel('Mesaj yaz',{exact:true}).fill('Kontrol mesajı — gönderilmeyecek');assert(await page.getByLabel('Mesajı gönder',{exact:true}).isDisabled());
 await page.screenshot({path:'/tmp/hys-messenger-desktop.png',fullPage:true});
 await page.getByLabel('Dosya ekle',{exact:true}).click();await page.getByLabel('Görsel ekle',{exact:true}).waitFor({state:'visible'});
 await page.getByLabel('Görsel ekle',{exact:true}).setInputFiles({name:'test.png',mimeType:'image/png',buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=','base64')});
 await page.screenshot({path:'/tmp/hys-messenger-attachments.png',fullPage:true});await page.keyboard.press('Escape');assert.equal(await page.getByLabel('Görsel ekle',{exact:true}).isVisible(),false);assert.equal(await page.getByLabel('Mesaj yaz',{exact:true}).inputValue(),'Kontrol mesajı — gönderilmeyecek');
 await page.getByLabel('Seçilen eki kaldır').click();assert.equal(await page.locator('.wa-attachment-strip').count(),0);
 if(process.env.VIDEO_UI_SAMPLE){
  await page.getByLabel('Dosya ekle',{exact:true}).click();await page.getByRole('tab',{name:'Video',exact:true}).click();await page.getByLabel('Video seç ve WhatsApp için hazırla').setInputFiles(process.env.VIDEO_UI_SAMPLE);await page.getByLabel('Ek panelini kapat').click();
  await page.locator('.wa-file-summary strong').filter({hasText:'hys-ui-sample.mp4'}).waitFor({timeout:60000});await page.locator('.wa-file-summary').click();await page.locator('.service-media video').waitFor({state:'visible'});await page.locator('.service-media video').evaluate(v=>new Promise((resolve,reject)=>{if(v.readyState>=1)return resolve(true);v.addEventListener('loadedmetadata',()=>resolve(true),{once:true});v.addEventListener('error',()=>reject(Error('Preview failed')),{once:true})}));await page.getByLabel('Ek panelini kapat').click();await page.getByLabel('Seçilen eki kaldır').click();
 }
 await page.getByLabel('Sohbetlerde ara').fill('bulunmayan');await page.getByText('Eşleşen sohbet yok',{exact:true}).waitFor();await page.getByLabel('Aramayı temizle').click();assert.equal(await page.locator('.conversation-row').count(),12);
 await page.getByRole('button',{name:/^Okunmamış/}).click();assert.equal(await page.locator('.conversation-row').count(),6);await page.getByRole('button',{name:'Tümü',exact:true}).click();
 await page.locator('.conversation-row').filter({hasText:'+905550000001'}).click();await page.getByRole('button',{name:'Sohbet başlatmak için şablon seçin',exact:true}).click();await page.getByLabel('Onaylı şablon',{exact:true}).selectOption({index:1});await page.getByLabel('Şablon panelini kapat').click();assert(await page.getByLabel('Mesajı gönder',{exact:true}).isDisabled());
 await page.setViewportSize({width:390,height:844});await page.getByLabel('Konuşma listesine dön').click();await page.locator('.conversation-row').first().click();await page.getByLabel('Mesaj yaz',{exact:true}).waitFor();g=await geometry();assert(g.history>400);assert(g.composer<120);assert(!g.overflow);await page.screenshot({path:'/tmp/hys-messenger-mobile.png',fullPage:true});
 await page.getByLabel('Dosya ekle',{exact:true}).click();await page.getByRole('tab',{name:'Video',exact:true}).click();await page.getByLabel('Video seç ve WhatsApp için hazırla').waitFor({state:'visible'});await page.screenshot({path:'/tmp/hys-messenger-mobile-attachments.png',fullPage:true});await page.getByLabel('Ek panelini kapat').click();
 assert.deepEqual(errors,[]);console.log('Messenger UI PASS: compact desktop/mobile layout, search, unread filter, drafts, image selection/removal, attachment tabs, templates, send lock; no browser errors.');
}finally{await browser.close()}
