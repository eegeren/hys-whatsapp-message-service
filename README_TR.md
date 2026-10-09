# HYS WhatsApp Yönetim Merkezi

HYS Köroğlu Mağazacılık için bağımsız Türkçe iletişim paneli. Yazıcı takip sistemiyle bağlantısı yoktur. İlk sürümün odağı kayıt yönetimi, müşteri/personel Excel aktarımı, izin kontrolü, mesaj hazırlama ve kalıcı DRY_RUN kuyruğudur. Başlangıçta gerçek mesaj gönderilmez. Veritabanı boş açılır; örnek müşteri/personel eklenmez.

## Bu bilgisayarda hemen açın

Panel yerel DRY_RUN ortamında `http://localhost:3000` adresinde çalışır. İlk açılışta kendi yönetici hesabınızı oluşturun. En az 3 karakterli parola desteklenir. Yerel yönetici hesabı kullanıcının isteğiyle hys olarak ayarlanmıştır.

- `BASLAT_YEREL.bat`: Python ve Node.js gerektirir. Bağımlılıkları kurar, frontend derler, migration uygular; API ve DRY_RUN işleyicisini gizli arka plan süreçlerinde çalıştırır.
- `DURDUR_YEREL.bat`: Yalnızca bu projenin kaydedilmiş süreçlerini durdurur.
- Yerel kayıtlar kök klasördeki `hys-local.db` SQLite dosyasındadır. Gerçek kalıcı veritabanıdır; üretim PostgreSQL sürümünün yerine geçmez. Yerel işleyici canlı gönderimi reddeder.
- `api-error.log`, `worker-error.log`: hata günlükleri.
- Başka bir hizmet 3000 portunu kullanıyorsa önce çakışmayı çözün. Docker ve yerel sürümü aynı anda başlatmayın.

## PostgreSQL + Redis + Celery kurulumu

1. Windows için Docker Desktop kurun, WSL2/Linux containers kullanın ve Docker'ı başlatın.
2. `BASLAT.bat` çalıştırın. İlk çalıştırmada `.env.example` üzerinden rastgele veritabanı parolası ve ilk kurulum anahtarı içeren `.env` oluşturulur. Mevcut `.env` değiştirilmez.
3. İlk yönetici ekranında `.env` dosyasındaki `BOOTSTRAP_TOKEN` değerini kullanın. Tokenı başkalarıyla paylaşmayın.
4. Paneli `http://localhost:3000` üzerinden açın. Sağlık kontrolü: `/api/health`.
5. Durdurmak için `DURDUR.bat`. Veriler Docker named volume içinde korunur. `docker compose down -v` verileri siler; normal durdurma için kullanmayın.

API localhost'a bağlanır. PostgreSQL ve Redis host'a açılmaz. Uzak erişim için ayrı HTTPS reverse proxy, erişim sınırlandırması ve uygun yedekleme gereklidir. Webhook için yalnızca gerekli HTTPS uç noktasını yayınlayın.

Yerel ve Docker veritabanları ayrıdır. Yerelden üretime otomatik taşıma yapılmaz; kayıtları dışa/içe aktarabilirsiniz ancak izinleri yeniden kanıtlarıyla doğrulamalısınız.

## İlk test akışı

