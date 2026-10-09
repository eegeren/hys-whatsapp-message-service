import {useState} from 'react';
import {Eye,EyeOff} from 'lucide-react';

type Props={name:string;label:string;minLength?:number;autoComplete?:string;hint?:string};
export default function PasswordInput({name,label,minLength,autoComplete='off',hint}:Props){
 const [visible,setVisible]=useState(false),[caps,setCaps]=useState(false);
 return <label className="field password-field"><span>{label} *</span><div className="password-control"><input name={name} aria-label={label+' *'} type={visible?'text':'password'} required minLength={minLength} maxLength={128} autoComplete={autoComplete} aria-describedby={hint?name+'-hint':undefined} onKeyUp={e=>setCaps(e.getModifierState('CapsLock'))} onBlur={()=>setCaps(false)}/><button type="button" aria-label={visible?label+' gizle':label+' göster'} aria-pressed={visible} onClick={()=>setVisible(v=>!v)}>{visible?<EyeOff size={18}/>:<Eye size={18}/>}</button></div>{hint&&<small id={name+'-hint'}>{hint}</small>}{caps&&<small className="caps-warning">Caps Lock açık.</small>}</label>;
}
