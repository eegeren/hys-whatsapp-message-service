import {useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {AlertCircle,CheckCircle2,X} from 'lucide-react';

type Props={error:string;notice?:string;onErrorClose:()=>void;onNoticeClose?:()=>void};
export default function Notifications({error,notice='',onErrorClose,onNoticeClose}:Props){
 const [paused,setPaused]=useState(false);
 const close=useRef(onNoticeClose);close.current=onNoticeClose;
 useEffect(()=>{if(!notice||paused)return;const timer=setTimeout(()=>close.current?.(),10000);return()=>clearTimeout(timer);},[notice,paused]);
 if(!error&&!notice)return null;
 return createPortal(<div className="notification-stack" aria-label="Bildirimler" onMouseEnter={()=>setPaused(true)} onMouseLeave={()=>setPaused(false)} onFocusCapture={()=>setPaused(true)} onBlurCapture={()=>setPaused(false)}>
  {error&&<div className="notification-card notification-error" role="alert"><AlertCircle size={21}/><div><strong>İşlem tamamlanamadı</strong><p>{error.replace(/^Error:\s*/,'')}</p></div><button type="button" aria-label="Hata bildirimini kapat" onClick={onErrorClose}><X size={18}/></button></div>}
  {notice&&<div className="notification-card notification-success" role="status" aria-live="polite"><CheckCircle2 size={21}/><div><strong>İşlem sonucu</strong><p>{notice.replace(/^Error:\s*/,'')}</p></div><button type="button" aria-label="Bilgilendirmeyi kapat" onClick={onNoticeClose}><X size={18}/></button></div>}
 </div>,document.body);
}