1. Yönetici hesabını oluşturun. Genel Bakış gerçek boş sayaçlarla açılır.
2. Mağazalar ekranından mağazanızı ekleyin.
3. `templates/musteri_aktarim_sablonu.xlsx` ve `templates/personel_aktarim_sablonu.xlsx` dosyalarını doldurun. Telefon hücreleri metin olmalıdır.
4. Müşteriler/Personeller → Excel/CSV yükle. Önizleme, geçerli satır sayısı ve hatalı satırlar gösterilir. Hata raporu JSON olarak indirilebilir. Aktar düğmesine basılmadan kayıt oluşmaz.
5. `0532 123 45 67` → `+905321234567`. Aynı modülde aynı telefon bir kez kaydedilir. Müşteri ve personel modülleri ayrıdır.
6. Tüm aktarılan kayıtlar `Doğrulanmadı` olur. Excel'deki izin sütunu, alışveriş veya personel olma durumu otomatik izin sağlamaz.
7. İzin düğmesiyle kaynağı, tarihi ve kanıt referansını kaydedin. Müşteride `marketing`, personelde `staff` kapsamı kullanılır. Personelde iletişim dayanağı ve WhatsApp tercihi gerekir. Müşteride İYS belgesi manuel incelenir. Bu kutu gerçek bir İYS API sorgusu değildir.
8. Mesaj Şablonları → yerel taslak oluşturun. DRY_RUN için `Merhaba {{musteri_adi}}` veya `Merhaba {{personel_adi}}, HYS {{magaza_adi}} mağazasında {{tarih}} saat {{saat}} toplantı vardır.` kullanabilirsiniz. Gerçek kişiler eklemeden kendi test verilerinizi kullanın.
9. Kampanya/duyuru oluşturun; mağaza, şehir, grup ve personel ID'leriyle hedef seçin. Değişken alanı JSON nesnesidir: `{"tarih":"12.10.2026","saat":"09:00"}`. Plan zamanı İstanbul (UTC+03:00) olarak UTC'ye çevrilip kaydedilir.
10. Önizle → uygun alıcı sayısı ve hariç bırakılanları görün → Simülasyonu kuyruğa al. Birkaç saniye sonra Gönderim Geçmişi'nde `DRY_RUN` görünür. Bu durum gönderildi/teslim edildi değildir.
11. Sayfayı yenileyin, sistemi durdurup başlatın: kayıtlar korunur. Raporları Excel'e aktarın.

## Meta Cloud API bağlantısı

Meta test numarası için adım adım güvenli yapılandırma: [META_TEST_KURULUM_TR.md](META_TEST_KURULUM_TR.md).

Mevcut WhatsApp Business numaranızla işlem yapmadan önce [COEXISTENCE_TR.md](COEXISTENCE_TR.md) okuyun. Bu uygulama numara kaydı, silme veya taşıma uç noktası çağırmaz.

`.env` alanları:

```dotenv
DRY_RUN=true
LIVE_SEND_ENABLED=false
META_ENVIRONMENT=test
META_ACCESS_TOKEN=...
META_PHONE_NUMBER_ID=...
META_WABA_ID=...
META_APP_SECRET=...
META_VERIFY_TOKEN=...
META_GRAPH_API_VERSION=v25.0
WEBHOOK_PUBLIC_URL=https://sizin-adresiniz/api/webhook
```

Sürüm yapılandırılabilir; hesabınızın desteklediği Graph sürümünü Meta panelinden doğrulayın. Varsayılan sürüm üretim hesabında doğrulanmış değildir. Docker'da değişiklik sonrası `docker compose up -d --force-recreate api worker beat`; yerel sürümde durdurup başlatın. Gizli değerleri Git'e eklemeyin. Arayüz tokenı göstermez veya düzenlemez.

