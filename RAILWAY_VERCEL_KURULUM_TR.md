# HYS Railway + Vercel production kurulumu

Bu çalışma yayınlama hazırlığıdır. Henüz Railway/Vercel hesabında servis oluşturulmadı, gerçek HTTPS adresi üretilmedi veya veri taşınmadı. Yerel `.env`, veritabanı ve çalışan kampanyalar değiştirilmez. Aşağıdaki adres yer tutucuları canlı URL değildir.

## Mevcut yapı ve kararlar

- Frontend React 19 + Vite 6 + TypeScript. Yerel `npm run build` çıktısı `backend/web` olarak korunur. Vercel için ayrı `npm run build:vercel` çıktısı `frontend/dist` olur.
- Mevcut kök Dockerfile frontend ve Python backend'i birlikte paketler. Compose PostgreSQL 17, Redis 7, API, Celery worker ve beat içerir; bu yerel seçenek korunur.
- Railway için `deploy/Dockerfile.railway` yalnızca Python backend'i paketler. API ve worker aynı imajdan, ayrı komutlarla çalışır. Root Directory `/` olmalıdır; konteyner çalışma dizini `/app` olur.
- Alembic 001 → 002 → 003 korunur. API pre-deploy adımında `alembic upgrade head` kullanılır. Worker migration çalıştırmaz; API migration tamamlandıktan sonra oluşturulur. Şema silme/sıfırlama komutu yoktur.
- PostgreSQL mevcut kalıcı mesaj kuyruğunun asıl kaynağıdır. Redis Railway worker lider kilidi ve heartbeat için kullanılır. Railway'de `python -m app.production_worker` kullanılır; ayrıca Celery beat servisi **oluşturulmaz**. Mevcut Celery kodu Compose için korunur.
- Vercel `/api` çağrılarını Railway'e harici rewrite ile yönlendirir. Tarayıcı aynı Vercel origin üzerinde kalır; HttpOnly/Secure/SameSite=strict oturum çerezi korunur. Meta tokenları Vercel'e aktarılmaz. [Vercel harici yönlendirme belgesi](https://vercel.com/docs/routing/rewrites).
- `frontend/vercel.mjs` sunucu tarafındaki `BACKEND_API_ORIGIN` ve `PANEL_PROXY_SECRET` değişkenlerini kullanır. [Programatik Vercel yapılandırması](https://vercel.com/docs/project-configuration/vercel-ts).
- `deploy/railway-services.json` Railway paneline uygulanacak ayar listesidir; otomatik Railway manifesti değildir. Resmî güncel belgede eski config-as-code yöntemi kullanımdan kaldırılmaktadır; ayarları aşağıdaki tabloda belirtildiği gibi dashboard'dan girin. [Railway yapılandırma belgesi](https://docs.railway.com/config-as-code/reference).

## Oluşturma sırası ve kesin komutlar

1. GitHub için yalnızca kaynakları hazırlayın. `.env`, `.bulk-media`, müşteri listeleri, SQLite, loglar ve yedekler yüklenmemeli. Bu çalışma GitHub'a push yapmaz.
2. Vercel projesini GitHub deposundan ekleyin; Root Directory `frontend`. Domains ekranından projenin gerçek, sabit production `*.vercel.app` adresini alın. Railway URL henüz yoksa ilk build'in eksik ayar nedeniyle durması normaldir. Önizleme branch'lerini production sırlarına bağlamayın.
3. Railway projesinde **PostgreSQL** ve **Redis** oluşturun. İkisine de kalıcı volume ve yedekleme ayarlayın. PostgreSQL/Redis'e kamuya açık HTTP domain vermeyin. Yerel taşıma gerekirse PostgreSQL TCP proxy'yi yalnızca taşıma için kullanın.
4. Railway **backend** servisini depodan oluşturun. `RAILWAY_DOCKERFILE_PATH=deploy/Dockerfile.railway` belirleyin; Root Directory `/`. API servisine `/data` volume bağlayın. `deploy/railway-api.env.example` değişkenlerini Railway Variables'a girin. İlk dağıtım kilitli olmalıdır.
5. Backend için Generate Domain ile gerçek Railway HTTPS adresi oluşturun. Bu origin Vercel'deki `BACKEND_API_ORIGIN` olur; sonunda `/api` yazmayın. Railway'deki `PANEL_ORIGIN` gerçek Vercel production origin olmalı, sonunda `/` bulunmamalı.
6. Vercel `PANEL_PROXY_SECRET` ile Railway aynı adlı değişken **aynı**, en az 32 karakterli, parola yöneticisinde üretilmiş değer olmalı. Frontend koduna, VITE_ değişkenine veya sohbet/terminale yazmayın. Vercel Production deploy/redeploy yapın.
7. Veri taşıma bakım penceresini ve güçlü personel parolalarını tamamlayın. Sonra Railway **worker** oluşturun. Başlangıçta `BULK_DISPATCH_ENABLED=false` ve `DEPLOYMENT_SEND_LOCK=true` kalsın. Public Networking kapalı, tek replica ve uyku/serverless modu kapalı olsun.
8. Yeni Meta sırlarını ve salt okunur bağlantıyı doğrulayın; webhook aboneliğini tamamlayın. Gönderim kilidini kaldırmak ve kuyruğu açmak ayrıca yönetici onayı gerektirir. Bu rehberi uygulamak kampanya başlatmaz.

| Servis | Build / kurulum | Pre-deploy | Start | Sağlık / çıktı |
|---|---|---|---|---|
| Railway backend | Dockerfile `deploy/Dockerfile.railway`, repo kökü | `alembic upgrade head` | `python -m app.serve` | `/api/ready`, timeout 120 sn |
| Railway worker | Aynı Dockerfile, repo kökü | Yok | `python -m app.production_worker` | Yetkili API `/api/settings/worker-health` |
| Vercel frontend | `npm ci`, `npm run build:vercel`, Root `frontend` | Yok | Statik frontend; start komutu yok | Output `dist` |

Docker build karşılığı: `docker build -f deploy/Dockerfile.railway -t hys-railway .`. API entry point `PORT` değişkenini okur ve `0.0.0.0` üzerinde dinler. Vercel için `frontend/vercel.mjs` hem komutları hem API rewrite'ını tanımlar.

Backend ve worker: replica 1, Restart ON_FAILURE, max retries 10. Backend volume nedeniyle yatay çoğaltılmamalı. Worker'a HTTP healthcheck path girilmez; HTTP sunucusu yoktur. Redis heartbeat 90 saniyede sona erer; yönetici endpoint'i sağlığı bildirir. Redis/DB erişimi başarısızsa worker ağ gönderimini kilitsiz sürdürmez. [Railway volume davranışı ve kısıtları](https://docs.railway.com/volumes/reference).

## Ayrı environment listeleri

**Railway backend:** `deploy/railway-api.env.example`.

- `DATABASE_URL=${{Postgres.DATABASE_URL}}`, `REDIS_URL=${{Redis.REDIS_URL}}`: servis adlarını kendi Railway adlarınıza göre seçin. Bu referansları Railway Variables editörüne girin. PostgreSQL URL uygulamada kurulu `psycopg` sürücüsüne otomatik uyarlanır.
- `APP_ENVIRONMENT=production`, `PANEL_ORIGIN`, `PANEL_PROXY_SECRET`, `BOOTSTRAP_TOKEN`: son üçü gerçek origin / ayrı güvenli rastgele sırlar. Bootstrap ve proxy anahtarı aynı olmak zorunda değildir; her biri en az 32 karakter.
- `BULK_MEDIA_DIR=/data/bulk-media`: Railway `RAILWAY_VOLUME_MOUNT_PATH` değerini volume bağlanınca sağlar; elle sahte mount değeri girmeyin.
- İlk dağıtım: `DRY_RUN=true`, `LIVE_SEND_ENABLED=false`, `DEPLOYMENT_SEND_LOCK=true`, `BULK_DISPATCH_ENABLED=false`, `LOCAL_WORKER=false`.
- Meta: `META_ENVIRONMENT=production`, yenilenmiş `META_ACCESS_TOKEN`, `META_APP_SECRET`, `META_VERIFY_TOKEN`, `META_GRAPH_API_VERSION`, `META_PHONE_NUMBER_ID=1353767504488829`, doğrulanmış `META_WABA_ID`.
- Webhook: gerçek `WEBHOOK_PUBLIC_URL`, `WEBHOOK_PRODUCTION_PHONE_NUMBER_ID`, doğrulanmış `WEBHOOK_PRODUCTION_WABA_ID`. Production alımı için filtreleri kontrol ederek `WEBHOOK_PRODUCTION_ENABLED=true` yapın; bu bir gönderim ayarı değildir.
- Ayrı geliştirme numarası gerekiyorsa mevcut `META_TEST_*` kimliklerini ayrıca girin; `META_TEST_MESSAGE_ENABLED=false` kalır. Test kimliklerini production ID ile değiştirmeyin.

**Railway worker:** `deploy/railway-worker.env.example`. Backend ile aynı DB, Redis, Meta numara/WABA/token ve aynı gönderim kilitleri. Public URL ve medya volume gerekmez: backend medyayı gönderim onayında Meta'ya yükler; worker yalnızca hazırlanmış Meta medya ID'sini kullanır.

**Vercel:** `deploy/vercel.env.example` içindeki yalnızca iki sunucu tarafı değişken: `BACKEND_API_ORIGIN` ve `PANEL_PROXY_SECRET`. META_*, DATABASE_URL, Redis, PIN veya BOOTSTRAP_TOKEN Vercel'e konmaz. Hiçbir sır VITE_ öneki almaz. Önizlemelere production değişkenlerini kopyalamayın; CORS yalnızca tam production panel origin'ine izin verir.

## Personel giriş güvenliği

Production'da oturum, rol, mutation CSRF başlığı, Origin ve Vercel proxy anahtarı kontrol edilir. Yönetim endpointleri doğrudan Railway URL'sinden anonim açılamaz. Webhook yalnızca GET verify token / POST HMAC ile; login ve bir defalık bootstrap kendi kontrolleriyle, sağlık endpointleri ise hassas veri vermeden çalışır. API dokümantasyonu production'da kapalıdır.

`hys / hys` gibi kısa yerel parolalar cloud'da kabul edilmez. Veri taşıma kullanıcı parola hash'lerini korur fakat eski oturumları taşımaz. Güvenli yerel/SSH konsolunda, hedef DB ortamı seçiliyken `python tools/reset_password.py` çalıştırın. Parola yalnızca gizli girişle alınır, minimum 7 karakter; veritabanına Argon2 hash kaydedilir. Hedef kullanıcının eski oturumları kapatılır. Kullanıcı oluşturma/değiştirme işlemlerini yalnızca yetkili yöneticiler yapmalıdır.

## Verileri kaybetmeden kontrollü taşıma

1. Yerel gönderimleri **yönetici onayıyla** duraklatın; uygulamaya yeni yazmayı kesen bakım penceresi planlayın. API/worker'ı o anda durdurmak da açık onayla yapılır. Dosyayı çalışan SQLite üzerinden normal kopyalamayın.
2. Mevcut `scripts/backup-local.py` SQLite backup API kullanır. Repo kökünde yedek örneği: `.\.venv\Scripts\python.exe scripts/backup-local.py backups/hys-cutover.sqlite`. `backups` dizini önceden oluşturulmalıdır. Yedek kişisel veri içerir; şifreli ve yetkili erişimli saklayın. Cloud yedeklerini Git'e yüklemeyin.
3. Railway hedefinde `alembic upgrade head` sonrası, **henüz setup yapmadan** tüm uygulama tablolarının boş olduğunu doğrulayın. Migration tablosu korunur. Hedefe kullanıcı/mesaj yazılmışsa araç durur; otomatik temizlemez.
4. Salt okunur plan: `.\.venv\Scripts\python.exe backend/tools/transfer_sqlite.py --source backups/hys-cutover.sqlite`. Bu varsayılan mod veri yazmaz; yalnızca tablo sayıları raporlanır.
5. Yalnızca açık taşıma onayından sonra güvenli yerel ortamda `TRANSFER_DATABASE_URL` hedef Railway PostgreSQL bağlantısını tanımlayın (terminalde görüntülemeyin; GUI/secret input kullanın). Uygulama komutu: `.\.venv\Scripts\python.exe backend/tools/transfer_sqlite.py --source backups/hys-cutover.sqlite --apply --confirm-empty-target`.
6. Araç tek hedef transaction içinde boşluk kontrolü, FK sırasıyla kopyalama, ID/sequence korunması ve kayıt sayısı doğrulaması yapar. Müşteri/personel, konuşmalar, şablonlar, kampanyalar, webhook ve audit geçmişi korunur. Kaynakta hiçbir yazma/silme yapmaz. Başarısızlıkta hedef transaction geri alınır.
7. Aktif/scheduled/preparing kampanyalar **hedefte paused** olur. Kabul edilmiş/sent/delivered/read/cancelled mesajlar korunur. API isteği yarıda kalmış `sending` mesajlar `uncertain` olur ve otomatik tekrarlanmaz. Oturum ve geçici önizleme/cache kayıtları taşınmaz. Taşınan geçmiş gösterilir; canlı kuyruk açılmaz.
8. `.bulk-media` içindeki özel medya dosyalarını ayrıca şifreli taşıyıp Railway backend volume'unda `/data/bulk-media` altına aynı dosya adlarıyla yerleştirin. Railway volume dosya araçları veya güvenli SSH/SFTP kullanın; müşteri medyası GitHub'a gitmez. Hazır taslakların SHA-256 kontrolü korunur. [Volume dosya işlemleri](https://docs.railway.com/volumes).
9. Kullanıcı hash'lerini koruyup güçlü cloud parolalarını güvenli konsoldan yenileyin. Backend ve worker'ı kilitli modda açın. Sayıları ve birkaç konuşmanın tarih/ID ilişkilerini yetkili panelden kontrol edin. Yerel API'yi bir süre veri almaya devam ettirirseniz aradaki kayıtlar taşınmayabilir; webhook geçişi bakım penceresinde koordineli yapılmalıdır.
10. Cloud doğrulaması tamamlanmadan yerel veritabanını veya yedeğini silmeyin. Kaynak geri dönüş için kalır. Bir tabloya yeniden içe aktarma / ikinci taşıma otomatik yapılmaz.

PostgreSQL'e gerçek aktarım bu çalışma sırasında yapılmamıştır; Railway PostgreSQL'e bağlı uçtan uca taşıma ve restore provası yayın öncesi ayrıca gereklidir.

## Kalıcı medya

Backend `/data` volume olmadan production modunda başlamaz. JPG/PNG/MP4 taslakları `/data/bulk-media` altında kalır; dosyalar HTTP üzerinden sunulmaz. API ve worker aynı diski paylaşmak zorunda değildir; Meta yüklemesini API kullanıcı onayıyla yapar. Tekli medya akışı korunur. API yalnızca backend'e ait dosyayı doğrulayıp Meta'ya yükler; erişim anahtarını tarayıcıya vermez.

Vercel API yönlendirmesi harici rewrite'dır; yüklemeyi gövdesi 4,5 MB ile sınırlı bir Vercel Function üzerinden geçiren kod eklenmedi. Cloud yayın kabulünde hem 5 MB görsel hem 16 MB video sınırlarına yakın sahte dosyalarla **yükleme/önizleme** kontrolü yapın; Gönder'e basmayın. Gerçek platform proxy sınırları ve zaman aşımı henüz deployment üzerinde test edilmemiştir. [Vercel Function sınırı](https://vercel.com/docs/errors/function_payload_too_large).

## Kalıcı Meta webhook kurulumu

Generate Domain sonrası Callback URL: **Railway'nin gerçek backend HTTPS origin'i + `/api/webhook`**. Henüz gerçek adres oluşmadığından burada uydurma URL verilmez. Aynı tam URL'yi `WEBHOOK_PUBLIC_URL` olarak kaydedin.

Meta Developers → ilgili production uygulaması → WhatsApp → Configuration/Webhooks:

1. Callback URL'ye bu gerçek adresi yazın.
2. Verify Token alanına **Railway backend META_VERIFY_TOKEN ile aynı yeni güvenli değeri** yalnızca yerel gizli girişten girin. Sohbet veya loglara kopyalamayın.
3. Verify and Save ile GET challenge'ı doğrulayın. `messages` alanına Subscribe seçin. POST'lar `META_APP_SECRET` ile X-Hub-Signature-256 kontrolünden geçer; tekrar gelen olaylar dedup edilir.
4. Uygulamanın doğru production WABA'ya abone olduğuna salt okunur `GET /{waba-id}/subscribed_apps` ile bakın. Eksikse yalnızca WABA/uygulama doğrulaması ve ayrı yönetici onayıyla resmî abonelik işlemini yapın; bu hazırlık otomatik POST aboneliği yapmaz.
5. GET token testi yanlış anahtarda 403, doğru challenge'da eşit yanıt vermeli. İmzasız veya yanlış imzalı POST 403 olmalı. Boş event listesiyle imzalı test yalnızca açık onayla yapılabilir; gerçek mesaj gönderilmez.
6. Yetkili panelde webhook son olay zamanını ve gerçek teslimat durumlarını kontrol edin. API kabulünü teslimat saymayın. Railway domain'i servise bağlı kalır; Quick Tunnel gerekmez.

## İfşa edilmiş sırları yenileme

Cloud'a eski ifşa edilmiş tokenı kopyalamayın. Önce tüm cloud gönderim kilitleri kapalı kalsın.

- Meta System User'dan yalnızca gerekli production WABA/WhatsApp izinlerine sahip yeni token üretin; GUI secret variables'a girin. Salt okunur numara CONNECTED/WABA üyeliği/şablon sorgularıyla doğrulayın; ardından eski tokenı iptal edin.
- İlgili Meta uygulamasının App Secret'ını Meta'da kontrollü yenileyin; aynı uygulamayı kullanan diğer sistemlerle bakım penceresi planlayın. Railway API/worker secret values'ını güncelleyin. Gerçek tokenın ait olduğu uygulamayla eşleşmeyi doğrulayın. Eski secret ile webhook imzasını kabul etmeyin.
- Verify Token'ı parola yöneticisinde rastgele yeniden üretin; backend ve Meta Callback doğrulamasında koordineli değiştirin. Sır değerlerini `echo`, terminal komutu argümanı, build logu veya sohbet çıktısıyla taşımayın.
- Vercel/Railway proxy ve bootstrap anahtarlarını da ayrı üretin. PostgreSQL/Redis için platformun ürettiği güçlü parolaları kullanın. Örnek `.env.example` parolasını gerçek sistemde kullanmayın.
- Önceden Git'e sır girmişse geçmişten kaldırmak tek başına yeterli değildir; ilgili sırlar iptal edilir/yenilenir. Bu çalışma `.env` ve DB'lerin takip edilmediğini ve Git'e aday dosyalarda mevcut sır değerleri olmadığını denetler; başka sistemlerdeki geçmişi doğrulamış sayılmaz.

## Sağlık, log, yedek ve yeniden başlatma

- `/api/health`: DB bağlantısı; `/api/ready`: DB + Redis. Railway deploy healthcheck `/api/ready` olmalı. Bu endpointler token/telefon listesi göstermez.
- `/api/settings/worker-health`: yalnızca yetkili yönetici; Redis heartbeat ve gönderim kilitleri. Worker sağlığı ayrı izlenir; web API'nin sağlıklı olması worker'ın çalıştığını kanıtlamaz.
- API access logu kapalıdır; webhook challenge tokenı query string'dedir. Platform URL/request-body loglarını da kapatın/redact edin. Authorization, Cookie, PIN, token, App Secret ve Verify Token loglanmamalı. Worker güvenli JSON olay isimleri yazdırır, exception payload'ını yazdırmaz. SQL parametreleri gizlenir.
- PostgreSQL ve medya volume'unda Railway Backups ekranından günlük/haftalık/aylık programı ve saklama politikasını ayarlayın. Yeni snapshot sonrasında ayrı geçici restore ortamında kayıt sayısı/konuşma/medya ve Alembic revision kontrolü yapın. Production üstüne restore otomatik yapılmaz. [Railway yedekleme](https://docs.railway.com/volumes/backups).
- Ek mantıksal yedek: sürümü PostgreSQL sunucusuyla aynı veya daha yeni `pg_dump` ile, PGHOST/PGPORT/PGUSER/PGDATABASE/PGPASSWORD güvenli ortam değişkenlerindeyken `pg_dump --format=custom --file=backups/hys-production.dump`. Komutta bağlantı URL'si/parola yazılmaz. `pg_restore` yalnızca ayrı doğrulama DB'sine, onaylı bakım işlemi olarak yapılır.
- Backend veya worker yeniden deploy olduğunda migration veriyi silmez. Worker tek replica + Redis lease + DB atomic claim + global 1/s hız sınırıyla çalışır. Başarılar yeniden kuyruğa alınmaz. Duraklatılmış/iptal kampanyalar çalışmaz; belirsiz API sonuçları otomatik tekrarlanmaz. Kapanırken worker yeni işleri durdurur; yarıda kalan sending durumları süre aşınca uncertain olur.
- İşletim arızasında önce gönderimi duraklatın / deployment lock'u açın; sırları veya kuyruğu silmeyin. Backend volume, DB ve Redis erişimini doğrulayın; onay olmadan eski kampanyaları devam ettirmeyin.

## Yayın kabul kontrolü — mesaj göndermeden

Yetkisiz API 401/403, yanlış Origin 403, kısa parola reddi, HTTPS Secure cookie ile giriş, Excel önizleme, gerçek onaylı şablonların salt okunur listesi, JPG/PNG/MP4 taslak önizlemesi ve yeniden deploy sonrası kalıcılığı, gelen kutusu ve WABA/numara filtreleri, webhook HMAC/dedup, worker heartbeat, yedek/restore provası kontrol edilir. İlk aşamada DRY_RUN ve deployment lock açık, LIVE_SEND kapalı, BULK_DISPATCH kapalı kalır. Kullanıcı onayı olmadan gerçek mesaj veya toplu gönderim başlatılmaz.

Yerel Python testleri sahte API ve geçici SQLite ile çalışır. Docker bu bilgisayarda kurulu olmadığından container build testi ve gerçek Railway/Vercel ağ testleri henüz doğrulanmış değildir.
