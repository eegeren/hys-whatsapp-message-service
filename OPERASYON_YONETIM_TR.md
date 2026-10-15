# HYS Connect — Operasyon ve yönetim modülleri

## Mimari ve kapsam

Mevcut Vercel React/Vite frontend, Railway FastAPI, PostgreSQL, Redis worker ve aynı WhatsApp işletme hattı kullanılır. Eski kullanıcılar ve mevcut `stores` tablosu korunur. Yeni ana menü yoktur: yönetim ekranı **Ayarlar → Operasyon yönetimi** içindedir. Giriş ekranı, ana menü, mesaj yazma kutusu ve Meta gönderim fonksiyonları yeniden yazılmadı. Var olan yerel değişiklikler korundu; çalışma dalı `feature/operations-management`.

Konuşma kimliği mevcut normalize telefonun SHA-256 özetiyle aynıdır. Mesajlar taşınmaz. Müşteri profili mevcut müşteri rehberinden ad ve mağazayı okur; profil düzenlemesi operasyon katmanında bir geçersiz kılma kaydı tutar, rehber kaydını veya mesaj geçmişini değiştirmez. Aynı telefonun mevcut tek sohbeti için sohbet sayısı 1; mesaj sayısı tüm kayıtlı mesajların sayısıdır.

## Eklenenler

- Sohbet üstünde durum ve sorumlu personel; üzerime alma, devir ve atamayı kaldırma.
- Yeni / İşlemde / Müşteri Bekleniyor / Çözüldü durumları. Eski sohbetler açıkça **Belirlenmedi** kalır.
- Telefon üzerinden sağ müşteri paneli: isim, mağaza, etiketler, mesaj sayısı, son iletişim, sorumlu, dahili notlar, atama/durum geçmişi.
- Dahili notlar ayrı `internal_notes` tablosunda; WhatsApp mesajı veya Meta isteği oluşturmaz. Not silme, geçmişi koruyan mantıksal silmedir.
- Arama ve okunmamış filtresi korunarak atama, durum, mağaza ve personel filtreleri birlikte uygulanır.
- Yöneticiye gerçek performans raporları, mevcut mağaza tablosuna mağaza ekleme ve personel erişim ayarı, işlem geçmişi, otomatik yeniden açma kuralı.
- Durum/atama/profil güncellemelerinde sürüm kontrolü. Eşzamanlı değişiklik 409 döndürür; kullanıcı güncel kaydı yükleyerek yeniden dener.

## Erişim davranışı

- Yönetici mevcut genel erişimini korur.
- **Önceden oluşturulmuş ve kapsam tanımlanmamış personel hesaplarının erişimi değişmez.** Yeni hesap da mevcut hesap oluşturma davranışına uyar. Yönetici mağaza sınırını ayrıca kaydetmelidir; ilk kullanımda her personelin kapsamını inceleyin.
- Kapsam kaydedildiğinde yalnızca seçilen mağazalar ve ayrıca izin verilmişse mağazası atanmamış müşteriler görüntülenir. Genel erişim tekrar açılabilir.
- Mağaza bağlantısı önce operasyon profilinden; henüz düzenlenmemişse mevcut `Contact.store` değerinin `Store.name` ile **tam eşleşmesinden** alınır. Tanınmayan/boş mağaza atanmamıştır. Eski mağaza adlarını otomatik tahmin ederek dönüştürmeyin.
- Mağaza sınırı sohbet listesi/detayı, mesaj listesi, müşteri listesi, medya indirme, okunma, uygunluk, yeni sohbet ve gönderim uçlarında backend tarafından uygulanır. Yetkisi kaldırılan sohbet açık ekrandan sonraki yenilemede kaldırılır.
- Aynı mağazadaki başka personele atanmış sohbet görülebilir; yazma, atama, profil ve not yönetimi yalnızca sorumlu veya yöneticiye aittir. Atanmamış havuzdaki personel yalnızca kendisini atayabilir; sorumlu kişi veya yönetici devir yapabilir. Mağaza dışındaki personele atama reddedilir.
- Dahili notları yalnızca yönetebilen personel görür. Notu yazarı veya yönetici silebilir; sohbet devri eski notun yeni sorumlu tarafından silinmesine izin vermez.
- **Açıkça mağaza sınırı tanımlanan** personelin eski, mağazalar arası genel kampanya, toplu müşteri Excel önizleme/içe aktarım ve genel rapor API'leri kapatılır. Bu eski araçlar mağaza kapsamlı veri ayırmadığı için genel veriyi açığa çıkarmaz. Kapsamsız mevcut hesapların akışı değişmez. Personel duyurularının mevcut ayrı yetkilendirmesi korunur.
- Pasife alınan hesabın geçmiş atamaları otomatik başka birine aktarılmaz. Yönetici kalan sohbetleri devretmelidir.

