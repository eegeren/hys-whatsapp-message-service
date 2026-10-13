# Personel Duyuruları

Personel Seç → PDF Yükle → Videoları Ekle → Önizle → Gönder.

Bu bölüm yalnızca `admin` kullanıcılarına açıktır. Mevcut müşteri kampanyası, tekli mesaj, webhook ve Redis/Railway worker yolları korunur. Yeni kuyruk `staff_announcements`, `staff_assets`, `staff_deliveries` tablolarını kullanır; müşteri kampanyalarına veya sohbet geçmişine personel gönderimi eklemez. Personel rehberi mevcut `contacts.kind=staff` kayıtlarıyla uyumludur.

## Kullanım

- Excel'de yalnızca `Telefon` sütunu zorunludur. `Ad Soyad` ve `Mağaza` isteğe bağlıdır; varsa personel seçiminde ad/telefon/mağaza araması ve mağaza filtresi kullanılabilir. Eksik veya boş ad/mağaza mevcut personel bilgilerini silmez. XLSX, XLS ve CSV desteklenir; en fazla 10.000 satır / 5 MB. Telefonlar Türk cep numarasına normalize edilir, aynı telefon dosyada bir kez alınır, mevcut personel güncellenir. Hatalı satırlar numaralarıyla bildirilir; mevcut ret kayıtları korunur. Müşteri kayıtları değiştirilmez.
- Tüm personel, mağazalar veya tek tek kişiler seçilebilir. Devre dışı/ret kaydı bulunan kişiler dışlanır; ret listesi gönderim öncesinde yeniden kontrol edilir.
- Bir PDF (100 MB sınır), ardından en fazla 10 MP4 (dosya başına 16 MB). Dosya imzaları kontrol edilir; MP4 için `ffprobe` H.264 video ve varsa AAC ses doğrular. Docker imajına ffmpeg eklendi.
- Önizleme gerçek hedef listesini, sıralı dosyaları, şablon metinlerini, toplam alıcı/dosya/mesaj sayısını, ücretli mesaj tahminini ve üst sınırını gösterir. Önizleme 10 dakika geçerlidir; dosya veya alıcı/şablon değişirse yeniden hazırlanır.
- Tek Gönder işlemi her personel/dosya çifti için tek bir kalıcı kayıt oluşturur. Aynı duyurunun tekrar onaylanması yeni mesaj üretmez. Yeni bir duyuru hazırlamak ayrı bir gönderim sayılır.
- PDF → video 1 → video 2 sırası korunur. Bir alıcı için önceki dosyada `delivered` veya `read` webhook gelmeden sonraki dosya gönderilmez. `sent` ve API kabulü teslimat sayılmaz. Webhook gelmezse sıradaki dosya bekler; panelden duraklatılabilir veya iptal edilebilir. WhatsApp istemcisinin görüntüleme sırası garanti edilemez.
- Durum ekranı 50 personellik sayfalara bölünür; büyük listeler tek yanıtta taşınmaz.
- Her dosyada 24 saatlik pencere yeniden kontrol edilir. Açık pencerede `document` / `video`; kapalı pencerede o dosyanın türüne uygun ayrı başlıklı şablon gönderilir. Bir şablona birden çok medya konmaz.
- Dosya ilk kullanımında Meta Media API'ye yüklenir. Media ID PostgreSQL'e kaydedilir; aynı duyuru içindeki sonraki personeller aynı ID'yi kullanır. Dosya başına kilit eşzamanlı yüklemeleri seri hale getirir.
- Duraklatma ve iptal bekleyen kayıtları etkiler; Meta'ya giden veya devam eden HTTP isteği geri alınamaz. API belirsizliği/işleyici kesintisi `uncertain` olarak gösterilir ve otomatik tekrar edilmez. Önceki dosya başarısızsa sonraki dosyalar gönderilmez. Bu tercih çift gönderimi önler; belirsiz sonucu operatörün Meta/webhook kayıtlarından incelemesi gerekir.

## Meta'da onaylanacak iki şablon

İki ayrı Türkçe şablon oluşturun. Bu sürüm, değişken/buton içermeyen standart tek medya başlıklı şablonları destekler. Seçim adla sabitlenmez; panelde senkronize edilmiş uygun onaylı şablon seçilir.

