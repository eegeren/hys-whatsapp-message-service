import hashlib, secrets, json, time
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from argon2 import PasswordHasher
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from app.core import *

@asynccontextmanager
async def lifespan(app):
    from app.deployment import validate_production
    validate_production()
    yield

production=settings.app_environment=='production'
app=FastAPI(title='HYS WhatsApp Yönetim Merkezi',lifespan=lifespan,docs_url=None if production else '/docs',redoc_url=None if production else '/redoc',openapi_url=None if production else '/openapi.json')
app.add_middleware(CORSMiddleware,allow_origins=[settings.panel_origin] if settings.panel_origin else [],allow_credentials=True,allow_methods=['GET','POST','PUT','PATCH','DELETE','OPTIONS'],allow_headers=['Content-Type','X-HYS-Request'])
ph=PasswordHasher()

@app.middleware('http')
async def production_api_guard(request:Request,call_next):
    if settings.app_environment=='production' and request.url.path.startswith('/api/'):
        public=('/api/webhook','/api/health','/api/ready')
        if request.url.path not in public:
            origin=request.headers.get('origin')
            if origin and origin!=settings.panel_origin:return JSONResponse({'detail':'Panel kaynağı yetkili değil.'},status_code=403)
            if request.method=='OPTIONS':return await call_next(request)
            supplied=request.headers.get('X-HYS-Proxy-Secret','')
            if not settings.panel_proxy_secret or not secrets.compare_digest(supplied,settings.panel_proxy_secret):return JSONResponse({'detail':'Panel yönlendirmesi doğrulanamadı.'},status_code=403)
            if request.method not in ('GET','HEAD') and (origin!=settings.panel_origin or request.headers.get('X-HYS-Request')!='1'):
                return JSONResponse({'detail':'İstek kaynağı doğrulanamadı.'},status_code=403)
            if request.url.path not in ('/api/setup','/api/login'):
                try:
                    with Session() as db:actor(request,db)
                except HTTPException as e:return JSONResponse({'detail':e.detail},status_code=e.status_code)
    response=await call_next(request)
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
    return response
def db_session():
    with Session() as db: yield db
def actor(request:Request,db=Depends(db_session)):
    session=db.get(LoginSession,hashlib.sha256(request.cookies.get('hys_session','').encode()).hexdigest())
    if not session or session.expires<now():raise HTTPException(401,'Oturum açmanız gerekiyor')
    if request.method not in ('GET','HEAD') and request.headers.get('X-HYS-Request')!='1':raise HTTPException(403,'İstek doğrulanamadı')
    user=db.get(User,session.user_id)
    if not user or user.role not in ('admin','operator'):raise HTTPException(401,'Yetkili kullanıcı bulunamadı')
    return user
def admin(user=Depends(actor)):
    if user.role!='admin':raise HTTPException(403,'Yönetici yetkisi gerekiyor')
    return user
def require(db,model,id):
    obj=db.get(model,id)
    if not obj:raise HTTPException(404,'Kayıt bulunamadı')
    return obj
def serial(obj):return {c.name:(getattr(obj,c.name).isoformat() if isinstance(getattr(obj,c.name),datetime) else getattr(obj,c.name)) for c in obj.__table__.columns if c.name!='password'}
def connection_ok(db):
    value=db.get(SystemValue,'meta_verified')
    fingerprint=hashlib.sha256((settings.meta_access_token+settings.meta_phone_number_id+settings.meta_waba_id+settings.meta_environment).encode()).hexdigest()
    if not value:return False
    try:
        saved=json.loads(value.value)
        return saved['fingerprint']==fingerprint and now()-datetime.fromisoformat(saved['checked_at'])<timedelta(hours=1)
    except (ValueError,KeyError,TypeError):return False
class Credentials(BaseModel):
    username:str=Field(min_length=3,max_length=100)
    password:str=Field(min_length=3,max_length=128)
    bootstrap_token:str=''
@app.get('/api/setup')
def setup_state(db=Depends(db_session)):
    return {'required':db.scalar(select(func.count(User.id)))==0,'database':'PostgreSQL' if settings.database_url.startswith('postgres') else 'SQLite — yerel test','dry_run':settings.dry_run,'bootstrap_required':bool(settings.bootstrap_token)}
@app.post('/api/setup')
def setup(data:Credentials,request:Request,db=Depends(db_session)):
    if settings.app_environment=='production' and len(data.password)<12:raise HTTPException(422,'Production parolası en az 12 karakter olmalıdır.')
    if db.scalar(select(func.count(User.id))):raise HTTPException(409,'İlk kurulum tamamlandı')
    if settings.bootstrap_token and not secrets.compare_digest(data.bootstrap_token,settings.bootstrap_token):raise HTTPException(403,'Kurulum anahtarı hatalı')
    if not settings.bootstrap_token and request.client.host not in ('127.0.0.1','::1','testclient'):raise HTTPException(403,'Uzak kurulum için BOOTSTRAP_TOKEN ayarlayın')
    db.add(SystemValue(key='setup_lock',value='done'));db.add(User(username=data.username,password=ph.hash(data.password),role='admin'))
    try:db.commit()
    except IntegrityError:db.rollback();raise HTTPException(409,'Kurulum başka oturumda tamamlandı')
    return {'ok':True}
