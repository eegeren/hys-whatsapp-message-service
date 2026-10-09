"""PORT-aware Railway API entry point; no embedded worker."""
import os

def run():
    print('[HYS] API başlangıcı: ortam yapılandırması kontrol ediliyor.', flush=True)
    try:
        port=int(os.environ.get('PORT','3000'))
        if not 1<=port<=65535:raise ValueError()
    except ValueError:
        print('[HYS] Başlangıç durdu: PORT 1–65535 arasında bir sayı olmalıdır.',flush=True)
        return 1
    try:
        from app.deployment import validate_production,ProductionConfigurationError
    except Exception:
        # Validation exceptions may contain connection credentials.
        print('[HYS] Başlangıç durdu: ortam değişkenleri okunamadı. DATABASE_URL ve değişken türlerini kontrol edin; değerler gizlendi.',flush=True)
        return 1
    try:
        validate_production('api')
    except ProductionConfigurationError as exc:
        print('[HYS] Başlangıç durdu: '+str(exc),flush=True)
        return 1
    except Exception:
        print('[HYS] Başlangıç durdu: production yapılandırması doğrulanamadı; ayrıntılar gizlendi.',flush=True)
        return 1
    import uvicorn
    print(f'[HYS] API hazırlanıyor: 0.0.0.0:{port}; worker ayrı servistir.',flush=True)
    uvicorn.run('app.main:app',host='0.0.0.0',port=port,access_log=False,proxy_headers=False)
    return 0

if __name__=='__main__':
    raise SystemExit(run())
