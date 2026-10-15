# HYS Connect — Hazır Yanıtlar / Hızlı Mesajlar

## Kullanım

Mesaj yazma alanındaki **Hazır Yanıtlar** düğmesi, kategorili ve aranabilir yanıt listesini açar. Seçim, mesaj kutusunu doldurur; metin düzenlenebilir. Hazır yanıttan oluşturulan taslak yalnızca **Gönder** düğmesiyle gönderilir. Seçim veya Enter tuşu otomatik gönderim yapmaz. Diğer elle yazılan mesajların mevcut Enter davranışı korunur.

Tek değişken `{{personel_adi}}` değeridir. Sunucu bunu oturumdaki kullanıcının hesap açılırken kaydedilen `display_name` alanındaki ilk adıyla değiştirir. Örneğin hesap adı Emre Erbilen ise değişken Emre olur; ayrıca profil düzenlemek gerekmez. Ad **Ayarlar → Profilim → Görünen adınız** bölümünden değiştirilir. Eski kullanıcıların ilk görünen adı mevcut kullanıcı adıdır; profil kaydedildiğinde sonraki seçimler yeni adı kullanır.

Bunlar yerel hazır yanıtlardır; Meta onaylı Marketing/Utility şablonları değildir. 24 saatlik hizmet penceresi kapalı olduğunda listede açıklama görünür, hazır yanıt seçimleri kapatılır. Mevcut backend gönderim kontrolü de kapalı pencerede şablonsuz gönderimi reddeder. Yanıt seçimi canlı gönderim kilitlerini değiştirmez.

## Yönetim ve erişim

**Ayarlar → Hazır Yanıtlar / Hızlı Mesajlar** bölümü yalnızca yöneticide görünür. Yönetici başlık, kategori, metin, kategori sırası ve yanıt sırasını düzenleyebilir; yeni yanıt ekleyebilir, silebilir ve oklarla sıralayabilir. Kategori sırası aynı kategorideki tüm yanıtlar için birlikte güncellenir.

Erişim alanı **Tüm ekip** veya belirli bir personeldir. Normal seçim API'si yalnızca ortak ve oturumdaki personele ait yanıtları döndürür. Yönetim API'si tüm kayıtları yalnızca yöneticilere açar. Operatörler profil adlarını değiştirebilir; yanıt yönetimi yapamaz. Ad, profil ve yanıt değişiklikleri denetim kaydına yazılır; yanıt metinleri denetim kaydına kopyalanmaz.

## Railway / PostgreSQL / Vercel

Migration **006** mevcut `users` tablosuna `display_name` ekler ve ayrı `quick_replies` tablosunu oluşturur. Altı başlangıç yanıtını yalnızca migration sırasında ekler. Sunucu yeniden başladığında silinen yanıtlar yeniden oluşturulmaz, düzenlemeler sıfırlanmaz. Mevcut müşteri, mesaj, medya, personel duyurusu veya Meta şablonu tabloları silinmez.

Mevcut Railway pre-deploy adımı backend dizininde `alembic upgrade head` çalıştırmalıdır. API ve worker yeni kodla başlamadan önce migration uygulanmalıdır; üretim başlangıç denetimi güncel migration'ı zaten kontrol eder. Vercel'in `/api/*` yönlendirmesi GET/POST/PUT/PATCH/DELETE isteklerini mevcut Railway servisine taşır. Yeni gizli anahtar, ortam değişkeni veya harici servis gerekmez.

API:
- GET `/api/quick-replies`: oturumdaki personelin kullanabileceği kayıtlar, isim uygulanmış `rendered_body` dahil.
- GET `/api/quick-replies?manage=true` ve `/api/quick-replies/users`: yalnızca yönetici.
- POST `/api/quick-replies`, PUT/DELETE `/api/quick-replies/{id}`, POST `/api/quick-replies/reorder`: yalnızca yönetici.
- PATCH `/api/profile`: yalnızca oturumdaki kullanıcının görünen adı.

Gerçek gönderim mevcut `/api/conversations/send` akışını kullanır; `template_id=null` ile normal metin gönderilir. Yanıt seçimi ayrı bir WhatsApp gönderim endpoint'i çağırmaz.

## Testler

API testleri değişken doğrulamasını, profil ve yeniden oturum açma kalıcılığını, kişisel kayıt gizliliğini, yönetici yetkilerini, kategori/sıralama/silme işlemlerini ve kapalı pencere engelini kapsar. Migration testi 005 sürümündeki kullanıcı/verileri koruyarak 006'ya yükseltir; yeniden başlatma/yükseltmede düzenlenen veya silinen yanıtların geri gelmediğini doğrular.

