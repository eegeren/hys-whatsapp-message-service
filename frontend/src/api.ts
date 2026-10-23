// Same-origin requests preserve the HttpOnly session and the server-only proxy secret.
export async function api(path:string,method='GET',body?:any){
 const multipart=body instanceof FormData;
 const files:File[]=multipart?[...body.values()].filter((v):v is File=>v instanceof File):[];
 const sizes=files.map(f=>({name:f.name,browser_bytes:f.size}));
 for(const file of files)if(file.size===0)throw Error('Seçilen dosya boş (tarayıcı: 0 bayt).');
 if(path!=='/media/inspect')for(const file of files){
  if(!['image/jpeg','image/png','video/mp4','video/3gpp','application/pdf'].includes(file.type))continue;
  const probe=new FormData();probe.append('file',file);probe.append('browser_bytes',String(file.size));
  const result=await api('/media/inspect','POST',probe);
  console.info('HYS medya kontrolü (bayt)',result);
 }
 if(files.length)console.info('HYS medya: bu istekteki tarayıcı dosya boyutu',sizes);
 let r:Response;
 try{r=await fetch('/api'+path,{method,headers:{'X-HYS-Request':'1',...(multipart?{}:{'Content-Type':'application/json'})},body:body===undefined?undefined:multipart?body:JSON.stringify(body)});}
 catch{throw Error('Sunucuya ulaşılamadı. Ağ bağlantısını kontrol edin. İstek otomatik tekrarlanmadı.');}
 const raw=await r.text();let d:any={};try{d=JSON.parse(raw)}catch{}
 if(!r.ok){
  const detail=typeof d.detail==='string'?d.detail:d.detail?.message?(d.detail.message+(d.detail.code!==undefined?' (Meta hata kodu: '+d.detail.code+')':'')):'';
  const reason=detail||(r.status===413?(raw.includes('FUNCTION_PAYLOAD_TOO_LARGE')?'Vercel Function istek gövdesi sınırı aşıldı (413 FUNCTION_PAYLOAD_TOO_LARGE).':'Yükleme sunucu veya ağ geçidi tarafından boyut nedeniyle reddedildi (HTTP 413); backend’e ulaştığı doğrulanamadı.'):'İstek tamamlanamadı (HTTP '+r.status+').');
  throw Error(reason+(files.length?' Tarayıcı dosya boyutu: '+files.map(f=>f.size+' bayt').join(', ')+'.':''));
 }
 return d;
}
