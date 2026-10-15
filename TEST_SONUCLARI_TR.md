# Production webhook altyapısı — 8 Ekim 2026

89 backend testi ve panel derlemesi geçti. GET challenge, imza reddi, değiştirilmiş gövde, olay bazında tekrar kontrolü, farklı paketlerdeki tekrarlar, sırası değişen teslimat durumları, bağımsız production kimlik eşleştirmesi ve hatalı gövde rollback testleri başarılı. İzole tarayıcı testi imzalı sahte mesajın Gelen Mesajlar ekranında görünmesini doğruladı. Testler gerçek Meta webhook kabulünü kanıtlamaz.

003 migration yerel veritabanına uygulandı. Backend/worker yeniden başlatıldı; panel çalışıyor. DRY_RUN=true, LIVE_SEND_ENABLED=false korundu. Mevcut META_* test kimlikleri ve sırlar korunmuştur. Ayrı production alımı kapalı; gerçek production ID çifti verilmedi. Kullanıcı alan adı/HTTPS hizmeti olmadığını belirtti; Callback URL boş, dış erişim ve Meta aboneliği doğrulanmadı. Caddy yerel/Docker yapılandırmaları hazırlandı ancak hizmetler kurulu olmadığı için başlatılmadı. Gerçek mesaj gönderilmedi.

Aşağıdaki kayıtlar önceki aşamalara aittir.

# Panelden kendi test alıcısını yapılandırma — güncel sonuç

77 backend testi, TypeScript/Vite derlemesi ve izole tarayıcı testi geçti. Yönetici kimlik onayı, E.164 yerel telefon kaydı, açık Meta alıcı doğrulaması beyanı, .env içindeki gizli değerlerin korunması, izin listesinin hemen uygulanması ve yetkisiz/izinsiz kayıtların engellenmesi doğrulandı.

Çalışan backend verilen test kimliklerini ve META_TEST_MESSAGE_ENABLED=true ayarını yükledi. DRY_RUN=true, LIVE_SEND_ENABLED=false. Gerçek salt okunur Graph kontrolünde numara/WABA ilişkisi ve hello_world / en_US şablonunun onayı doğrulandı; account_mode=LIVE. API geliştirme numarası niteliğini kesin kanıtlamaz; yönetici ekran karşılaştırması henüz verilmedi. Kendi telefon numarası panelden girilmeyi bekliyor. Gerçek mesaj gönderilmedi. .env Git tarafından takip edilmiyor.

Aşağıdaki kayıtlar önceki aşamalara aittir.

# Güncel güvenli test numarası onayı — 8 Ekim 2026

74 backend testi geçti. TypeScript/Vite derlemesi ve 13 ekranı kapsayan izole tarayıcı testi geçti. Yeni kimlik karşılaştırması, yönetici onayı, LIVE/unknown davranışı, ayar değişiminde onay geçersizleşmesi, bilinen üretim ID engeli ve denetim kaydı test edildi. Testlerde sahte Graph API yanıtları kullanıldı; bu güncellemede gerçek Meta API erişimi ve gerçek mesaj gönderimi yapılmadı.

LIVE artık tek başına gönderimi engellemez. Test niteliği otomatik SANDBOX sayılmaz; Meta Developers test ekranına dayanan açık yönetici beyanı zorunludur. DRY_RUN açık, canlı kampanya/personel gönderimi kapalı, özellik etkinleştirme ayarı kapalı ve alıcı listesi boş bırakılmıştır. .env Git tarafından izlenmiyor. Gerçek gizli değerler korunmuştur.

Aşağıdaki eski kayıtlar önceki sürüme aittir; eski SANDBOX/LIVE kısıtı artık uygulanmaz.

# Doğrulama sonuçları — 8 Ekim 2026

## Son Meta bağlantı kontrolü

Kullanıcının yerel `.env` dosyasına eklediği ayarlarla gerçek salt okunur Graph API testi başarılı oldu. Phone Number ID erişimi ve WABA ilişkisi doğrulandı; panelin bağlantı durumu güncellendi. Gizli değerler rapora, terminale veya loglara yazılmadı. DRY_RUN açık ve LIVE_SEND_ENABLED kapalı tutuldu; müşteri/personel mesajı gönderilmedi. Bu sonuç teslimat veya Coexistence doğrulaması değildir.

Docker bu bilgisayarda bulunmadığından yerel backend ve işleyici yeniden başlatıldı. Windows venv başlatıcısının alt süreçlerini durdurmama hatası giderildi. Boş miras alınmış ortam değişkenlerinin `.env` ayarlarını gölgelemesi önlendi. Erişim günlükleri hassas webhook query değerlerini kaydetmemesi için kapatıldı. Panel hata gösterimine Meta hata kodu eklendi.