## Veritabanı / migration

Yeni dosya: `backend/alembic/versions/008_operations.py`, önceki sürüm `007`.

- `conversation_ops`: isteğe bağlı sorumlu/durum/mağaza, profil, sürüm.
- `internal_notes`: içerik, yazar, zaman, mantıksal silme.
- `operation_events`: aktör, olay, sohbet kimliği, mağaza, zaman, eski/yeni değerler.
- `operator_scopes`: mevcut kullanıcıya mağaza kapsamı. Yeni kullanıcı veya mağaza tablosu oluşturulmaz.
- `messages.sender_user_id`, `messages.operation_store_id`: NULL destekleyen yeni alanlar; eski mesajlarda NULL kalır. Doğrudan gönderimde oturumdaki gerçek gönderen ve o andaki mağaza kaydedilir; mesaj içeriği/Meta payload'ı değişmez. Toplu kampanyalar personel yanıtı olarak sayılmaz.
- Eski mesaj, müşteri ve kullanıcı kayıtları yerinde kalır. Eski sohbetlere durum veya personel ataması yapılmaz. Yeni gelen mesaj gözlemcisi eski sohbeti tespit ederse durumunu yine boş tutar; gerçekten yeni konuşma `Yeni` olur. İlk kayıt eklemesi SQLite/PostgreSQL `ON CONFLICT DO NOTHING` ile eşzamanlı webhook isteklerine dayanıklıdır.
- Otomatik yeniden açma varsayılan **kapalıdır**. Açıldığında yeni gelen mesaj çözülen sohbeti `Yeni` yapar; sorumlu korunur. Aynı webhook tekrarında ek olay/mesaj oluşmaz. Webhook imza doğrulaması ve teslimat işleyicisi değiştirilmedi; ek metadata SQLAlchemy gözlemcisiyle kaydedilir.
- Eski migration dosyaları değiştirilmedi. 008 otomatik yıkıcı downgrade yapmaz; geri alma için uygulamayı önceki sürüme döndürüp ek tabloları saklayın veya doğrulanmış yedeği ayrı kurtarma prosedürüyle kullanın.

## Rapor tanımları

Tarih aralığı Türkiye saatine (`Europe/Istanbul`) göre, başlangıç dahil/bitiş gününün sonuna kadar hesaplanır; veritabanındaki UTC zamanları kullanılır. Son 7/30 gün bugünü içerir. Özel aralık en fazla 366 gün farkıyla kabul edilir.