| Ad | Dil | Başlık | Önerilen sabit gövde |
| --- | --- | --- | --- |
| `hys_personel_duyuru_belge` | `tr` | DOCUMENT | HYS çalışma süreçleriyle ilgili personel duyuru belgesi ektedir. Lütfen belgeyi inceleyiniz. |
| `hys_personel_duyuru_video` | `tr` | VIDEO | HYS çalışma süreçleriyle ilgili personel bilgilendirme videosu ektedir. Lütfen videoyu izleyiniz. |

Başvuruya örnek PDF ve örnek MP4 ekleyin. Meta şablon başvurusundaki örnek medya `header_handle`, gönderimde kullanılan Media API `id` değerinden farklıdır. Bu çalışma gerçek şablon başvurusu yapmaz ve gerçek dosyaları Meta'ya yüklemez. WhatsApp Manager üzerinden başvuru yapıldıktan ve APPROVED durumuna geldikten sonra panel Ayarlar → Meta şablonlarını yenile işlemini kullanın.

Kategori, duyurunun gerçek içeriğine göre Meta tarafından belirlenir. Operasyonel içerik için UTILITY başvurusu değerlendirilebilir; genel duyuruların UTILITY olarak kabul edileceği garanti edilmez. Meta'nın onayladığı kategoriye ait ülke/hesap tarifesini kullanın; kategori sistem tarafından değiştirilmez.