## İlk sürüm sonuçları

## Güvenli test mesajı güncellemesi

69 backend testi ve TypeScript/üretim derlemesi başarılı. Ayrı geçici veritabanı ve sahte Graph sunucusu ile Playwright testinde test mesajı hazırlama, iki açık onay, WhatsApp mesaj ID'si ve teslimat bilinmiyor gösterimi doğrulandı. Eski kayıt/aktarım/DRY_RUN akışları da test edildi. Gerçek Meta mesajı gönderilmedi.

Sunucu kontrolleri: rol, E.164, sabit ID eşleşmesi, anlık SANDBOX ve WABA kontrolü, onaylı hello_world, izinli alıcı listesi, onay süresi/ayar bağlama, tekrarlı istekten tek gönderim, dakikalık/günlük sınırlar, güvenli hata kayıtları ve test webhook durumu doğrulandı. 002 migration yerel kalıcı veritabanına uygulandı.

Mevcut Phone Number ID üzerinde yapılan yalnızca GET sorgusu Meta account_mode=LIVE sonucunu verdi. Bu ID'nin SANDBOX olmadığı durumda test gönderimi engellendi; otomatik test ID sabitleme yapılmadı. Genel DRY_RUN açık, gerçek kampanya/personel gönderimleri kapalı kaldı. Doğrulanmış test alıcısı henüz sağlanmadığından sunucu izin listesi boş bırakıldı.

### İlk sürümün önceki kontrol listesi

- 31 backend testi başarılı. Telefon normalizasyonu, mükerrer kontrolü, müşteri/personel ayrımı, CSV/XLSX önizleme ve aktarım, izin kanıtı, manuel İYS kontrolü, gönderim öncesi ret engeli, zamanlama/duraklatma/iptal, DRY_RUN kalıcılığı, webhook HMAC ve deduplikasyon, teslimat sıralaması, 24 saat penceresi, roller, silme ve Excel formül güvenliği doğrulandı.
- 10.000 müşteri satırı önizlendi ve aktarıldı. 200. sayfa dahil kalıcı kayıt ve sayfalama doğrulandı. Aktarım sonunda hiçbir kayıt otomatik gönderime uygun olmadı.
- Meta API kabulü ile teslimat ayrımı, 429 backoff, belirsiz ağ yanıtında tekrar göndermeme, eski bağlantı doğrulamasının reddi ve kesintili işlerin incelemeye alınması sahte dış servis yanıtlarıyla test edildi. Gerçek Meta gönderimi yapılmadı.
- `npm ci` ve `npm run build` başarılı; TypeScript doğrulaması geçti. npm denetimi sıfır bilinen açık bildirdi.
- Microsoft Edge headless UI testi: ilk yönetici oluşturma, 13 ekranın açılması, kayıt ekleme ve sayfa yenilemede kalıcılık, izin formu, şablon oluşturma, kampanya önizleme, kuyruk ve DRY_RUN sonucu başarılı. JavaScript konsol hatası yok.
- 1440 px masaüstü ve 390 px mobil ekran görüntüleri görsel kontrol edildi. Sonuçlar `test-results/` altında; yalnızca ayrı test veritabanının verilerini gösterir.
- Yerel Windows başlatma/durdurma PowerShell betikleri gerçekten çalıştırıldı. `http://localhost:3000/api/health` başarılı; panel DRY_RUN, SQLite ve ilk yönetici kurulumu bekleyen boş veritabanıyla açık bırakıldı.
- SQLite backup API ile yedekleme çalıştırıldı.

## Doğrulanamayanlar

Docker bu bilgisayarda bulunmadığından Compose servisleri, PostgreSQL/Redis/Celery konteynerleri ve PostgreSQL geri yükleme işlemi uçtan uca çalıştırılmadı. İlk migration ayrı UI test veritabanında çalıştırıldı; üretim PostgreSQL yük testi yapılmadı.

Meta kimlik bilgileri, hesabın Coexistence uygunluğu ve HTTPS webhook adresi sağlanmadı. Gerçek bağlantı, şablon onayı, mesaj gönderimi, teslimat ve maliyet doğrulanmadı. Üretimde bu kontroller yapılmadan başarı iddiasında bulunulmaz. Diğer kapsam sınırları README_TR.md içinde listelenmiştir.

Bir Starlette TestClient/httpx deprecation uyarısı var; test başarısını etkilemedi.