- **Mesaj:** aralıkta gerçek göndericisi kaydedilmiş, durumu accepted/sent/delivered/read olan doğrudan gönderim. Başarısız, belirsiz, sıradaki ve dry-run kayıtları dahil değildir. API kabulü teslimat garantisi sayılmaz.
- **Yanıtlanan sohbet:** aynı dönemde bekleyen müşteri mesajına ölçülebilen yanıt verilen farklı telefonlar. Birden çok yanıt aynı sohbeti çoğaltmaz.
- **İlk yanıt:** telefonun kayıtlı geçmişindeki ilk kabul edilmiş yanıtta, bekleyen ilk müşteri mesajından geçen süre; birden çok sohbet için ortalama. İlk yanıtı geçmiş dönemde olan sohbetin sonraki yanıtı yeni bir ilk yanıt sayılmaz.
- **Ortalama yanıt:** bekleyen müşteri mesajları grubunun son mesajından sonraki kabul edilmiş yanıta sürelerin ortalaması. Başka personele atama öncesi bekleme de gerçek süreye dahildir. Bir yanıt sonrası yeni müşteri mesajı beklenir; ardışık temsilci mesajları süreyi tekrar ölçmez.
- Gönderici bilinmeyen kabul edilmiş eski yanıt bekleme grubunu kapatır, ancak herhangi bir personele puanlanmaz. İlk/ortalama yanıt ölçülemiyorsa **Veri yok** gösterilir. Eski gönderimler toplamı ayrı bilgilendirilir; geriye dönük personel tahmini yapılmaz.
- **Çözülen:** seçilen dönemde durumu gerçekten Çözüldü yapan aktörün olay sayısı. Yeniden açılıp tekrar çözülen görüşmenin yeni çözüm işlemi ayrıca sayılır. Gönderim tek başına çözüm sayılmaz.
- **Atama:** dönemde o personele yapılmış gerçek atama/devir olayları; aynı kişiye değişikliksiz kayıt ek puan değildir.
- **Açık:** seçilen dönemden bağımsız **güncel** sorumluluk ve açık durum anlık görüntüsü. Eski Belirlenmedi durumları tahmin edilmez.
- Mağaza filtresinde gönderim/olay için olay anında kaydedilmiş mağaza; açık sohbet ve mağaza istatistiklerinde güncel mağaza kullanılır. Personel filtresi mağaza tablosunda güncel sorumluya uygulanır. Mağaza istatistiği yalnızca takip kaydı oluşturulmuş sohbetleri kapsar; tüm eski sohbetler otomatik takip kaydına çevrilmez.

Raporlar geçmiş mesajları sıralı okuyarak hesaplanır; sahte örnek rakam veya arka plan puanlama yoktur. Büyük geçmişlerde rapor sorgusu ek süre alabilir; gelen kutusunun mevcut 10.000 son mesaj okuma sınırı bu çalışmada yeniden yazılmadı.

## Yeni API uçları

| Yöntem | Yol | Yetki |
|---|---|---|
| GET | `/api/operations/options` | Oturum, izinli mağazalar |
| GET / PATCH | `/api/operations/conversations/{key}` | Mağaza / yönetim yetkisi; PATCH `version` zorunlu |
| POST | `/api/operations/conversations/{key}/notes` | Sohbet yönetimi |
| DELETE | `/api/operations/notes/{id}` | Sohbet yönetimi ve yazar/yönetici |
| GET | `/api/operations/reports` | Yönetici; period/start/end/person_id/store_id |
| GET | `/api/operations/access` | Yönetici |
| PUT | `/api/operations/access/{user_id}` | Yönetici |
| GET / PUT | `/api/operations/config` | Yönetici |
| GET | `/api/operations/audit?page=1` | Yönetici, 50 kayıt/sayfa |

Mevcut `/api/stores` uçları yeniden kullanılır. Mevcut mesajlaşma uçlarına kontrollü kapsam/yönetim bağımlılıkları eklenmiştir. Meta tokenları, şifreler ve not/mesaj gövdeleri operasyon denetim kaydına kopyalanmaz; müşteri adı/etiket güncellemesinde yalnızca değişen alan adları kaydedilir. Ayrıntılı not kendi yetkili tablosunda bulunur. Eski sistemin mevcut audit tablosu ayrıca korunur.

## Dosyalar

Bu modüle ait yeni dosyalar:

- `backend/app/operations.py`
- `backend/app/operations_access.py`
- `backend/alembic/versions/008_operations.py`
- `backend/tests/test_operations.py`
- `frontend/src/ConversationOperations.tsx`
- `frontend/src/OperationsManagement.tsx`
- `frontend/tests/operations-ui-smoke.mjs`
- `OPERASYON_YONETIM_TR.md`

Kontrollü entegrasyon değişiklikleri:

- `backend/app/core.py` — ek modeller ve NULL gönderici alanları.
- `backend/app/main.py` — router kaydı, kapsamlı hesapların genel uçlardan izolasyonu, kapsamlı dashboard sayımları.
- `backend/app/messaging.py`, `backend/app/incoming_media.py` — erişim bağımlılıkları ve liste metadata'sı; Meta gönderme gövdeleri değişmedi.
- `backend/app/contacts.py` — müşteri ve mağaza listeleme/ekleme kapsam kontrolü.
- `frontend/src/Workspace.tsx` — küçük sohbet kontrolleri, birleşik filtre, müşteri paneli bağlantısı.
- `frontend/src/SettingsWorkspace.tsx`, `frontend/src/whatsapp.css` — yönetici sekmesi ve ek stiller.
- `backend/tests/test_deployment.py`, `backend/tests/test_staff.py` — beklenen Alembic head 008.
- `frontend/tests/settings-ui-smoke.mjs` — ek yönetim sekmesi beklentisi.

