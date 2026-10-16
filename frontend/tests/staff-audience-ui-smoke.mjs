// Temporary sandbox only; imports persist in its throwaway DB, never calls Meta.
import {createRequire} from 'node:module';import assert from 'node:assert/strict';
const {chromium}=createRequire(import.meta.url)(process.env.PLAYWRIGHT_MODULE_PATH||'playwright');const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_EXECUTABLE});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];let sends=0;page.on('pageerror',e=>errors.push(String(e)));page.on('request',r=>{if(/\/send(?:\?|$)/.test(r.url()))sends++});
 await page.goto(process.env.STAFF_UI_URL);await page.locator('input[name=username]').fill('uiadmin');await page.locator('input[name=password]').fill('UITestPassword123!');await page.getByRole('button',{name:'Giriş yap',exact:true}).click();await page.getByRole('button',{name:'Personel Duyuruları',exact:true}).click();
 await page.getByText('Henüz Excel yüklenmedi.',{exact:false}).waitFor();assert(await page.getByLabel('Hedef').isDisabled());assert.equal(await page.locator('.staff-choice').count(),0);
 await page.getByRole('button',{name:'Kayıtlı personelleri kullan',exact:true}).click();await page.getByLabel('Hedef').selectOption('people');await page.getByLabel(/Test Personeli/).waitFor();
 await page.getByRole('button',{name:'Excel’den yükle',exact:true}).click();assert(await page.getByLabel('Hedef').isDisabled());assert.equal(await page.getByLabel(/Test Personeli/).count(),0);
 await page.getByLabel('Personel Excel dosyası',{exact:true}).setInputFiles({name:'current.csv',mimeType:'text/csv',buffer:Buffer.from('Ad Soyad,Telefon,Mağaza\nDosya Personeli,05550000099,Test Mağazası\n')});await page.getByText('current.csv',{exact:true}).waitFor();await page.getByLabel('Hedef').selectOption('people');await page.getByLabel(/Dosya Personeli/).waitFor();assert.equal(await page.getByLabel(/Test Personeli/).count(),0);
 await page.getByRole('button',{name:'Kayıtlı personelleri kullan',exact:true}).click();await page.getByLabel('Hedef').selectOption('people');await page.getByLabel(/Test Personeli/).waitFor();await page.getByLabel(/Dosya Personeli/).waitFor();
 await page.getByRole('button',{name:'Yeni duyuru',exact:true}).click();await page.getByText('Henüz Excel yüklenmedi.',{exact:false}).waitFor();assert(await page.getByLabel('Hedef').isDisabled());assert.equal(await page.locator('.staff-choice').count(),0);assert.equal(await page.getByText('current.csv',{exact:true}).count(),0);
 await page.setViewportSize({width:390,height:844});await page.screenshot({path:'/tmp/hys-staff-audience-empty-mobile.png',fullPage:true});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);assert.equal(sends,0);assert.deepEqual(errors,[]);
 console.log('Staff audience UI PASS: no automatic saved audience, explicit stored list, upload-only scope, named file, reset, mobile, no sends.');
}finally{await browser.close()}
