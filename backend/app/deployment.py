"""Fail closed production configuration; no remote mutations."""
import os
from pathlib import Path
from urllib.parse import urlsplit
from app.core import settings

class ProductionConfigurationError(RuntimeError):
    """Only fixed, credential-free messages may be used here."""

def validate_production(service='api'):
    if os.environ.get('RAILWAY_ENVIRONMENT_ID') and settings.app_environment!='production':
        raise ProductionConfigurationError('Railway üzerinde APP_ENVIRONMENT=production olmalıdır.')
    if settings.app_environment!='production':return
    errors=[]
    if service=='api':
        origin=urlsplit(settings.panel_origin)
        if origin.scheme!='https' or not origin.hostname or not origin.hostname.endswith('.vercel.app') or origin.path or origin.query or origin.fragment or origin.username or origin.port:
            errors.append('PANEL_ORIGIN gerçek https://...vercel.app adresi olmalıdır (sonunda / olmadan).')
        if len(settings.panel_proxy_secret)<32:errors.append('PANEL_PROXY_SECRET en az 32 karakter olmalıdır.')
        if len(settings.bootstrap_token)<32:errors.append('BOOTSTRAP_TOKEN en az 32 karakter olmalıdır.')
    if not settings.database_url.startswith('postgresql+psycopg://'):errors.append('Production DATABASE_URL PostgreSQL olmalıdır.')
    if not settings.redis_url.startswith(('redis://','rediss://')):errors.append('REDIS_URL geçersiz.')
    if service=='api':
        mount=os.environ.get('RAILWAY_VOLUME_MOUNT_PATH','')
        path=Path(settings.bulk_media_dir)
        if not mount or not path.is_absolute() or not path.is_relative_to(Path(mount)):
            errors.append('BULK_MEDIA_DIR Railway kalıcı volume içinde olmalıdır.')
        else:
            try:
                path.mkdir(parents=True,exist_ok=True)
                probe=path/'.write-check';probe.write_bytes(b'');probe.unlink()
            except OSError:errors.append('Kalıcı medya diski yazılabilir değil.')
    if errors:raise ProductionConfigurationError('Production yapılandırması eksik: '+' '.join(errors))

def redis_client():
    from redis import Redis
    return Redis.from_url(settings.redis_url,socket_timeout=5,socket_connect_timeout=5)

def check_startup_dependencies():
    """Read-only checks bounded by database and Redis connection timeouts."""
    if settings.app_environment!='production':return
    from sqlalchemy import text
    from app.core import engine
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    config=Config()
    config.set_main_option('script_location',str(Path(__file__).resolve().parents[1]/'alembic'))
    expected=set(ScriptDirectory.from_config(config).get_heads())
    print('[HYS] PostgreSQL erişimi ve migration kontrol ediliyor.',flush=True)
    try:
        with engine.connect() as db:
            db.execute(text("SET LOCAL statement_timeout = '5s'"))
            db.execute(text('SELECT 1'))
            revisions=set(db.execute(text('SELECT version_num FROM alembic_version')).scalars())
        if revisions!=expected:raise RuntimeError()
    except Exception:
        raise RuntimeError('PostgreSQL erişimi veya migration hazır değil. DATABASE_URL ve pre-deploy alembic upgrade head adımını kontrol edin.') from None
    print('[HYS] Redis erişimi kontrol ediliyor.',flush=True)
    try:
        cache=redis_client()
        try:cache.ping()
        finally:cache.close()
    except Exception:
        raise RuntimeError('Redis erişimi doğrulanamadı. REDIS_URL ve Redis servis durumunu kontrol edin.') from None
    print('[HYS] API hazır: PostgreSQL ve Redis kontrolleri başarılı.',flush=True)
