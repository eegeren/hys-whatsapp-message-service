# hys-whatsapp-message-service

HYS WhatsApp Yönetim Merkezi: Türkçe mesaj kutusu, tekli şablon/medya gönderimi ve Excel/CSV kampanya yönetimi. FastAPI, React/Vite, PostgreSQL, Redis ve ayrı kuyruk worker'ı kullanır.

## Production: Railway + Vercel

Tam rehber: [Railway + Vercel kurulumu](RAILWAY_VERCEL_KURULUM_TR.md).

Deploy Logs yalnızca “Starting Container” gösteriyorsa: [Railway başlangıç kontrolü](RAILWAY_BASLANGIC_TR.md).

1. Vercel projesinde Root Directory `frontend` seçin; gerçek production panel adresini alın.
2. Railway projesinde PostgreSQL ve Redis oluşturun; yedekleme ayarlayın.
3. Railway backend için repo kökünü ve `deploy/Dockerfile.railway` dosyasını seçin (`RAILWAY_DOCKERFILE_PATH`). Backend'e `/data` kalıcı volume bağlayın.
4. Railway pre-deploy: `alembic upgrade head`; start: `python -m app.serve`; healthcheck: `/api/ready`. API Railway `PORT` değerini otomatik kullanır.
5. Railway Generate Domain ile gerçek HTTPS adresini alın. Vercel'deki `BACKEND_API_ORIGIN` bu origin; Railway'deki `PANEL_ORIGIN` gerçek Vercel origin olmalı. Aynı `PANEL_PROXY_SECRET` iki servisin gizli deployment değişkenlerinde bulunmalı; frontend kaynaklarına yazılmaz.
6. Vercel install: `npm ci`; build: `npm run build:vercel`; output: `dist`. API rewrite yapılandırması `frontend/vercel.mjs` içindedir.
7. Onaylı bakım penceresinde yerel verileri boş, migration uygulanmış PostgreSQL'e taşıyın. Araç varsayılan olarak yalnızca plan çıkarır; kaynak veritabanını silmez. Kayıt sayısı/ID doğrulaması ve güçlü personel parolası yenilemesini tamamlayın.
8. Railway worker aynı Dockerfile'dan ayrı servis olarak çalışır: `python -m app.production_worker`. Tek replica, sürekli çalışma, public networking kapalı. Railway'de ayrıca Celery beat oluşturmayın.
9. Meta Callback URL gerçek Railway backend HTTPS origin + `/api/webhook` olur. GET challenge ve POST `X-Hub-Signature-256` doğrulanır; Meta `messages` aboneliği ayrıca tamamlanır. Gerçek adres henüz yoksa URL uydurmayın.

Dağıtım ayar listesi: [deploy/railway-services.json](deploy/railway-services.json). Bu dosya dashboard kontrol listesidir; otomatik Railway manifesti değildir.

## Ortam değişkenleri ve gönderim kilitleri

- Yerel yapılandırma: `.env.example` → **Git dışında** `.env`.
- Railway API: [railway-api.env.example](deploy/railway-api.env.example).
- Railway worker: [railway-worker.env.example](deploy/railway-worker.env.example).
- Vercel: [vercel.env.example](deploy/vercel.env.example); yalnızca backend origin ve server-side proxy anahtarı. Meta tokenı, App Secret, Verify Token, PostgreSQL/Redis parolası veya PIN Vercel'e konmaz. Sırlar `VITE_` değişkenlerine yazılmaz.

İlk cloud dağıtımında `DRY_RUN=true`, `LIVE_SEND_ENABLED=false`, `DEPLOYMENT_SEND_LOCK=true`, `BULK_DISPATCH_ENABLED=false` kalır. Gönderim kilidini kaldırmak ayrıca yönetici onayı gerektirir. Taşınan aktif kampanyalar hedefte duraklatılır; eski kabul/teslim/okundu kayıtları yeniden gönderilmez.

Production girişte en az 7 karakterli personel parolası, HttpOnly/Secure oturum çerezi, rol, Origin ve mutation CSRF kontrolleri uygulanır. Kısa yerel parolayı cloud'da kullanmayın. Medya taslakları kalıcı backend volume'unda saklanır; kamuya açık dosya servisi değildir.

## Veritabanı ve yedekleme

Alembic 001–003 şeması korunur. `backend/tools/transfer_sqlite.py --source <SQLite-yedek-dosyası>` salt okunur plan modudur. Gerçek taşıma yalnızca boş PostgreSQL hedefinde açık `--apply --confirm-empty-target` ile yapılır. Hedef bağlantısı gizli `TRANSFER_DATABASE_URL` ortam değişkeninden alınır; komut argümanına yazılmaz.

Kaynak yedeği, kalıcı medya kopyası, PostgreSQL/volume yedek programı ve ayrı restore provası gereklidir. Production üzerinde otomatik reset/drop/restore yapılmaz. Ayrıntılar kurulum rehberindedir.

## Testler — gerçek mesaj göndermeden

Python 3.12 ve Node.js 22 ile:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
.\.venv\Scripts\python.exe -m pytest backend/tests -q
cd frontend
npm ci
npm run build:vercel
```

Backend testleri geçici veritabanı ve sahte Meta yanıtları kullanır. Test amacıyla gerçek gönderim başlatılmaz. Mevcut yerel Docker/Windows başlatma yönergeleri [README_TR.md](README_TR.md) içindedir; o belge eski akışları da açıklar. Güncel cloud kurulumu için bu README ve Railway/Vercel rehberi esas alınmalıdır.

## GitHub'a güvenli yükleme

`.env`, özel env dosyaları, token/anahtar dosyaları, müşteri Excel/CSV'leri, yerel medya, veritabanı, yedek, log, cache ve bağımlılık dizinleri Git dışında tutulur. Yalnızca incelenmiş boş Excel şablonları ve sentetik test fixture'ı istisnadır. Gerçek değerleri örnek dosyalara yazmayın; `.git` dizinini arşivleyip paylaşmayın.

Yerel geçmiş/nesnelerde daha önce görülmüş bir sır için `.gitignore` yeterli değildir: anahtar iptal/yenileme ve gerekli geçmiş temizliği ayrıca yapılır. Güvenlik denetiminin ayrıntıları [GitHub hazırlık raporu](GITHUB_HAZIRLIK_TR.md) içindedir.

GitHub push, gerçek veritabanı taşıması ve gerçek WhatsApp gönderimi yalnızca açık yönetici onayıyla gerçekleştirilir.
