import {useEffect,useRef} from 'react';

export default function useDialog(open:boolean,onClose:()=>void,busy:boolean){
 const ref=useRef<HTMLElement>(null),close=useRef(onClose),locked=useRef(busy);
 close.current=onClose;locked.current=busy;
 useEffect(()=>{
  if(!open)return;
  const trigger=document.querySelector<HTMLButtonElement>('.new-message-trigger');
  function keydown(event:KeyboardEvent){
   if(event.key==='Escape'&&!locked.current){event.preventDefault();close.current();}
   if(event.key!=='Tab'||!ref.current)return;
   const elements=Array.from(ref.current.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href]')).filter(el=>el.getClientRects().length>0);
   const first=elements[0],last=elements[elements.length-1];if(!first)return;
   if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
   else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
  }
  document.addEventListener('keydown',keydown);
  return()=>{document.removeEventListener('keydown',keydown);trigger?.focus();};
 },[open]);
 return ref;
}
