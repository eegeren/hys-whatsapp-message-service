import {useEffect,useId,useState,useRef} from 'react';

export type TemplateValues=Record<string,string>;
type Button={type:string;text?:string;url?:string;phone_number?:string};
type Component={type:string;format?:string;text?:string;buttons?:Button[]};
type TemplateText={body:string;components?:string|Component[]};
const placeholder=/{{\s*([A-Za-z_][A-Za-z_0-9]*|\d+)\s*}}/g;
const mediaRules:Record<string,{label:string;accept:string;limit:number}>={
 IMAGE:{label:'Görsel',accept:'image/jpeg,image/png',limit:5},
 VIDEO:{label:'Video',accept:'video/mp4,video/3gpp',limit:16},
 DOCUMENT:{label:'Belge',accept:'application/pdf',limit:100},
};
export function variableKeys(body:string):string[]{
 const keys=[...new Set([...body.matchAll(placeholder)].map(match=>/^\d+$/.test(match[1])?String(Number(match[1])):match[1]))];
 return keys.every(key=>/^\d+$/.test(key))?keys.sort((a,b)=>Number(a)-Number(b)):keys;
}
export function filledTemplate(body:string,values:TemplateValues):string{
 return body.replace(placeholder,(original,key)=>values[/^\d+$/.test(key)?String(Number(key)):key]||original);
}
function parts(template:TemplateText){
 let components:Component[]=[];
 try{const parsed=typeof template.components==='string'?JSON.parse(template.components):template.components;components=Array.isArray(parsed)?parsed:[];}catch{}
 const header=components.find(c=>c.type==='HEADER');
 const body=components.find(c=>c.type==='BODY')?.text??template.body??'';
 const footer=components.find(c=>c.type==='FOOTER')?.text||'';
 const buttons=components.find(c=>c.type==='BUTTONS')?.buttons||[];
 const unsupported=components.some(c=>!['HEADER','BODY','FOOTER','BUTTONS'].includes(c.type))||!!header&&!['TEXT','IMAGE','VIDEO','DOCUMENT'].includes(header.format||'TEXT')||buttons.some(b=>!['URL','PHONE_NUMBER','QUICK_REPLY'].includes(b.type));
 return {header,body,footer,buttons,unsupported};
}
function scopedValues(values:TemplateValues,scope:string,keys:string[]){return Object.fromEntries(keys.map(key=>[key,values[scope+key]||'']));}
function validLink(value:string){try{const url=new URL(value);return url.protocol==='https:'&&!url.username&&!url.password&&!['localhost','127.0.0.1','[::1]'].includes(url.hostname);}catch{return false;}}
function mediaError(kind:string,file:File|null){const rule=mediaRules[kind];return file&&rule&&(!rule.accept.split(',').includes(file.type)||file.size===0||file.size>rule.limit*1024*1024)?`Dosya türünü ve boyutunu kontrol edin (${rule.limit} MB sınırı).`:'';}
export function templateInputs(template:TemplateText,values:TemplateValues){
 const {header,body,buttons}=parts(template);const headerKind=header?.format||'TEXT';
 const buttonValues:TemplateValues={};
 buttons.forEach((button,index)=>{if(button.type==='URL'&&variableKeys(button.url||'').length)buttonValues[String(index)]=values['button:'+index]||'';});
 return {variables:scopedValues(values,'',variableKeys(body)),header_variables:scopedValues(values,'header:',variableKeys(header?.text||'')),button_variables:buttonValues,...(mediaRules[headerKind]?{header_media:{link:values['media:link']||'',filename:values['media:filename']||''}}:{})};
}
export function templateComplete(template:TemplateText|undefined,values:TemplateValues,file:File|null=null):boolean{
 if(!template)return false;
 const {header,body,buttons,unsupported}=parts(template);
 if(unsupported||!variableKeys(body).every(key=>!!values[key]?.trim())||!variableKeys(header?.text||'').every(key=>!!values['header:'+key]?.trim()))return false;
 if(buttons.some((button,index)=>button.type==='URL'&&variableKeys(button.url||'').length&&!values['button:'+index]?.trim()))return false;
 const kind=header?.format||'TEXT';return !mediaRules[kind]||(file?!mediaError(kind,file):validLink(values['media:link']||''));
}
export function templateSummary(template:TemplateText,values:TemplateValues,file:File|null=null){
 const {header,body,footer,buttons}=parts(template);const kind=header?.format||'TEXT';const lines:string[]=[];
 if(header){if(kind==='TEXT')lines.push(filledTemplate(header.text||'',scopedValues(values,'header:',variableKeys(header.text||''))));else lines.push(`[${mediaRules[kind]?.label||kind}${file?': '+file.name:''}]`);}
 lines.push(filledTemplate(body,values));if(footer)lines.push(footer);
 buttons.forEach((button,index)=>{const target=button.type==='URL'?filledTemplate(button.url||'',Object.fromEntries(variableKeys(button.url||'').map(key=>[key,values['button:'+index]||'']))):button.type==='PHONE_NUMBER'?button.phone_number:'';lines.push((button.text||'')+(target?' → '+target:''));});
 return lines.filter(Boolean).join('\n');
}
export default function TemplateFields({template,values,onChange,file=null,onFileChange,disabled=false}:{template?:TemplateText;values:TemplateValues;onChange:(values:TemplateValues)=>void;file?:File|null;onFileChange?:(file:File|null)=>void;disabled?:boolean}){
 const id=useId();const [filePreview,setFilePreview]=useState('');const fileInput=useRef<HTMLInputElement>(null);
 useEffect(()=>{if(!file&&fileInput.current)fileInput.current.value='';},[file,template]);
 useEffect(()=>{if(!file){setFilePreview('');return;}const url=URL.createObjectURL(file);setFilePreview(url);return()=>URL.revokeObjectURL(url);},[file]);
 if(!template)return null;
 const {header,body,footer,buttons,unsupported}=parts(template);const kind=header?.format||'TEXT',rule=mediaRules[kind];
 const mediaSource=file?filePreview:(validLink(values['media:link']||'')?values['media:link']:'');
 function field(key:string,label:string,maxLength=4096){return <label className="template-variable-field" key={key} htmlFor={`${id}-${key}`}>{label}<input id={`${id}-${key}`} type="text" required disabled={disabled} maxLength={maxLength} placeholder={`${label} için metin yazın`} value={values[key]||''} onChange={e=>onChange({...values,[key]:e.target.value})}/></label>;}
 return <div className="template-fields">
  {unsupported&&<p className="eligibility-warning">Bu şablonda standart başlık, metin veya URL/telefon/hızlı yanıt butonlarından farklı bir bileşen var.</p>}
  {header&&kind==='TEXT'&&variableKeys(header.text||'').map(key=>field('header:'+key,`Başlık değişkeni ${key}`))}
  {rule&&<div className="template-media-inputs"><label className="template-variable-field" htmlFor={`${id}-media-link`}>{rule.label} bağlantısı<input id={`${id}-media-link`} type="url" disabled={disabled} maxLength={2048} placeholder="https://… (herkese açık medya dosyası)" value={values['media:link']||''} onChange={e=>{onChange({...values,'media:link':e.target.value});onFileChange?.(null);}}/></label>{onFileChange&&<label className="template-variable-field" htmlFor={`${id}-media-file`}>Veya {rule.label.toLocaleLowerCase('tr-TR')} dosyası seçin<input key={String(template.components)} ref={fileInput} id={`${id}-media-file`} type="file" accept={rule.accept} disabled={disabled} onChange={e=>{onFileChange?.(e.target.files?.[0]||null);onChange({...values,'media:link':''});}}/></label>}<small>{kind==='IMAGE'?'JPEG / PNG':kind==='VIDEO'?'MP4 / 3GP (H.264 video, AAC ses)':'PDF'} · en fazla {rule.limit} MB. Dosya yalnızca Gönder onayından sonra Meta’ya yüklenir.</small>{file&&<small>Seçilen dosya: {file.name} <button type="button" disabled={disabled} onClick={()=>onFileChange?.(null)}>Kaldır</button></small>}{mediaError(kind,file)&&<p className="eligibility-warning">{mediaError(kind,file)}</p>}{kind==='DOCUMENT'&&<label className="template-variable-field" htmlFor={`${id}-filename`}>Belge adı (isteğe bağlı)<input id={`${id}-filename`} disabled={disabled} maxLength={200} value={values['media:filename']||''} placeholder={file?.name||'dosya.pdf'} onChange={e=>onChange({...values,'media:filename':e.target.value})}/></label>}</div>}
  {variableKeys(body).map(key=>field(key,`Değişken ${key}`))}
  {buttons.map((button,index)=>button.type==='URL'&&variableKeys(button.url||'').length?<div key={index}>{field('button:'+index,`URL butonu ${index+1} değişkeni`,2000)}<small>{button.text} · Bağlantının değişken kısmını yazın; tam bağlantı önizlemede görünür.</small></div>:null)}
  <div className="template-preview" aria-live="polite"><span>MESAJ ÖNİZLEMESİ</span>
   {header&&kind==='TEXT'&&<div className="template-preview-header">{filledTemplate(header.text||'',scopedValues(values,'header:',variableKeys(header.text||'')))}</div>}
   {rule&&(mediaSource?(kind==='IMAGE'?<img className="template-preview-media" src={mediaSource} alt="Seçilen şablon görseli"/>:kind==='VIDEO'?<video className="template-preview-media" src={mediaSource} controls preload="none"/>:<a className="template-preview-document" href={mediaSource} target="_blank" rel="noopener noreferrer">📄 {values['media:filename']||file?.name||'Belgeyi görüntüle'}</a>):<div className="template-preview-media-placeholder">{rule.label} başlığı · medya seçin</div>)}
   <p>{filledTemplate(body,values)||'Şablon metni alınamadı.'}</p>{footer&&<div className="template-preview-footer">{footer}</div>}
   {buttons.length>0&&<div className="template-preview-buttons">{buttons.map((button,index)=><div className="template-preview-button" key={index}><strong>{button.text}</strong>{button.type==='URL'&&<small>{filledTemplate(button.url||'',Object.fromEntries(variableKeys(button.url||'').map(key=>[key,values['button:'+index]||''])))}</small>}{button.type==='PHONE_NUMBER'&&<small>{button.phone_number}</small>}</div>)}</div>}
   {!templateComplete(template,values,file)&&!unsupported&&<small>Göndermeden önce gerekli değişkenleri ve medya başlığını doldurun.</small>}
  </div>
 </div>;
}
