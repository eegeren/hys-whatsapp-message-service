# Production webhook altyapısı

Uç nokta: GET /api/webhook ve POST /api/webhook. GET hub.mode=subscribe, hub.verify_token ve hub.challenge alanlarını kontrol edip challenge değerini düz metin olarak döndürür. POST ham gövde için META_APP_SECRET ile HMAC-SHA256 hesaplar ve X-Hub-Signature-256 imzasını sabit süreli karşılaştırır. İmzasız/değiştirilmiş içerik reddedilir. Bu işlemler mesaj göndermez ve DRY_RUN'dan bağımsız olarak olay alabilir.

## Yerel kurulumda tamamlananlar

İstek özeti events tablosuna; mesaj ve teslimat olayları olay bazında tekil kimlikle webhook_items tablosuna kaydedilir. Aynı mesaj farklı paketle geldiğinde veya teslimat olayı tekrarlandığında yeniden işlenmez. Gelen metin messages tablosunda direction=in, status=received ve unread=true olarak saklanır. Metin dışı mesajlar tür etiketiyle görünür; medya indirilmez. İlişkili kişi bulunamazsa eşleşmeyen kişi olarak gösterilir. STOP/RET geri çekme akışı korunur.

Teslimat olayları sent/delivered/read sırasını geriye düşürmez. Henüz ilişkili çıkış mesajı bulunamayan teslimat olayları da webhook_items içinde saklanır; otomatik yeniden eşleştirme bu sürümde yoktur. Geçersiz veya işlenemeyen istek 200 ile başarılı sayılmaz; veritabanı işlemi geri alınır. Hata kayıtlarına yalnızca hata kodu ve Türkçe açıklama yazılır, keyfi Meta hata metni veya gizli anahtar kaydedilmez.

Panel → Gelen Mesajlar gerçek webhook kayıtlarını gösterir ve 10 saniyede bir yenilenir. WhatsApp API Ayarları → Production webhook alımı yapılandırma durumunu gösterir; dış erişimi veya Meta aboneliğini doğrulanmış gibi göstermez.

## Eksik dış erişim

Bu bilgisayarda yapılandırılmış alan adı/HTTPS Callback URL veya caddy/cloudflared/ngrok/Docker aracı bulunmadı. Çalışan adres yalnızca localhost:3000; Meta dışarıdan bu adrese erişemez. Gerçek Callback URL oluşturulmadı, WEBHOOK_PUBLIC_URL boş korundu. HTTPS ve Meta üzerinden gerçek webhook alımı henüz doğrulanmadı.

Gerçek alan adı ve internete açık sunucu hazır olduğunda DNS kaydını o sunucuya yönlendirin, 80/443 portlarını erişilebilir yapın. Yerel kurulumu dışarı açacaksanız gerçek HTTPS tünel hizmeti veya ters proxy, erişim yönlendirmesi ve bilgisayarın sürekli çalışması gerekir.

Hazır HTTPS dosyaları:
- deploy/Caddyfile: Docker api:3000 hedefi; yalnızca /api/webhook dışarı açılır.
- deploy/Caddyfile.local: bu Windows bilgisayarındaki 127.0.0.1:3000 hedefi; yine yalnızca webhook dışarı açılır.
- docker-compose.webhook.yml: alan adı gerektiren isteğe bağlı Caddy servisi, otomatik TLS ve kalıcı sertifika depoları. Docker burada kurulu olmadığı için çalıştırılıp doğrulanmadı.

Gerçek alan adını .env içinde HYS_WEBHOOK_DOMAIN alanına yazın (yalnızca DNS adı). WEBHOOK_PUBLIC_URL alanına HTTPS hizmetinin gerçekten sağladığı adresin /api/webhook ile biten TAM callback adresini yazın. Bu belge örnek/sahte bir callback adresi üretmez.

Docker sunucusunda: docker compose -f docker-compose.yml -f docker-compose.webhook.yml up -d --build. Yerel Caddy kuruluysa .env'den gerçek HYS_WEBHOOK_DOMAIN değişkenini Caddy sürecine güvenle aktararak caddy run --config deploy/Caddyfile.local kullanın; mevcut bilgisayarda bu hizmet kurulmadı. Caddy/uvicorn erişim günlükleri kapalıdır; challenge sorgusundaki Verify Token loglanmamalıdır. Başka proxy/tünel kullanıyorsanız sorgu ve gövde kayıtlarını kapatın. Sadece webhook yolunu açın; paneli dışarı yayınlamayın.

## Meta'ya yazılacak değerler

Meta Developers → ilgili uygulama → WhatsApp → Configuration → Webhooks / Callback URL bölümüne:
1. Callback URL: WEBHOOK_PUBLIC_URL alanına yazdığınız gerçek HTTPS adresi, yol /api/webhook.
2. Verify Token: yerel .env dosyasındaki MEVCUT META_VERIFY_TOKEN değeri. Dosyayı yerel editörde açıp değeri Meta alanına aktarın. Bu token sohbet, terminal veya panelde gösterilmez. Access Token ya da App Secret bu alana yazılmaz.
3. Verify and Save işlemini yapın; WhatsApp Business Account için messages alanına abone olun. Uygulamanın ilgili WABA aboneliğini Meta panelinde ayrıca kontrol edin. Bu görev Meta'da abonelik oluşturma API çağrısı yapmadı.

POST imza kontrolü için META_APP_SECRET ilgili Meta uygulamasına ait olmalıdır. Mevcut sırlar korunmuştur. GET challenge ve sahte imzalı yerel testler, gerçek Meta dış erişim doğrulaması yerine geçmez.

## Kontrollü production alımı: test kimlikleri değişmez

Gerçek kayıtlı üretim Phone Number ID ve WABA ID değerlerini Meta ekranında karşılaştırdıktan sonra kök .env içinde ayrı alanları doldurun:
- WEBHOOK_PRODUCTION_PHONE_NUMBER_ID: kayıtlı gerçek numaranın ID'si.
- WEBHOOK_PRODUCTION_WABA_ID: gerçek numaranın WABA ID'si.
- WEBHOOK_PRODUCTION_ENABLED=true: yalnızca bu kimlik çifti için ek webhook ALIMINI açar.

Numara test Phone Number ID ile aynıysa ayrı üretim alımı kabul edilmez. WEBHOOK_PRODUCTION_ENABLED varsayılan false; gerçek üretim ID'leri sağlanmadığı için boş bırakıldı. Bu ayarlar META_PHONE_NUMBER_ID, META_WABA_ID veya META_TEST_* değerlerinin yerine geçmez; test akışı korunur. Üretim olayında hem metadata.phone_number_id hem entry.id (WABA) eşleşmelidir. Backend yeniden başlatılmalıdır.

DRY_RUN ve LIVE_SEND_ENABLED değiştirilmez. Üretim gönderimine geçiş bu görevin kapsamı değildir. Uygulama numara kaydetme/taşıma/silme veya Coexistence işlemi yapmaz.

Kaynaklar: Meta webhook GET/POST doğrulaması: https://whatsapp.github.io/WhatsApp-Nodejs-SDK/api-reference/webhooks/start/ ; Caddy istek boyutu: https://caddyserver.com/docs/caddyfile/directives/request_body .
