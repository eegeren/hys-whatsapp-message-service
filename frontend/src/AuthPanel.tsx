import BrandLogo from './BrandLogo';
import PasswordInput from './PasswordInput';
import {useState} from 'react';
import {MessageCircle,ShieldCheck} from 'lucide-react';

type Row=Record<string,any>;
type Props={setup:Row|null;initialError:string;api:(path:string,method?:string,body?:any)=>Promise<any>;onLogin:(user:Row)=>void;onSetup:()=>void};

export default function AuthPanel({setup,initialError,api,onLogin,onSetup}:Props){
 const [register,setRegister]=useState(Boolean(setup?.required));
 const [busy,setBusy]=useState(false),[error,setError]=useState(initialError),[notice,setNotice]=useState('');
 const first=register&&Boolean(setup?.required);
 function switchMode(){setRegister(!register);setError('');setNotice('');}
 async function submit(e:React.FormEvent<HTMLFormElement>){
  e.preventDefault();const form=e.currentTarget;const values=new FormData(form);
  const username=String(values.get('username')||''),password=String(values.get('password')||'');
  setBusy(true);setError('');setNotice('');let adminSession=false;
  try{
   if(!register){onLogin(await api('/login','POST',{username,password}));return;}
   if(first){
    await api('/setup','POST',{username,password,bootstrap_token:String(values.get('bootstrap_token')||'')});
    onSetup();
   }else{
    const admin=await api('/login','POST',{username:String(values.get('admin_username')||''),password:String(values.get('admin_password')||'')});
    adminSession=true;
    if(admin.role!=='admin')throw Error('Yeni personel hesabını yalnızca yönetici oluşturabilir.');
    await api('/users','POST',{username,password,role:'operator'});
   }
   form.reset();setRegister(false);setNotice('Hesap oluşturuldu. Yeni kullanıcı adı ve parolanızla giriş yapın.');
  }catch(e){setError(e instanceof Error?e.message:'İşlem tamamlanamadı.');}
  finally{
   if(adminSession){try{await api('/logout','POST');}catch{setError('Hesap işlemi tamamlandı ancak yönetici oturumu kapatılamadı. Sayfayı yenileyin.');}}
   setBusy(false);
  }
 }
 return <div className="login">
  <div className="login-brand"><BrandLogo className="login-brand-logo"/><p>KÖROĞLU MAĞAZACILIK</p><h1>WhatsApp.<br/>Tek bir merkezde.</h1><p>Mesajlar, izinli toplu gönderimler ve bağlantı ayarları.</p><div className="login-foot"><ShieldCheck size={18}/> Resmî WhatsApp Cloud API</div></div>
  <div className="login-form"><BrandLogo className="login-mobile-logo"/><MessageCircle className="green" size={34}/>
   <h2>{register?'Yeni hesap oluştur':'Tekrar hoş geldiniz'}</h2>
   <p>{first?'İlk yönetici hesabınızı kurulum anahtarıyla oluşturun.':register?'Yeni personel hesabı oluşturmak için yönetici doğrulaması gerekir.':'Devam etmek için hesabınıza giriş yapın.'}</p>
   {error&&<div className="error" role="alert">{error.replace(/^Error:\s*/,'')}</div>}
   {notice&&<p className="green" role="status">{notice}</p>}
   <form key={register?'register':'login'} onSubmit={submit}>
    <div className="form-grid">
     <label className="field"><span>Kullanıcı adı *</span><input name="username" required minLength={3} maxLength={100} autoComplete="username"/></label>
     <PasswordInput name="password" label="Parola" minLength={register?7:3} autoComplete={register?'new-password':'current-password'} hint={register?'En az 7 karakter kullanın.':undefined}/>
     {first&&setup?.bootstrap_required&&<label className="field"><span>Kurulum anahtarı *</span><input name="bootstrap_token" type="password" required autoComplete="off"/></label>}
     {register&&!first&&<>
      <label className="field"><span>Yönetici kullanıcı adı *</span><input name="admin_username" required autoComplete="off"/></label>
      <PasswordInput name="admin_password" label="Yönetici parolası"/>
     </>}
    </div>
    <button className="primary form-submit" disabled={busy||!setup}>{busy?'İşleniyor…':register?'Hesap oluştur':'Giriş yap'}</button>
   </form>
   <div className="auth-switch"><span>{register?'Zaten hesabınız var mı?':'Hesabınız yok mu?'}</span> <button type="button" disabled={busy||!setup} onClick={switchMode}>{register?'Giriş yapın':'Yeni hesap oluştur'}</button></div>
   <div className="login-note"><ShieldCheck size={16}/> Yalnızca yetkili HYS personeli erişebilir.</div>
  </div>
 </div>;
}
