"""Fail closed production configuration; no remote mutations."""
import os
from pathlib import Path
from urllib.parse import urlsplit
from app.core import settings

def validate_production(service='api'):
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
            path.mkdir(parents=True,exist_ok=True)
            try:
                probe=path/'.write-check';probe.write_bytes(b'');probe.unlink()
            except OSError:errors.append('Kalıcı medya diski yazılabilir değil.')
    if errors:raise RuntimeError('Production yapılandırması eksik: '+' '.join(errors))

def redis_client():
    from redis import Redis
    return Redis.from_url(settings.redis_url,socket_timeout=5,socket_connect_timeout=5)
