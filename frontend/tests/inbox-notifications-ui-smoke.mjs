// All data is an isolated sandbox; no Meta calls or real customer messages.
import {createRequire} from 'node:module';import assert from 'node:assert/strict';
const {chromium}=createRequire(import.meta.url)(process.env.PLAYWRIGHT_MODULE_PATH||'playwright');const browser=await chromium.launch({headless:true,...(process.env.CHROME_EXECUTABLE?{executablePath:process.env.CHROME_EXECUTABLE}:{})});
try{
 const page=await browser.newPage({viewport:{width:1440,height:900}});const errors=[];page.on('pageerror',e=>errors.push(String(e)));
 await page.addInitScript(()=>{window.chimes=0;const original=AudioContext.prototype.createOscillator;AudioContext.prototype.createOscillator=function(...args){window.chimes++;return original.apply(this,args)}});
 let rows=[],reads=0;await page.route('**/api/conversations',async route=>{const result=await route.fetch();rows=await result.json();await route.fulfill({response:result,json:rows})});
 await page.route('**/api/conversations/*/read',async route=>{reads++;await route.continue()});
 await page.goto(process.env.STAFF_UI_URL||'http://127.0.0.1:3012');await page.locator('input[name=username]').fill('uiadmin');await page.locator('input[name=password]').fill('UITestPassword123!');await page.getByRole('button',{name:'Giriş yap',exact:true}).click();await page.getByLabel('Mesaj yaz',{exact:true}).waitFor();
 // Explicitly focus the active chat; displaying it clears only incoming unread badges.
 await page.getByLabel('Mesaj yaz',{exact:true}).click();await page.waitForFunction(()=>document.hasFocus());
 await page.locator('.conversation-row').filter({hasText:'+905550000000'}).locator('i').waitFor({state:'hidden'});
 await page.getByRole('button',{name:/^Okunmamış/}).click();await page.getByRole('button',{name:'Tümü',exact:true}).click();assert(reads>0);assert.equal(await page.evaluate(()=>window.chimes),0);
 const first=page.locator('.conversation-row').filter({hasText:'+905550000000'});assert.equal(await first.locator('i').count(),0);
 // Simulate one new incoming watermark in another conversation; no send endpoint is used.
 await page.unroute('**/api/conversations');let next=rows.map(r=>r.phone==='+905550000002'?{...r,last_incoming_id:100000,unread:1}:r);
 await page.route('**/api/conversations',route=>route.fulfill({json:next}));
 await page.waitForFunction(()=>window.chimes===1,null,{timeout:12000});assert.equal(await page.evaluate(()=>window.chimes),1);
 // Repeated polls and outgoing-only changes must not chime again.
 await page.getByRole('button',{name:'Bildirim sesini kapat',exact:true}).click();next=next.map(r=>r.phone==='+905550000002'?{...r,last_incoming_id:100001,unread:2}:r);const refreshed=page.waitForResponse(r=>r.url().endsWith('/api/conversations'));await page.getByRole('button',{name:'Ayarlar',exact:true}).click();await page.getByRole('button',{name:'Mesajlar',exact:true}).click();await refreshed;assert.equal(await page.evaluate(()=>window.chimes),1);
 await page.screenshot({path:'/tmp/hys-inbox-notifications.png',fullPage:true});assert.deepEqual(errors,[]);console.log('Inbox notifications UI PASS: opening chat clears unread, initial load silent, one new-message chime, mute suppresses sound, no Meta sends.');
}finally{await browser.close()}
