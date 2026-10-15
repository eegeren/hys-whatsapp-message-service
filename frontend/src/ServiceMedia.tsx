import {useEffect,useRef,useState} from 'react';
import VideoProcessor from './VideoProcessor';
export function serviceMediaValid(file:File|null){return !file||['image/jpeg','image/png','video/mp4'].includes(file.type)&&file.size>0&&file.size<=(file.type==='video/mp4'?16:5)*1024*1024;}
export default function ServiceMedia({file,onChange,disabled=false}:{file:File|null;onChange:(file:File|null)=>void;disabled?:boolean}){
 const [url,setUrl]=useState('');const input=useRef<HTMLInputElement>(null);
 useEffect(()=>{if(!file){setUrl('');if(input.current)input.current.value='';return;}const link=URL.createObjectURL(file);setUrl(link);return()=>URL.revokeObjectURL(link);},[file]);
 return <div className="service-media"><label className="simple-field">Görsel ekle<input ref={input} type="file" accept="image/jpeg,image/png,.jpg,.jpeg,.png" disabled={disabled} onChange={e=>onChange(e.target.files?.[0]||null)}/></label><small>JPG / PNG: 5 MB. Dosya yalnızca Gönder onayından sonra Meta’ya yüklenir.</small>{file&&file.type.startsWith('image/')&&<><p>{file.name} <button type="button" disabled={disabled} onClick={()=>onChange(null)}>Kaldır</button></p>{!serviceMediaValid(file)?<p className="eligibility-warning">Dosya türünü ve boyutunu kontrol edin.</p>:file.type==='video/mp4'?<video className="template-preview-media" src={url} controls preload="none"/>:<img className="template-preview-media" src={url} alt="Gönderilecek görsel önizlemesi"/>}</>}<VideoProcessor file={file&&!file.type.startsWith('image/')?file:null} onChange={onChange} disabled={disabled}/></div>;
}
