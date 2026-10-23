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

test('real multipart bytes and browser-generated boundary survive serialization',async()=>{
 const raw=new Uint8Array(9_670_000);raw.set([0,0,0,24,102,116,121,112]);
 const file=new File([raw],'clip.mp4',{type:'video/mp4'});const form=new FormData();form.append('file',file);
 globalThis.fetch=async(url,options)=>{
  assert.equal(options.headers['Content-Type'],undefined);
  const request=new Request('http://localhost'+url,options);
  assert.match(request.headers.get('Content-Type'),/multipart\/form-data; boundary=/);
  const received=(await request.formData()).get('file');
  assert.equal(received.size,raw.length);assert.deepEqual(new Uint8Array(await received.arrayBuffer()),raw);
  return Response.json({ok:true});
 };
 assert.deepEqual(await api('/bulk/campaign-with-media','POST',form),{ok:true});
});
test('regression: spoofing an empty File size still serializes zero bytes',async()=>{
 const file=new File([],'clip.mp4',{type:'video/mp4'});Object.defineProperty(file,'size',{value:9_670_000});
 const form=new FormData();form.append('file',file);
 const request=new Request('http://localhost',{method:'POST',body:form});
 assert.equal((await request.formData()).get('file').size,0);
 globalThis.fetch=async()=>assert.fail('empty placeholder must never be uploaded');
 await assert.rejects(api('/bulk/campaign-with-media','POST',form),/boş|eşleşmiyor/);
});
test('prepared output becomes a real File with identical bytes',async()=>{
 const {preparedVideoFile}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
 const raw=new Uint8Array(9_670_000);raw[raw.length-1]=117;
 globalThis.fetch=async()=>new Response(raw);
 const file=await preparedVideoFile({preview_url:'http://localhost/preview',output_filename:'clip.mp4',output_size:raw.length,id:'job',source_size:raw.length});
 assert.equal(file.size,file.slice().size);assert.equal(file.videoJobId,'job');
 assert.deepEqual(new Uint8Array(await file.arrayBuffer()),raw);
});
test('incomplete prepared output is rejected',async()=>{
 const {preparedVideoFile}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
 globalThis.fetch=async()=>new Response('short');
 await assert.rejects(preparedVideoFile({preview_url:'http://localhost',output_filename:'clip.mp4',output_size:9_670_000,id:'job',source_size:9_670_000}),/eksik/);
});