Meta'nın medya başlıklı şablon yapısı: [HeaderObject](https://whatsapp.github.io/WhatsApp-Nodejs-SDK/api-reference/types/HeaderObject/). Medya sınırları: [Meta'nın resmi Postman koleksiyonu](https://www.postman.com/meta/whatsapp-business-platform/folder/13382743-ecb27be5-4d27-4763-bbee-6a8002c04bf3).

## Railway / Vercel kurulumu

1. Backend ve worker'a aynı kod sürümünü dağıtın. Var olan pre-deploy adımında `alembic upgrade head` çalıştırın; yeni revision `004`. Migration mevcut tabloları silmez/değiştirmez. Canlı veritabanında bu çalışma sırasında migration çalıştırılmadı.
2. `STAFF_UPLOAD_ORIGIN=https://GERCEK-BACKEND.up.railway.app` backend API ortamına eklenmelidir. `PANEL_ORIGIN` mevcut Vercel panel origin'i olmalıdır. Dosyalar panelden 10 dakikalık tek kullanımlık izin alınarak doğrudan Railway'e PUT ile yüklenir. Bu yol proxy sırrı veya Meta tokenı tarayıcıya göndermez. Büyük dosyalar için Vercel istek boyutu sınırlarına bağımlı kalınmaz: [Vercel sınırları](https://vercel.com/docs/functions/limitations).
3. `DRY_RUN=true`, `LIVE_SEND_ENABLED=false`, `STAFF_DISPATCH_ENABLED=false` ile başlayın. Bu ayarlarda Gönder yalnızca simülasyon üretir; dosya yüklemesi dahil Meta çağrısı yapılmaz. Simülasyon kayıtları ayarlar değiştiğinde canlı kuyruğa dönüşmez.
4. Gerçek gönderime hazır olduğunuzda mevcut bağlantı doğrulamasını, imzalı webhook aboneliğini ve worker'ı doğrulayın. `DRY_RUN=false`, `LIVE_SEND_ENABLED=true`, `STAFF_DISPATCH_ENABLED=true`, `DEPLOYMENT_SEND_LOCK=false` gerekir. Personel worker'ı müşteri toplu gönderim anahtarından bağımsızdır; mevcut küresel saniyelik/günlük gönderim sınırını paylaşır.
5. Canlı modda önizleme altında **Bu alıcı listesine gerçek WhatsApp gönderimini onaylıyorum** kutusu ayrıca seçilmelidir. Sunucu bu onayı da zorunlu tutar. Bu geliştirme sırasında canlı ayarlar açılmadı ve gerçek mesaj gönderilmedi.

## Ücret tahmini

`STAFF_DOCUMENT_UNIT_PRICE` ve `STAFF_VIDEO_UNIT_PRICE`, seçilecek şablon kategorileri için mesaj başına ücretlerdir; `STAFF_PRICE_CURRENCY=USD` (veya kendi tarife para birimi). Bunlar tanımlı değilse panel tutar uydurmaz ve “Birim ücret tanımlı değil” gösterir. Tahmin, o andaki kapalı pencere sayısı × dosya sayısıdır. Pencere kuyrukta kapanabileceği için tüm alıcılar × dosyalar üst sınırı da gösterilir. Teslim edilmeyen mesajlar, tarife kademeleri ve özel ücretsiz giriş pencereleri nihai faturayı değiştirebilir.

Hizmet penceresi/ücret açıklaması ve güncel hesabın tarifesi için [Meta fiyatlandırması](https://business.whatsapp.com/products/platform-pricing) kontrol edilmelidir. Ücret tahmini fatura garantisi değildir; birim fiyatları güncel Meta tarifenizden girin.

## Dosya güvenliği ve saklama

Dosyalar herkese açık dizin veya URL'de sunulmaz. Geçici içerik PostgreSQL'de tutulur; API yalnızca yöneticiye dosya adı ve boyut metadata'sı verir. Yükleme izni hash ile saklanır, tek kullanımdır ve üretimde panel Origin'i doğrulanır. Excel ve dosya içeriği loglanmaz; `uvicorn` mevcut entry point'i access loglarını kapatır. Reverse proxy'de yükleme izinlerini içeren URL'leri loglamayın.

Yerel PDF/video içeriği Meta yüklemesi başarıyla tamamlanınca veya duyuru iptal edilince temizlenir. Worker ayrıca 24 saat dolmuş içerikleri ve süresi geçmiş yükleme izinlerini temizler. Worker durursa temizlik yeniden başladığında tamamlanır; süresi dolmuş içerikle gönderim engellenir. Byte temizliği PostgreSQL yedeklerini geçmişe dönük silmez; mevcut yedek erişim ve saklama politikanızı uygulayın. Meta'daki yüklenmiş medyanın saklanması Meta kurallarına tabidir. MP4 doğrulama geçici dizini her başarı/hata yolunda kaldırılır.

## Testler

Backend: `cd backend && python -m pytest tests -q`.
Frontend: `cd frontend && npm ci && npm run build && node --test tests/vercel-config.test.mjs`.

Personel testleri `backend/tests/test_staff.py` altında gerçek Meta çağrılarını yasaklayıp sahtelerini kullanır: medya ID paylaşımı, açık/kapalı pencere payload'ları, PDF/video sırası ve webhook bekleme, erken/tekrarlı webhook, belirsiz yanıt, çift onay, duraklatma/iptal, Excel hataları/ret kayıtları, yetki, dosya boyutu/codec, tek kullanımlık yükleme, üretim Origin kontrolü, additive migration ve simülasyonun canlıya dönüşmemesi.

İsteğe bağlı tarayıcı testi: yeni geçici `hys-ui-staff-*` dizinindeki SQLite URL ile `HYS_STAFF_UI_SANDBOX=1 DRY_RUN=true LIVE_SEND_ENABLED=false` ayarlayın; `alembic upgrade head` ardından `uvicorn tests.staff_ui_server:app --port 3011 --no-access-log`. `frontend/tests/staff-ui-smoke.mjs` dosyasını Playwright kurulu Node ile çalıştırın. Bu sandbox bütün gerçek Meta çağrılarını yasaklar. `PLAYWRIGHT_MODULE_PATH`, `CHROME_EXECUTABLE`, `STAFF_UI_URL` isteğe bağlıdır.

Doğrulama sonucu: 269 backend testi, 3 Vercel yapılandırma testi ve TypeScript/Vite build başarılı. Tarayıcı smoke testi masaüstü/mobil giriş, bölüm, doğrudan PDF yükleme, önizleme, tek gönderim, duraklatma ve iptal akışlarını geçti; tarayıcı hatası yok. Testler izole SQLite veritabanları ve sahte Meta yanıtlarıyla çalıştırıldı; canlı PostgreSQL/Railway/Vercel dağıtımı bu çalışma sırasında yapılmadı.
