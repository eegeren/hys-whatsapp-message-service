// Isolated sandbox only. Never calls WhatsApp sending endpoints.
import {createRequire} from 'node:module';
import assert from 'node:assert/strict';
const {chromium}=createRequire(import.meta.url)(process.env.PLAYWRIGHT_MODULE_PATH||'playwright');
const browser=await chromium.launch({headless:true,...(process.env.CHROME_EXECUTABLE?{executablePath:process.env.CHROME_EXECUTABLE}:{})});
try{
 const page=await browser.newPage({viewport:{width:1440,height:900}}),errors=[];
 page.on('pageerror',e=>errors.push(String(e)));
 await page.addInitScript(()=>{window.dateFormatCalls=0;for(const method of ['toLocaleDateString','toLocaleTimeString']){const original=Date.prototype[method];Date.prototype[method]=function(...args){window.dateFormatCalls++;return original.apply(this,args)}}});
 await page.route('**/api/conversations/send**',()=>{throw Error('No real or simulated sends allowed')});
 await page.goto(process.env.STAFF_UI_URL||'http://127.0.0.1:3012');
 await page.locator('input[name=username]').fill('uiadmin');await page.locator('input[name=password]').fill('UITestPassword123!');await page.getByRole('button',{name:'Giriş yap',exact:true}).click();
 const composer=page.getByLabel('Mesaj yaz',{exact:true});await composer.waitFor();
 await composer.click();await page.waitForTimeout(300);
 const before=await page.evaluate(()=>window.dateFormatCalls);
 await composer.pressSequentially('Taslak korunmalı — gönderilmeyecek',{delay:5});
 const repeated=await page.evaluate(()=>window.dateFormatCalls)-before;
 assert(repeated<10,'Typing must not reformat all conversation/message dates: '+repeated);
 // Keep one slow poll pending across two subsequent ticks. Polling must not pile up.
 let requests=0,release;
 const gate=new Promise(resolve=>release=resolve);
 await page.route('**/api/conversations',async route=>{requests++;if(requests===1)await gate;await route.continue()});
 await page.waitForFunction(()=>!!document.querySelector('.conversation-row'));
 const deadline=Date.now()+12000;
 while(!requests&&Date.now()<deadline)await page.waitForTimeout(100);
 assert.equal(requests,1,'Expected the first automatic poll');
 await page.waitForTimeout(11000);assert.equal(requests,1,'Slow list request must not accumulate overlapping polls');
 const resumed=page.waitForResponse(r=>r.url().endsWith('/api/conversations')&&r.status()===200);
 release();await resumed;
 assert.equal(await composer.inputValue(),'Taslak korunmalı — gönderilmeyecek');
 // Polling resumes after the slow response, and changing conversations still works.
 await page.waitForResponse(r=>r.url().endsWith('/api/conversations')&&r.status()===200,{timeout:10000});
 assert(requests>=2);
 await page.locator('.conversation-row').filter({hasText:'+905550000002'}).click();
 await composer.waitFor();await page.locator('.chat-bubble').first().waitFor();
 assert.deepEqual(errors,[]);
 console.log('Inbox performance UI PASS: slow polling does not overlap, polling recovers, draft preserved, conversation switch works, no sends.');
}finally{await browser.close()}
