# Railway backend başlangıcı

Kök Dockerfile daha önce CMD veya ENTRYPOINT tanımlamıyordu. Railway bu dosyayı seçip Start Command boş bırakıldığında FastAPI başlamıyordu. Kök Dockerfile artık `CMD ["python", "-m", "app.serve"]` içerir. Railway için hazırlanmış `deploy/Dockerfile.railway` zaten bu komutu kullanır; ENTRYPOINT yoktur. Railway hesabındaki hangi dosyanın seçili olduğu yerel kod incelemesiyle doğrulanamaz.

## Backend servisinde girilecek ayarlar

| Alan | Değer |
| --- | --- |
| Root Directory | `/` |
| Variables → RAILWAY_DOCKERFILE_PATH | `deploy/Dockerfile.railway` |
| Start Command | `python -m app.serve` |
| Pre-deploy Command | `alembic upgrade head` |
| Healthcheck Path | `/api/ready` |
| Healthcheck Timeout | `120` saniye |
| Volume mount | `/data` |
| Restart Policy | On Failure |

Start Command'da `$PORT` yazmak gerekmez: Python bu değişkeni doğrudan okur, `0.0.0.0` üzerinde dinler. Yerelde değişken yoksa 3000 kullanılır. Dockerfile'daki EXPOSE 3000, Railway PORT değerini sabitlemez. Backend imajının çalışma dizini `/app` olduğundan `backend/` öneki veya `cd backend` gerekmez.

Bu ayarlar backend servisi içindir. Ayrı worker servisi aynı Railway Dockerfile ile `python -m app.production_worker` kullanır; HTTP portu veya healthcheck yolu yoktur. Başlangıç sorununu çözmek için worker gönderim kilitlerini açmayın.

## Variables

### Build sırasında `/backend: not found`

Logda `frontend` aşaması ve `node:22-alpine` görünüyorsa kök Dockerfile seçilmiştir; backend'e özel Railway Dockerfile yalnızca Python kullanır. Kök Dockerfile frontend çıktısını artık açıkça `/frontend/dist` içine üretip aynı yoldan kopyalar. Eski `/backend/web` aşamalar arası çıktı yoluna bağımlılık kaldırılmıştır. Yerel Vite build'in varsayılan `backend/web` çıktısı değişmez.

Backend servisi için `RAILWAY_DOCKERFILE_PATH=deploy/Dockerfile.railway` ve Root Directory `/` seçin. `/backend` veya `/frontend` root seçmeyin: bu Dockerfile repo kökündeki `backend/requirements.txt` dosyasını kopyalar. Son commit ile yeniden build başlatın. Yeni build logunda hâlâ Node aşaması görünüyorsa Railway Dockerfile seçimi uygulanmamıştır. Cache temizliği, yanlış Dockerfile veya Root Directory seçimini tek başına düzeltmez.

Railway yerel `.env` dosyasını otomatik taşımaz. Sırları yalnızca Railway Variables alanına girin, Git'e eklemeyin. Tam liste: [API örnek değişkenleri](deploy/railway-api.env.example).

- `DATABASE_URL`: PostgreSQL servisinin referansı, örneğin servis adı Postgres ise `${{Postgres.DATABASE_URL}}`. Gerçek servis adına göre seçin. `postgres://` ve `postgresql://` otomatik olarak psycopg sürücüsüne uyarlanır.
- `REDIS_URL`: Redis servisinin referansı; örneğin `${{Redis.REDIS_URL}}`.
- `APP_ENVIRONMENT=production`, `LOCAL_WORKER=false`.
- `PANEL_ORIGIN`: gerçek Vercel HTTPS panel origin'i, sonunda `/` olmadan.
- `PANEL_PROXY_SECRET` ve `BOOTSTRAP_TOKEN`: her biri en az 32 karakterli ayrı güvenli sır. Proxy anahtarı Vercel'dekiyle eşleşmelidir.
- `BULK_MEDIA_DIR=/data/bulk-media`: gerçek backend volume'u bağlayın. `RAILWAY_VOLUME_MOUNT_PATH` Railway tarafından sağlanır; elle sahte değer girmeyin.
- İlk dağıtımda `DEPLOYMENT_SEND_LOCK=true`, `BULK_DISPATCH_ENABLED=false`, `DRY_RUN=true`, `LIVE_SEND_ENABLED=false` tutun. Yerel `.env` bu düzeltmede değiştirilmedi.
- Mevcut Meta sırlarını koruyarak gerekli `META_*` ve webhook değişkenlerini güvenli Variables alanında yapılandırın. API başlangıcı Meta'ya mesaj göndermez veya abonelik/kayıt işlemi yapmaz.

Railway ortam kimliği mevcutsa production ve ayrı worker/gönderim kilidi varsayılanları uygulanır; açıkça girilmiş değerler değiştirilmez. `APP_ENVIRONMENT=local` Railway'de reddedilir. Eksik PostgreSQL ayarıyla SQLite'a sessizce geçilmez.

## Log ve sağlık kontrolü

Yeni sürümde sırasıyla `[HYS] API başlangıcı`, `API hazırlanıyor: 0.0.0.0:<PORT>`, `PostgreSQL erişimi ve migration kontrol ediliyor`, `Redis erişimi kontrol ediliyor`, `API hazır` mesajlarını görmelisiniz. “API hazırlanıyor” henüz başarılı dinleme anlamına gelmez; Uvicorn'un startup tamamlandı logu ve `/api/ready` HTTP 200 yanıtı gerekir.

Yanlış PORT veya yapılandırma kontrollü çıkış kodu 1 verir. PostgreSQL bağlantısı ve pool bekleme için 5 saniyelik zaman aşımı vardır. Başlangıç ve readiness kontrol sorguları kendi transaction'larında `SET LOCAL statement_timeout` ile 5 saniyede sınırlandırılır; migration ve normal iş sorgularına bu sınır uygulanmaz. Redis bağlantısı/işlemleri için 5 saniyelik zaman aşımı vardır. Bunlar her işlem için ayrı sınırlardır, toplam başlangıç süresi için tek bir 5 saniye garantisi değildir.

PostgreSQL kontrolü yalnızca `SELECT 1` ve Alembic revision okuması yapar. Migration eksikse başlangıç durur; otomatik tablo oluşturma/silme yapılmaz. Pre-deploy `alembic upgrade head` mevcut migration'ları uygular, veri sıfırlama komutu değildir. Mevcut üretim verileriniz için deployment öncesi yedek politikasını koruyun.

`Kalıcı medya diski yazılabilir değil` hatasında gerçek volume mount'unu ve Dockerfile seçimini kontrol edin. Kök yerel Dockerfile `hys` kullanıcısı kullanır; volume erişim izinleri farklı olabilir. Railway için `deploy/Dockerfile.railway` seçin; kalıcı disk kontrolünü kaldırmayın.

Sır içerebilen bağlantı istisnaları loga basılmaz. PostgreSQL, migration ve Redis hatalarında yalnızca sabit Türkçe açıklama gösterilir. Bu kontroller WhatsApp mesajı göndermez, kayıtları silmez veya kuyruk başlatmaz.

Kod yerel izole testlerle doğrulanır; Railway'deki gerçek Variables, container ve ağ durumları ancak yeniden deployment sonrasında değerlendirilebilir. Bu makinede Docker yoksa gerçek Docker build testi ayrıca Railway'de yapılmalıdır.

Resmî kaynaklar: [Railway Start Command](https://docs.railway.com/deployments/start-command), [Dockerfile seçimi](https://docs.railway.com/builds/dockerfiles).
