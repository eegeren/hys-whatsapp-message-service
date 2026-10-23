// Same-origin requests preserve the HttpOnly session and the server-only proxy secret.
export async function api(path:string,method='GET',body?:any){
 const multipart=body instanceof FormData;
 const files:File[]=multipart?[...body.values()].filter((v):v is File=>v instanceof File):[];
 for(const file of files)if(file.slice().size===0)throw Error('Seçilen dosya boş (tarayıcı: 0 bayt).');
 for(const file of files)assertFileBytes(file);
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

// Blob.slice uses the real backing bytes, even if someone overrides File.size.
export function assertFileBytes(file:File){
 const actual=file.slice().size;
 if(actual===0||actual!==file.size)throw Error(`Dosya içeriği ile boyut bilgisi eşleşmiyor (${actual} / ${file.size} bayt).`);
 return actual;
}
export async function preparedVideoFile(job:{preview_url:string;output_filename:string;output_size:number;id:string;source_size:number}){
 const response=await fetch(job.preview_url,{credentials:'omit'});
 if(!response.ok)throw Error(`Hazır video alınamadı (HTTP ${response.status}).`);
 const blob=await response.blob();
 if(blob.size!==job.output_size||blob.size===0)throw Error(`Hazır video eksik: ${blob.size} / ${job.output_size} bayt.`);
 const file=new File([blob],job.output_filename,{type:'video/mp4'});
 assertFileBytes(file);
 return Object.assign(file,{videoJobId:job.id,videoPreviewUrl:job.preview_url,sourceSize:job.source_size});
}
export function uploadBinary(url:string,file:File,onProgress:(pct:number)=>void=()=>{}){
 assertFileBytes(file);
 return new Promise<void>((resolve,reject)=>{
  const xhr=new XMLHttpRequest();xhr.open('PUT',url);xhr.withCredentials=false;
  xhr.setRequestHeader('Content-Type','application/octet-stream');
  xhr.upload.onprogress=e=>{if(e.lengthComputable)onProgress(Math.round(e.loaded/e.total*100))};
  xhr.onerror=()=>reject(Error('Dosya yüklenemedi. Ağ bağlantısını ve Railway yükleme adresini kontrol edin.'));
  xhr.onload=()=>{if(xhr.status>=200&&xhr.status<300)resolve();else{
   let detail='';try{const d=JSON.parse(xhr.responseText);detail=typeof d.detail==='string'?d.detail:''}catch{}
   reject(Error((detail|| (xhr.status===413?'Yükleme boyut sınırı aşıldı.':'Dosya yüklenemedi.'))+` (HTTP ${xhr.status}, tarayıcı: ${file.slice().size} bayt)`));
  }};
  xhr.send(file);
 });
}
