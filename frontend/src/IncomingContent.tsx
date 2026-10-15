import {useState} from 'react';
import {FileText,Download,MapPin,UserRound,RefreshCw} from 'lucide-react';
const labels:Record<string,string>={audio:'Ses kaydı',image:'Fotoğraf',video:'Video',document:'Belge',sticker:'Çıkartma',contacts:'Kişi kartı',location:'Konum',interactive:'Seçim yanıtı',reaction:'Tepki',unsupported:'Desteklenmeyen mesaj',unknown:'Bilinmeyen mesaj'};
export default function IncomingContent({message}:{message:Record<string,any>}){
 const [failed,setFailed]=useState(false),[attempt,setAttempt]=useState(0),[show,setShow]=useState(false);
 const content=message.content;const legacy=message.direction==='in'&&/^\[([a-z_]+)\]$/.exec(message.body||'');
 if(!content)return legacy?<div className="incoming-unavailable"><strong>{labels[legacy[1]]||'Mesaj içeriği'}</strong><span>Bu eski mesajın içeriği kaydedilmemiş. Gönderenden yeniden göndermesini isteyin.</span></div>:<div className="bubble-text">{message.body}</div>;
 const kind=content.kind;const url='/api/messages/'+message.id+'/media'+(attempt?'?retry='+attempt:'');
 if(kind==='location'){
  const lat=Number(content.latitude),lon=Number(content.longitude),valid=Number.isFinite(lat)&&Number.isFinite(lon)&&Math.abs(lat)<=90&&Math.abs(lon)<=180;
  return <div className="incoming-location"><MapPin size={21}/><strong>{content.name||'Paylaşılan konum'}</strong>{content.address&&<span>{content.address}</span>}{valid&&<a href={'https://www.google.com/maps?q='+lat+','+lon} target="_blank" rel="noopener noreferrer">Haritada aç</a>}</div>
 }
 if(kind==='contacts')return <div className="incoming-contacts">{(content.contacts||[]).map((c:any,i:number)=><div key={i}><UserRound size={20}/><strong>{c.name?.formatted_name||'Kişi'}</strong>{(c.phones||[]).map((p:any,j:number)=><span key={j}>{p.phone}</span>)}</div>)}</div>;
 if(kind==='interactive'||kind==='reaction')return <div className="bubble-text">{content.text||labels[kind]}</div>;
 if(!content.available)return <div className="incoming-unavailable"><strong>{labels[kind]||'Dosya'}</strong><span>Bu mesajın dosya bilgisi bulunamadı. Yeniden gönderilmesini isteyin.</span></div>;
 return <div className={'incoming-media incoming-'+kind}>
  <strong className="incoming-media-title">{labels[kind]||'Dosya'}</strong>
  {kind==='audio'&&<audio key={attempt} controls preload="none" src={url} onError={()=>setFailed(true)} aria-label="Gelen ses kaydı"/>}
  {(kind==='image'||kind==='sticker')&&(show?<a href={url} target="_blank" rel="noopener noreferrer"><img key={attempt} src={url} alt={content.caption||labels[kind]} onError={()=>setFailed(true)}/></a>:<button className="button-light" onClick={()=>setShow(true)}>Görüntüle</button>)}
  {kind==='video'&&<video key={attempt} controls playsInline preload="none" src={url} onError={()=>setFailed(true)} aria-label="Gelen video"/>}
  {kind==='document'&&<a className="incoming-document-link" href={url} target="_blank" rel="noopener noreferrer"><FileText size={26}/><span>{content.filename||'Gelen belge'}<small>Belgeyi aç</small></span></a>}
  {content.caption&&<div className="bubble-text">{content.caption}</div>}
  {failed&&<div className="incoming-media-error" role="status"><span>Dosya açılamadı. Meta’daki dosyanın süresi dolmuş veya bağlantı kesilmiş olabilir.</span><button onClick={()=>{setFailed(false);setAttempt(v=>v+1)}}><RefreshCw size={13}/>Tekrar dene</button></div>}
  <a className="incoming-download" href={url+(attempt?'&':'?')+'download=true'} target="_blank" rel="noopener noreferrer"><Download size={13}/>Dosyayı indir</a>
 </div>
}
