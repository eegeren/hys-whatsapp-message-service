import {useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {AlertCircle,CheckCircle2,X} from 'lucide-react';

type Props={error:string;notice?:string;onErrorClose:()=>void;onNoticeClose?:()=>void};
export default function Notifications({error,notice='',onErrorClose,onNoticeClose}:Props){
 const [paused,setPaused]=useState(false);
 const [container,setContainer]=useState<HTMLElement|null>(null);
 useEffect(()=>{let node=document.getElementById('hys-notifications');if(!node){node=document.createElement('div');node.id='hys-notifications';node.className='notification-stack';node.setAttribute('aria-label','Bildirimler');document.body.appendChild(node);}setContainer(node);},[]);
 const close=useRef(onNoticeClose);close.current=onNoticeClose;
 const closeError=useRef(onErrorClose);closeError.current=onErrorClose;
 useEffect(()=>{if(!error||paused)return;const timer=setTimeout(()=>closeError.current(),12000);return()=>clearTimeout(timer)},[error,paused]);
 useEffect(()=>{if(!notice||paused)return;const timer=setTimeout(()=>close.current?.(),5000);return()=>clearTimeout(timer);},[notice,paused]);
 if(!container||(!error&&!notice))return null;
 const interaction={onMouseEnter:()=>setPaused(true),onMouseLeave:()=>setPaused(false),onFocusCapture:()=>setPaused(true),onBlurCapture:()=>setPaused(false)};
 return createPortal(<>
  {error&&<div {...interaction} className="notification-card notification-error" role="alert" onClick={()=>{setPaused(false);onErrorClose()}}><AlertCircle size={21}/><div><strong>İşlem tamamlanamadı</strong><p>{error.replace(/^Error:\s*/,'')}</p></div><button type="button" aria-label="Hata bildirimini kapat" onClick={()=>{setPaused(false);onErrorClose()}}><X size={18}/></button></div>}
  {notice&&<div {...interaction} className="notification-card notification-success" role="status" onClick={()=>{setPaused(false);onNoticeClose?.()}} aria-live="polite"><CheckCircle2 size={21}/><div><strong>İşlem sonucu</strong><p>{notice.replace(/^Error:\s*/,'')}</p></div><button type="button" aria-label="Bilgilendirmeyi kapat" onClick={()=>{setPaused(false);onNoticeClose?.()}}><X size={18}/></button></div>}
 </>,container);
}
