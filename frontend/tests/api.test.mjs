import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
const source=ts.transpile(fs.readFileSync(new URL('../src/api.ts',import.meta.url),'utf8'),{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext});
const {api}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));

test('non-JSON Vercel 413 reports the actual platform error',async()=>{
 globalThis.fetch=async()=>new Response('FUNCTION_PAYLOAD_TOO_LARGE',{status:413});
 await assert.rejects(api('/media/inspect','POST',new FormData()),/Vercel Function.*413/);
});
test('other 413 does not assert a Vercel Function cause',async()=>{
 globalThis.fetch=async()=>new Response('Payload too large',{status:413});
 await assert.rejects(api('/media/inspect','POST',new FormData()),/backend’e ulaştığı doğrulanamadı/);
});
test('multipart inspection compares the browser and received sizes before proceeding',async()=>{
 const requests=[];const bytes=new Uint8Array(9_670_000);
 const file=new File([bytes],'clip.mp4',{type:'video/mp4'});const form=new FormData();form.append('file',file);
 globalThis.fetch=async(url,options)=>{requests.push([url,options]);return Response.json(url.endsWith('/inspect')?{browser_bytes:file.size,received_bytes:file.size,output_bytes:file.size,conversion_applied:false}:{ok:true});};
 assert.deepEqual(await api('/bulk/campaign-with-media','POST',form),{ok:true});
 assert.equal(requests.length,2);assert.equal(requests[0][0],'/api/media/inspect');
 assert.equal(requests[0][1].body.get('browser_bytes'),'9670000');
 assert.equal(requests[1][1].body,form);
 assert.equal(requests[1][1].headers['X-HYS-Request'],'1');
 assert.equal(requests[1][1].headers['Content-Type'],undefined);
});
test('failed inspection prevents the requested operation',async()=>{
 let calls=0;globalThis.fetch=async()=>{calls++;return Response.json({detail:'Backend boş dosya aldı (0 bayt).'},{status:422});};
 const form=new FormData();form.append('file',new File(['x'],'clip.mp4',{type:'video/mp4'}));
 await assert.rejects(api('/conversations/send-with-media','POST',form),/Backend boş dosya/);assert.equal(calls,1);
});
