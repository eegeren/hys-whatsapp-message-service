import {routes} from '@vercel/config/v1';

// These are server-side deployment values. Never use a VITE_ prefix for secrets.
const backend=process.env.BACKEND_API_ORIGIN;
const proxySecret=process.env.PANEL_PROXY_SECRET;
let parsed;
try {parsed=new URL(backend);} catch {throw new Error('BACKEND_API_ORIGIN gerçek Railway HTTPS adresi olmalıdır.');}
if(parsed.protocol!=='https:' || !parsed.hostname.endsWith('.up.railway.app') || parsed.username || parsed.password || parsed.port || parsed.pathname!=='/' || parsed.search || parsed.hash)
  throw new Error('BACKEND_API_ORIGIN yalnızca Railway HTTPS origin içermelidir.');
if(!proxySecret || proxySecret.length<32)throw new Error('PANEL_PROXY_SECRET en az 32 karakter olmalıdır.');

export const config={
  framework:'vite',installCommand:'npm ci',buildCommand:'npm run build:vercel',outputDirectory:'dist',
  routes:[
    routes.rewrite('/api/(.*)',parsed.origin+'/api/$1',{
      requestHeaders:{'X-HYS-Proxy-Secret':proxySecret},
      responseHeaders:{'Cache-Control':'no-store'},
    }),
    {handle:'filesystem'},
    {src:'^/.*$',dest:'/index.html'},
  ],
};
