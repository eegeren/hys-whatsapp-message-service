import assert from 'node:assert/strict';
import test from 'node:test';
import {getTransformedRoutes} from '@vercel/routing-utils';

// Dummy deployment settings only. No .env loading or network requests.
process.env.BACKEND_API_ORIGIN='https://hys-config-test.up.railway.app';
process.env.PANEL_PROXY_SECRET='dummy-proxy-secret-for-config-tests-only';
const {config}=await import('../vercel.mjs');

test('Vercel routing validation accepts transforms without mixed formats',()=>{
  const result=getTransformedRoutes(config);
  assert.equal(result.error,null);
  assert.equal(result.routes.length,3);
  for(const field of ['rewrites','redirects','headers'])assert.equal(config[field],undefined);
});

test('API forwards paths and injects the proxy secret only as a request header',()=>{
  const api=config.routes[0];
  const match=new RegExp(api.src).exec('/api/messages');
  assert.ok(match);
  assert.equal(api.dest.replace('$1',match[1]),process.env.BACKEND_API_ORIGIN+'/api/messages');
  const request=api.transforms.find(t=>t.type==='request.headers');
  assert.equal(request.op,'set');
  assert.equal(request.target.key,'X-HYS-Proxy-Secret');
  assert.equal(request.args,process.env.PANEL_PROXY_SECRET);
  const responses=api.transforms.filter(t=>t.type==='response.headers');
  assert.ok(responses.some(t=>t.target.key==='Cache-Control' && t.args==='no-store'));
  assert.ok(responses.every(t=>t.args!==process.env.PANEL_PROXY_SECRET));
  assert.equal(new RegExp(api.src).test('/assets/app.js'),false);
});

test('Static files are served before the SPA fallback, after the API route',()=>{
  assert.deepEqual(config.routes[1],{handle:'filesystem'});
  assert.equal(config.routes[2].dest,'/index.html');
  assert.ok(new RegExp(config.routes[2].src).test('/messages'));
});
