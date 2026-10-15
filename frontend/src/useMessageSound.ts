import {useEffect,useRef,useState} from 'react';
// A quiet synthesized chime: no remote audio, microphone permission or autoplay bypass.
export default function useMessageSound(){
 const [enabled,setEnabled]=useState(()=>{try{return localStorage.getItem('hys-message-sound')!=='off'}catch{return true}});
 const context=useRef<AudioContext|null>(null),last=useRef(0),armed=useRef(false);
 useEffect(()=>{function arm(){armed.current=true;if(!enabled)return;try{context.current??=new AudioContext();void context.current.resume().catch(()=>{})}catch{}}window.addEventListener('pointerdown',arm);window.addEventListener('keydown',arm);return()=>{window.removeEventListener('pointerdown',arm);window.removeEventListener('keydown',arm)}},[enabled]);
 useEffect(()=>()=>{void context.current?.close().catch(()=>{})},[]);
 function toggle(){setEnabled(v=>{try{localStorage.setItem('hys-message-sound',v?'off':'on')}catch{}return !v})}
 function play(){if(!enabled||!armed.current||Date.now()-last.current<1500)return;try{const ctx=context.current;if(!ctx||ctx.state!=='running')return;last.current=Date.now();const t=ctx.currentTime;const volume=ctx.createGain();volume.gain.setValueAtTime(0,t);volume.gain.linearRampToValueAtTime(.035,t+.012);volume.gain.exponentialRampToValueAtTime(.001,t+.22);volume.connect(ctx.destination);const tone=ctx.createOscillator();tone.type='sine';tone.frequency.setValueAtTime(880,t);tone.frequency.setValueAtTime(1174,t+.09);tone.connect(volume);tone.start(t);tone.stop(t+.23);tone.onended=()=>{tone.disconnect();volume.disconnect()}}catch{}}
 return {enabled,toggle,play};
}