`frontend/tests/quick-replies-ui-smoke.mjs`, izole `tests.staff_ui_server` üzerinde profil, yönetim, kişiselleştirme, arama, düzenleme, mobil görünüm, kapalı pencere ve manuel gönderimi kontrol eder. Gönderim isteği tarayıcıda sahte yanıtla karşılanır; sandbox'ta gerçek gönderim kilitlidir. Gerçek WhatsApp mesajı gönderilmez.

## Destek personeli hesapları

Yöneticiler Ayarlar → Destek Personeli Hesapları bölümünden görünen ad, kullanıcı adı ve ilk parola ile `operator` hesabı oluşturabilir. Hesap listesi GET `/api/users` üzerinden yalnızca yöneticilere döner; parola/hash döndürülmez. Parola mevcut Argon2 altyapısıyla saklanır. Destek kullanıcıları hesap yönetimine ve gizli ayarlara erişemez.

Meta bağlantı doğrulaması mevcut ortak sunucu kaydını kullanır; personele ayrı Meta tokenı verilmez. Üst çubuktaki Meta bağlantısı düğmesi mevcut, operatörlere de açık POST `/api/settings/test` kontrolünü çalıştırır. Bu işlem yalnızca Meta GET istekleriyle erişim ve WABA ilişkisini kontrol eder; mesaj göndermez. Bir kullanıcının başarılı kontrolü tüm oturumlarda geçerlidir. Mevcut bir saatlik doğrulama süresi ve gönderim kilitleri korunur; sürekli doğrulanmış gösterilmez.

## Gelen kutusu ve bildirimler

Konuşma görünür, odakta ve son mesajlara kaydırılmış olduğunda yüklenen son gelen mesaj kimliğine kadar kayıtlar okundu işaretlenir. POST `/api/conversations/{key}/read` sınır kimliğini doğrular; istek sırasında gelen daha yeni mesajlar okunmamış kalır. Bu durum mevcut ekip ortak gelen kutusunu kullanır; Meta'ya okundu mesajı gönderilmez. GET ile konuşma çekmek tek başına okunma durumunu değiştirmez.

Gelen kutusu diğer bölümlerdeyken de yeni mesajları beş saniyelik aralıklarla kontrol eder. İlk yükleme sessizdir; yalnızca yeni gelen mesaj kimliği ilerlediğinde kısa ve düşük sesli Web Audio bildirimi çalar. Giden mesajlar ve teslimat güncellemeleri ses üretmez. Tarayıcının ses politikası gereği ilk kullanıcı tıklaması/klavye etkileşiminden sonra etkinleşir. Üst çubuktaki ses düğmesi tercihi bu tarayıcıda saklar.

Başarı bildirimi beş, hata bildirimi on iki saniyede kapanır. Kullanıcı okurken üzerine gelme/odak süresince sayaç durur; bildirim kartı veya kapatma düğmesi tıklanınca kapanır.

## Düzenli ayarlar ve personel hesabı işlemleri

Ayarlar altı bölüme ayrılır: Profilim, Ekip hesapları, Hazır yanıtlar, Meta bağlantısı, Meta şablonları, Gelişmiş. Destek personeline yalnızca yetkili olduğu profil/bağlantı/Meta şablonu bölümleri gösterilir. Webhook ve geliştirici araçları Gelişmiş bölümündedir. Sekmeler arasında düzenlenmekte olan form taslakları korunur; bu taslaklar sayfa yenilendiğinde kaydedilmiş sayılmaz.

Yönetici Ekip hesaplarında destek personelinin adını ve kullanıcı adını düzenleyebilir, yeni parola belirleyebilir veya hesabı silebilir. Bu bölümden yönetici hesapları değiştirilemez. Parola sıfırlama mevcut oturumların tamamını geçersiz kılar; eski parola artık çalışmaz. Parola veya hash yanıtlara ve denetim kaydına yazılmaz.

Migration **007**, `users.active` alanını ekler ve mevcut hesapları aktif bırakır. Silme, hesabı pasif yapar ve oturumlarını siler; kişi artık giriş yapamaz ve hesap listesinden çıkar. Eski mesajlar, denetim kayıtları ve kişisel hazır yanıtların sahiplik bağlantıları korunur. Silinen kullanıcı adı geçmiş kayıtları korumak için tekrar kullanılamaz. DELETE `/api/users/{id}`, PUT `/api/users/{id}`, POST `/api/users/{id}/password` yalnızca yöneticilere açıktır. Üretimde API ve worker yeni sürümle başlamadan önce mevcut pre-deploy `alembic upgrade head` adımı 007'ye ulaşmalıdır.