Meta Business portfolio, WABA, uygulama ve yetkili erişim tokenı gerekir. Resmî koleksiyonda `whatsapp_business_management` ve `whatsapp_business_messaging` izinleri açıklanır: [Meta WhatsApp Cloud API koleksiyonu](https://www.postman.com/meta/whatsapp-business-platform/collection/wlk6lh4/whatsapp-cloud-api).

1. Ayrı API test numarasıyla başlayın; test alıcılarını Meta panelinde yetkilendirin.
2. API Ayarları → Gerçek API bağlantısını test et. Numara erişimi ve WABA içindeki üyeliği kontrol edilir. Bağlantı kontrolü mesaj teslimatı, faturalandırma veya Coexistence kanıtı değildir.

Bağlantı doğrulaması bir saat geçerlidir; uzun kampanyalarda yeniden test yapılana kadar yeni canlı mesajlar engellenir. Token veya numara ayarı değişirse önceki doğrulama geçersiz olur.
3. HTTPS webhook callback `/api/webhook` ve doğrulama tokenını Meta uygulamasında tanımlayın; WABA webhook aboneliğini ayrıca Meta'da yapılandırın. GET challenge doğrulaması ve POST `X-Hub-Signature-256` HMAC doğrulaması uygulanır. Gelen mesajlar ve teslimat olayları kalıcı kaydedilir.
4. Mesaj Şablonları → Meta'dan güncelle. Şablon adı, dil, gerçek kategori ve gerçek onay durumu çekilir. Yerel taslağı Meta'ya göndermek gerçek bir yönetim API isteğidir; müşteriye mesaj göndermez. Parametreli/karmaşık şablon oluştururken gerekli örnek bileşenlerini `/api/templates` isteğinin `components` alanına ekleyin; ilk UI yalnızca basit metin taslaklarını destekler.
5. Canlı kullanım için PostgreSQL/Redis/Celery ortamında iki farklı yönetici oluşturun. Kampanyada 1. onay, ikinci yöneticide 2. onay gerekir. Aynı yönetici iki onayı veremez.
6. Geliştirme test mesajı için DRY_RUN=true ve LIVE_SEND_ENABLED=false kalır. Ayrı test uç noktasının kimlik doğrulaması ve açık onay akışı için TEST_MESAJI_TR.md belgesini izleyin. Mevcut işletme numarasına veya Coexistence işlemine dokunmayın.
7. Kampanyada MARKETING onayı gerekir; personelde Meta'nın onayladığı gerçek kategori kullanılır. Şirket içi mesajlar otomatik ücretsiz veya Utility sayılmaz. Hizmet penceresi dışında serbest metin engellenir.

Canlı metin şablonlarının `{{1}}`, `{{2}}` değişkenlerini kampanya JSON'unda `{"1":"değer","2":"değer"}` şeklinde verin. Adlandırılmış parametre biçimleri için bu sürüm canlı gönderimi kapatır; DRY_RUN önizlemesinde adlandırılmış değişkenler desteklenir.

## Güvenli tekil test mesajı

WhatsApp API Ayarları ekranındaki **Test Mesajı Gönder** bölümü genel DRY_RUN kampanya/personel kuyruğundan ayrıdır. Meta test ekranından elle karşılaştırılıp yönetici tarafından onaylanmış Phone Number ID/WABA ID, API ile doğrulanmış kimlik ilişkisi, izinli alıcı listesi ve açık mesaj onayı gerekir. LIVE tek başına ret nedeni değildir; API test niteliğini kesin kanıtlamaz. [TEST_MESAJI_TR.md](TEST_MESAJI_TR.md) yapılandırmayı ve güvenlik sınırlarını açıklar.

## Kuyruk ve durumlar

- Mesaj intentleri PostgreSQL'de kalıcıdır; Redis AOF ve Celery görevleri sevki yönetir. Tek worker ve `1/s` hız sınırı muhafazakâr başlangıç ayarıdır; hesap kapasitesi onayı değildir. Meta rate-limit hatalarında backoff uygulanır; limit aşma mekanizması yoktur.
- `queued` → `dry_run` veya `sending` → `accepted`. `accepted` API kabulüdür; teslimat yalnızca webhook `delivered`/`read` olaylarıyla gösterilir.
- Ret/izin kontrolü hedefleme ve gönderim anında tekrar yapılır. Belirsiz ret içerikleri incelemeye işaretlenir ve güvenli biçimde gönderimden çıkarılır.
- HTTP 429 / belirli limit hata kodlarında en fazla beş deneme, artan bekleme uygulanır. Ağ zaman aşımı/5xx/işleyici kesintisi `uncertain` olur ve otomatik tekrar gönderilmez. Meta tarafında genel tam-bir-kez garantisi olmadığı için mutlak teslimat garantisi verilmez.
- Kampanya/alıcı başına unique kayıt ve veritabanı kilitleri tekrar görevlerin çift mesaj oluşturmasını önler. `sending` durumunda kesilen işlemler 10 dakika sonra manuel incelemeye alınır.
- İptal bekleyen mesajları durdurur. Meta'ya zaten iletilmiş veya ağda devam eden istek geri alınamaz. Duraklatılmış kampanya kayıtları korunur.
- 30 dakika sonra eski aktarım önizlemeleri kuyruk işleyicisi tarafından temizlenir.

## Güvenlik, KVKK ve yedek

Argon2id parola hashleme, HttpOnly/SameSite oturum, işlem başlığı doğrulaması, giriş hız sınırlaması, yönetici/operatör rolleri ve erişim denetim kayıtları vardır. Dosya tipi, 5 MB yükleme ve 40 MB açılmış XLSX boyutu sınırlıdır. Müşteri/personel dışa aktarma ve izin doğrulaması yöneticidedir; operatör telefonları maskeli görür. Excel dışa aktarımında formül enjeksiyonu engellenir.

İYS entegrasyonu **yoktur**. Manuel doğrulama alanı sahte API sorgusu göstermez. Mevzuat ve kurum süreçleri için [İYS SSS](https://iys.org.tr/iys/sss) ve [Ticaret Bakanlığı İYS açıklaması](https://ticaret.gov.tr/ic-ticaret/ticari-elektronik-iletiler/ileti-yonetim-sistemi-iys) temel alınarak kurumun hukuk/uyum sorumlusu süreçleri doğrulamalıdır. Yazılım tek başına mevzuat uyum sertifikası değildir.

`YEDEKLE.bat`: SQLite için tutarlı SQLite backup API, Docker PostgreSQL için `pg_dump -Fc` kullanır. Yedekler `backups/` altında kişisel veri içerir. Şifreleme ve haricî yedek saklama kuruluş tarafından ayrıca kurulmalıdır.

PostgreSQL geri yükleme (boş hedef veritabanında, kontrollü bakım sırasında):

```powershell
$container = docker compose ps -q postgres
docker cp backups\hys-TARIH.dump "${container}:/tmp/restore.dump"
docker compose exec postgres pg_restore -U hys -d hys /tmp/restore.dump
```

Yerel geri yükleme için önce `DURDUR_YEREL.bat`, mevcut veriyi yedekleyin, seçilen SQLite yedeğini `hys-local.db` olarak kopyalayın. Geri yükleme mevcut verilerle birleştirme değildir.

Kayıt silme bağlı mesajların ad/telefon/metnini anonimleştirir ve bekleyen gönderimleri iptal eder. İzin kanıtı içeren denetim kaydı ayrı korunur. Otomatik kişisel veri/denetim saklama süresi ve tam veri sahibi talep iş akışı bu sürümde yoktur; kurumun saklama ve silme politikası uygulanmalıdır.

## Testler

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -q
cd ..\frontend
npm.cmd ci
npm.cmd run build
```

Tarayıcı smoke testi ayrı geçici test veritabanı kullanır; gerçek panelin verilerine örnek kayıt eklemez:

```powershell
.\.venv\Scripts\python.exe -m pip install playwright
.\.venv\Scripts\python.exe scripts\ui-smoke.py
```

Microsoft Edge kurulumu gerekir. Ekran görüntüleri `test-results/` altında oluşur. Gerçek Meta çağrıları için kimlik bilgileri sağlanmadığından canlı bağlantı/teslimat doğrulaması yapılmamıştır. Bu bilgisayarda Docker olmadığı için PostgreSQL/Redis/Celery konteynerleri uçtan uca çalıştırılarak doğrulanmamıştır.

## İlk sürümde açık kalan özellikler

- Otomatik Coexistence Embedded Signup akışı, uygunluk ve hesap/işletme onayları.
- Gerçek İYS API entegrasyonu ve güncel onay senkronizasyonu.
- Güncel doğrulanmış Meta fiyat tarifesi, gerçek maliyet ve bütçe harcama muhasebesi. Bilinmeyen ücret sıfır gösterilmez; bütçe girilmiş canlı kampanya engellenir.
- Görsel, medya başlığı ve URL butonlu şablonların uçtan uca oluşturma/yükleme/gönderme arayüzü. Karmaşık şablonlar eksik payload ile canlı gönderilmez.
- Çok dilli aynı adlı şablonların ayrı varyant yönetimi; bu sürümde şablon adı tektir.
- Adlandırılmış Meta parametreleri, gelişmiş kampanya düzenleme/sürümleme.
- Gelişmiş konuşma atama, medya görüntüleme, yanıt bekleyenlere özel iş akışı ve manuel ret inceleme ekranı. İnceleme durumları kaydedilir; izin ekranından yönetilebilir.
- Otomatik KVKK saklama süreleri, denetim kanıtı silme iş akışı ve yedek şifreleme.
- 10.000 alıcıyla gerçek Meta kapasite, üretim PostgreSQL yük ve teslimat testleri.

## Dosya yapısı

`frontend/`: React + TypeScript + Vite + Tailwind arayüzü. `backend/app/`: FastAPI, SQLAlchemy modelleri, kayıt/aktarım, kampanya, resmî API, webhook ve Celery işleyicisi. `backend/alembic/`: migration. `backend/tests/`: izole backend testleri. `scripts/`: Windows başlatma/durdurma, yedek, Excel ve UI testi araçları. `templates/`: boş Excel şablonları. Kök: Dockerfile, Compose, .env.example ve BAT dosyaları.


Production webhook alımı, gerçek HTTPS gereksinimi ve test kimliklerinden bağımsız geçiş adımları: [WEBHOOK_PRODUCTION_TR.md](WEBHOOK_PRODUCTION_TR.md).