İşe başlamadan var olan hesap/parola değişiklikleri bu modülün parçası sayılmaz; korunmuştur. `.local-preview` altındaki test verisi/yama ve derlenen `backend/web` Git tarafından dışlanır.

## Doğrulama

Frontend TypeScript/Vite build başarılı. Yedi Playwright grubu (operasyon, messenger, settings, quick replies, bildirimler, ekip hesapları, personel duyuruları) ve üç Vercel route testi geçti. Backend tam regresyonu: **361 test geçti**; bunların **17 tanesi yeni operasyon testidir**. Starlette/httpx test istemcisinden gelen tek deprecation uyarısı vardır; test hatası yoktur. Testlerde yalnızca mock Meta ve geçici veritabanları kullanıldı.

- Mevcut backend ve yeni operasyon regresyonları, Meta mock ve geçici SQLite veritabanıyla.
- 007 → 008 geçişinde mevcut kullanıcı, müşteri, mağaza ve mesajın korunması; yeni mesaj alanlarının NULL kalması; geçmişe operasyon ataması yapılmaması.
- PostgreSQL için 007:008 offline migration SQL üretimi ve yıkıcı tablo silme olmadığının doğrulanması. **Gerçek PostgreSQL migration çalıştırılmadı:** yerel Docker daemon erişilebilir değil. Production veritabanına bağlanılmadı.
- Masaüstü/mobil Playwright: atama, durum, müşteri, not, birleşik filtre, rapor, mağaza erişimi, audit, yeniden açma; mevcut messenger, settings, quick replies, inbox notifications, staff accounts, staff duyuru akışları.
- Frontend TypeScript/Vite build, Vercel route testleri, `git diff --check`: başarılı.
- Yerel panel `http://127.0.0.1:3011/` üzerinde 008 migration ile güncel; mevcut yerel test kayıtları korundu. `DRY_RUN=true`, canlı gönderim kapalı, deployment gönderim kilidi etkin.
- Canlı WhatsApp gönderimi ve production deploy yapılmadı.

## Üretime almadan önce

1. PostgreSQL yedeğini alın; önce aynı sürümde staging kopyasıyla 007 → 008 geçişini ve uygulama açılışını doğrulayın. Bu ortamda gerçek PostgreSQL smoke testi eksik kaldı.
2. Railway API servisinin mevcut pre-deploy komutu `alembic upgrade head` olarak kalsın. Migration backend çalışma dizininde uygulanmalıdır. Startup kontrolü head 008 bekler; uygulamayı migration tamamlanmadan başlatmayın.
3. Aynı committen Railway backend/worker güncellemesini migration ile yayınlayın; ardından Vercel frontend'i yayınlayın. Yeni ortam değişkeni veya Redis kuyruğu gerekmez. Mevcut gönderim kilitlerini bu işlem sırasında açmayın.
4. Yöneticiyle Ayarlar → Operasyon yönetimi → Mağaza erişimleri bölümünde mevcut mağazaları inceleyin, gerekiyorsa ekleyin. Eski rehberdeki mağaza adlarını tam eşleşme açısından kontrol edin.
5. Her destek personelinin mağaza kapsamını ve atanmamış havuz erişimini açıkça kaydedin. Yeni hesabın da varsayılan genel erişime sahip olduğunu unutmayın; kapsamı belirledikten sonra personele hesabını teslim edin.
6. İki farklı mağaza personeliyle staging'de karşılıklı liste/detay/medya/gönderim 403/404 kontrolü yapın; atamaları ve pasif personelde kalan sohbetleri inceleyin.
7. İstenirse otomatik yeniden açmayı ayrı kuraldan etkinleştirin; varsayılan kapalıdır. Gerçek gönderim ancak panelde operatörün mevcut Gönder onayıyla yapılır.
8. Önceki uygulamaya dönmek gerektiğinde ek verileri silmeyin. Otomatik downgrade yoktur; doğrulanmış yedek/kurtarma prosedürünü kullanın.