@app.post('/api/login')
def login(data:Credentials,request:Request,response:Response,db=Depends(db_session)):
    if settings.app_environment=='production' and len(data.password)<12:raise HTTPException(401,'Production için güçlü personel parolası gerekir. Güvenli parola yenileme adımını uygulayın.')
    key='login:'+hashlib.sha256((request.client.host+':'+data.username.lower()).encode()).hexdigest();rate=db.get(SystemValue,key)
    count,stamp=json.loads(rate.value) if rate else [0,time.time()]
    if time.time()-stamp>300:count,stamp=0,time.time()
    if count>=10:raise HTTPException(429,'Çok fazla deneme; beş dakika bekleyin')
    db.merge(SystemValue(key=key,value=json.dumps([count+1,stamp])));db.commit()
    user=db.scalar(select(User).where(User.username==data.username))
    try:
        if not user:raise ValueError()
        ph.verify(user.password,data.password)
    except Exception:raise HTTPException(401,'Kullanıcı adı veya parola hatalı')
    token=secrets.token_urlsafe(48)
    db.add(LoginSession(id=hashlib.sha256(token.encode()).hexdigest(),user_id=user.id,expires=now()+timedelta(hours=8)))
    audit(db,user.username,'login','Oturum açıldı');db.commit()
    response.set_cookie('hys_session',token,httponly=True,samesite='strict',secure=settings.app_environment=='production' or request.url.scheme=='https',max_age=28800)
    return {'username':user.username,'role':user.role}
@app.get('/api/me')
def me(user=Depends(actor)):return {'id':user.id,'username':user.username,'role':user.role}
@app.post('/api/logout')
def logout(request:Request,response:Response,user=Depends(actor),db=Depends(db_session)):
    obj=db.get(LoginSession,hashlib.sha256(request.cookies.get('hys_session','').encode()).hexdigest())
    if obj:db.delete(obj);db.commit()
    response.delete_cookie('hys_session');return {'ok':True}
class NewUser(Credentials):role:str='operator'
@app.post('/api/users')
def add_user(data:NewUser,user=Depends(admin),db=Depends(db_session)):
    if settings.app_environment=='production' and len(data.password)<12:raise HTTPException(422,'Personel parolası en az 12 karakter olmalıdır.')
    if data.role not in ('admin','operator'):raise HTTPException(422,'Geçersiz rol')
    if db.scalar(select(User).where(User.username==data.username)):raise HTTPException(409,'Kullanıcı mevcut')
    db.add(User(username=data.username,password=ph.hash(data.password),role=data.role));audit(db,user.username,'user_create',data.username);db.commit();return {'ok':True}
@app.get('/api/dashboard')
def dashboard(user=Depends(actor),db=Depends(db_session)):
    contacts=db.scalars(select(Contact)).all()
    statuses=dict(db.execute(select(Message.status,func.count(Message.id)).where(Message.direction=='out').group_by(Message.status)).all())
    return {'customers':sum(c.kind=='customer' for c in contacts),'eligible':sum(c.kind=='customer' and eligible(c) for c in contacts),'staff':sum(c.kind=='staff' for c in contacts),'stores':db.scalar(select(func.count(Store.id))),'today':db.scalar(select(func.count(Message.id)).where(Message.created>=today_start(),Message.direction=='out',Message.status.in_(['accepted','sent','delivered','read']))),'statuses':statuses,'active':db.scalar(select(func.count(Campaign.id)).where(Campaign.status.in_(['running','scheduled']))),'pending_staff':db.scalar(select(func.count(Campaign.id)).where(Campaign.kind=='staff',Campaign.status.in_(['draft','scheduled']))),'connection':connection_ok(db),'dry_run':settings.dry_run,'cost':None}
@app.get('/api/health')
def health(db=Depends(db_session)):
    db.execute(select(1));return {'ok':True,'dry_run':settings.dry_run}

@app.get('/api/ready')
def ready(db=Depends(db_session)):
    try:
        db.execute(select(1))
        from app.deployment import redis_client
        redis_client().ping()
    except Exception:raise HTTPException(503,'Veritabanı veya kuyruk servisi hazır değil.')
    return {'ok':True}

@app.get('/api/settings/worker-health')
def worker_health(user=Depends(admin)):
    from app.deployment import redis_client
    try:heartbeat=redis_client().get('hys:production-worker:heartbeat')
    except Exception:raise HTTPException(503,'Worker bağlantısı doğrulanamadı.')
    return {'healthy':bool(heartbeat),'dispatch_enabled':settings.bulk_dispatch_enabled,'deployment_send_lock':settings.deployment_send_lock}

from app import contacts, campaigns, messaging, test_messages, bulk
web=Path(__file__).resolve().parents[1]/'web'
if web.exists():app.mount('/',StaticFiles(directory=str(web),html=True),name='web')
