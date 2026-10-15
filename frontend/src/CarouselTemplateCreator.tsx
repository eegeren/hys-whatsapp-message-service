import {useEffect,useState} from 'react';
import {variableKeys,filledTemplate} from './TemplateFields';
type Card={text:string;examples:Record<string,string>;file:File|null};
const emptyCard=():Card=>({text:'',examples:{},file:null});
function SamplePreview({card,button}:{card:Card;button:string}){
 const [url,setUrl]=useState('');
 useEffect(()=>{if(!card.file){setUrl('');return;}const next=URL.createObjectURL(card.file);setUrl(next);return()=>URL.revokeObjectURL(next);},[card.file]);
 return <div className="template-preview">{url&&<img className="template-preview-media" src={url} alt="Meta onayı için örnek görsel"/>}<p>{filledTemplate(card.text,card.examples)||'Kart açıklaması'}</p><div className="template-preview-button">{button}</div></div>;
}
export default function CarouselTemplateCreator({onCreated}:{onCreated:()=>void}){
 const [name,setName]=useState(''),[body,setBody]=useState(''),[examples,setExamples]=useState<Record<string,string>>({}),[cards,setCards]=useState<Card[]>([emptyCard(),emptyCard(),emptyCard()]),[button,setButton]=useState('Gördüm');
 const [review,setReview]=useState(false),[busy,setBusy]=useState(false),[confirmed,setConfirmed]=useState(false),[error,setError]=useState(''),[result,setResult]=useState<{name:string;status:string;notice:string}|null>(null);
 const validText=(text:string,values:Record<string,string>)=>!!text.trim()&&variableKeys(text).every(k=>/^\d+$/.test(k)&&!!values[k]?.trim());
 const validFile=(file:File|null)=>!!file&&['image/jpeg','image/png'].includes(file.type)&&file.size>0&&file.size<=5*1024*1024;
 const ready=/^[a-z0-9_]{1,150}$/.test(name)&&validText(body,examples)&&!!button.trim()&&cards.every(c=>validText(c.text,c.examples)&&validFile(c.file));
 function updateCard(index:number,update:Partial<Card>){setCards(old=>old.map((c,i)=>i===index?{...c,...update}:c));setResult(null);}
 function exampleFields(text:string,values:Record<string,string>,change:(v:Record<string,string>)=>void,scope:string){return variableKeys(text).map(k=><label className="simple-field" key={k}>{scope} değişken {k} için örnek<input required disabled={busy} maxLength={4096} value={values[k]||''} placeholder="Meta incelemesinde gösterilecek örnek değer" onChange={e=>change({...values,[k]:e.target.value})}/></label>);}
 async function submit(){
  if(!ready||!confirmed||busy)return;setBusy(true);setError('');
  try{
   const sample=(text:string,values:Record<string,string>)=>Object.fromEntries(variableKeys(text).map(k=>[k,values[k]]));
   const form=new FormData();form.append('data',JSON.stringify({name,body,examples:sample(body,examples),cards:cards.map(c=>({text:c.text,examples:sample(c.text,c.examples)})),button_text:button,confirmed:true}));
   cards.forEach(c=>form.append('files',c.file!));
   const response=await fetch('/api/templates/carousel-review',{method:'POST',headers:{'X-HYS-Request':'1'},body:form});const data=await response.json();
   if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:(data.detail?.message||'Meta başvurusu tamamlanamadı.')+(data.detail?.code!==undefined?' (Meta kodu: '+data.detail.code+')':''));
   setResult(data);setReview(false);onCreated();
  }catch(e){setError(e instanceof Error?e.message:'Başvuru tamamlanamadı.');}finally{setBusy(false);}
 }
 return <details className="carousel-create simple-card"><summary>Çoklu görsel şablonunu Meta onayına hazırla</summary><p>Türkçe Marketing carousel · 2–10 görsel kartı. Bu işlem şablon ve örnek görselleri Meta incelemesine gönderir; personele veya müşteriye mesaj göndermez.</p>
  {error&&<p className="eligibility-warning" role="alert">{error}</p>}{result&&<p className="queue-notice" role="status"><strong>{result.name} · {result.status}</strong><br/>{result.notice}</p>}
  <form onSubmit={e=>{e.preventDefault();if(ready){setConfirmed(false);setReview(true);}}}>
   <label className="simple-field">Şablon adı<input required disabled={busy} value={name} maxLength={150} pattern="[a-z0-9_]+" placeholder="hys_personel_gorseller" onChange={e=>{setName(e.target.value);setResult(null);}}/><small>Küçük harf, rakam ve alt çizgi kullanın.</small></label>
   <label className="simple-field">Ana mesaj metni<textarea required disabled={busy} rows={3} maxLength={1024} placeholder="Personellere gösterilecek ana mesajı yazın…" value={body} onChange={e=>{setBody(e.target.value);setResult(null);}}/></label>
   <small>Sabit metin Meta tarafından onaylanır. Değişken gerekiyorsa {'{{1}}'}, {'{{2}}'} yazıp örnek değerlerini doldurun.</small>{exampleFields(body,examples,setExamples,'Ana metin')}
   <label className="simple-field">Görsel kartı sayısı<select disabled={busy} value={cards.length} onChange={e=>{const count=Number(e.target.value);setCards(old=>Array.from({length:count},(_,i)=>old[i]||emptyCard()));setResult(null);}}>{Array.from({length:9},(_,i)=><option key={i+2} value={i+2}>{i+2} görsel</option>)}</select></label>
   <label className="simple-field">Tüm kartların örnek görsellerini seçin<input type="file" multiple accept="image/jpeg,image/png" disabled={busy} onChange={e=>{const files=Array.from(e.target.files||[]);if(files.length!==cards.length){setError(`Tam olarak ${cards.length} örnek görsel seçin.`);e.target.value='';return;}setError('');setCards(old=>old.map((c,i)=>({...c,file:files[i]})));setResult(null);}}/></label>
   <label className="simple-field">Kartların hızlı yanıt butonu<input required disabled={busy} value={button} maxLength={25} onChange={e=>{setButton(e.target.value);setResult(null);}}/><small>Her kartta aynı buton bulunur; personel dokunduğunda bu metinle yanıt verir.</small></label>
   <div className="carousel-cards">{cards.map((card,index)=><section className="carousel-card" key={index}><h3>Kart {index+1}</h3><label className="simple-field">Kart {index+1} açıklaması<textarea required disabled={busy} maxLength={160} rows={3} value={card.text} onChange={e=>updateCard(index,{text:e.target.value})}/></label>{exampleFields(card.text,card.examples,v=>updateCard(index,{examples:v}),`Kart ${index+1}`)}<label className="simple-field">Kart {index+1} örnek görseli<input required={!card.file} disabled={busy} type="file" accept="image/jpeg,image/png" onChange={e=>updateCard(index,{file:e.target.files?.[0]||null})}/></label>{card.file&&<small>{card.file.name}</small>}{card.file&&!validFile(card.file)&&<p className="eligibility-warning">JPEG / PNG seçin; kart başına en fazla 5 MB.</p>}<SamplePreview card={card} button={button}/></section>)}</div>
   <p className="template-preview">{filledTemplate(body,examples)||'Ana mesaj önizlemesi'}</p><button type="submit" className="button-green large" disabled={!ready||busy||!!result}>Başvuruyu kontrol et</button>
  </form>
  {review&&<div className="modal-backdrop"><section className="modal bulk-confirm-modal" role="dialog" aria-modal="true" aria-label="Carousel şablon başvurusunu onayla"><h2>Meta şablon başvurusunu onayla</h2><p><strong>{name}</strong> · Türkçe · Marketing · {cards.length} görsel</p><p className="template-preview">{filledTemplate(body,examples)}</p><div className="carousel-cards">{cards.map((c,i)=><section className="carousel-card" key={i}><h3>Kart {i+1}</h3><SamplePreview card={c} button={button}/></section>)}</div><label className="bulk-checkbox"><input type="checkbox" disabled={busy} checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>Bu metin, butonlar ve örnek görsellerin Meta incelemesine gönderilmesini onaylıyorum. Bu işlem alıcılara mesaj göndermez.</label>{error&&<p role="alert" className="eligibility-warning">{error}</p>}<div className="modal-actions"><button disabled={busy} onClick={()=>setReview(false)}>Vazgeç</button><button className="button-green" disabled={busy||!confirmed} onClick={()=>void submit()}>{busy?'Meta başvurusu işleniyor…':'Meta onayına gönder'}</button></div></section></div>}
 </details>;
}
