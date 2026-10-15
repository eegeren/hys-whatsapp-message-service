# Video yükleme ve otomatik dönüştürme

## Hata incelemesi: kesin bulgular ve sınırları

15 Ekim 2026 tarihinde incelenen sürümde:

1. `backend/app/staff.py`, FFprobe çıktısındaki H.264/AAC dışı codec'leri **dönüştürmeden reddediyordu**. FFprobe nonzero exit, zaman aşımı, JSON/stream okuma hatası ve codec uyumsuzluğu aynı `except Exception` ile “MP4 okunamadı. Video H.264, varsa ses AAC olmalıdır.” mesajına çevriliyordu. Gerçek stderr/codecler kaydedilmiyordu.
2. FFprobe binary'sinin **hiç bulunmaması**, bu kodda ayrı HTTP 503 ve “sunucuda ffprobe kurulmalıdır” mesajına gider. Bildirilen HTTP 422 metni bu nedenle tek başına “FFprobe eksik” kanıtı **değildir**.
3. Kök `Dockerfile` ffmpeg paketini kurmasına rağmen Railway checklist'inin kullandığı `deploy/Dockerfile.railway` bu paketi kurmuyordu. Bu kesin bir dağıtım eksikliğidir; iki Dockerfile artık aynı kurulumu ve build sırasında `ffmpeg -version`, `ffprobe -version`, `libx264` encoder kontrolünü içerir.
4. Önceki tekli mesaj yolu codec doğrulaması/dönüştürmesi yapmadan MP4'ü Meta'ya iletebiliyordu; ortak video işleme hattı yoktu.

Hatalı orijinal video ve o isteğin canlı Railway stderr kaydı paylaşılmadığı için bu dosyaya özgü codec'i veya probe hatasını kesin tespit edilmiş gibi sunmak mümkün değildir. Üretimde çalışan image digest'ine/servisine bu oturumdan erişilmedi. Doğrulanan şey yukarıdaki kod/dağıtım hatalarıdır; gerçek video fixture'larıyla MPEG4+PCM/MOV, VP9/WebM, uyumlu MP4, bozuk dosya ve boyut aşımı senaryoları yeniden üretilmiştir.

## Kullanıcı akışı

Tekli mesaj ve Personel Duyuruları aynı `VideoProcessor` ekranını kullanır:

1. MP4/MOV/MKV/WebM/AVI/M4V/3GP/MPEG/MTS/M2TS/WMV/FLV seçilir. Varsayılan kaynak sınırı **256 MiB**; süre en fazla **30 dakika**, çözünürlük güvenli işleme sınırında en fazla 8K'dır.
2. Kaynak, tek kullanımlık ve 10 dakikalık izinle doğrudan Railway'e yüklenir. Vercel üzerinden büyük body taşınmaz. Yükleme yüzdesi gösterilir.
3. PostgreSQL'deki kalıcı iş kuyruğu FFprobe incelemesi → dönüşüm → çıktı doğrulamasını takip eder. İlerleme FFmpeg `out_time_us` verisinden alınır. İstemci yalnızca sahte bir zamanlayıcıyla yüzde üretmez; upload ve işlem aşamaları ayrıdır. İş bekliyorsa panel bunu açıkça belirtir.
4. Video H.264 + yuv420p, en fazla bir AAC ses kanalı (ses yoksa sessiz video) ve MP4 `faststart` halinde hazırlanır. Uyumlu ve faststart video byte-byte korunur. Yalnızca kapsayıcı/moov yerleşimi uygunsuzsa `-c copy` ile yeniden kodlamadan remux yapılır.
5. Gerekirse çözünürlük ve bitrate, süreye göre hesaplanan boyut bütçesiyle azaltılır. İlk kalite denemesi CRF 22; büyük kaynakta bitrate/VBV bütçesi, en fazla üç boyut denemesi kullanılır. Çıktı ayrıca codec, pixel format, süre, faststart ve gerçek byte boyutuyla doğrulanır. Video kesilerek limite sığdırılmaz. Kullanılabilir bitrate sağlanamıyorsa video kısaltılması istenir.
6. Kullanıcı **dönüştürülmüş MP4'ü** videolu önizlemede izler; kaynak ve çıktı boyutlarını görür. Personel ekranında “Önizlediğim videoyu duyuruya ekle” ile PDF'nin arkasına ekler. Tekli mesajda hazır video seçimi korunur.
7. Gönder onayı gelene kadar **Meta medya yüklemesi ve gerçek WhatsApp mesajı yapılmaz**. Dönüşüm işlemi DRY_RUN modunda da denenebilir; mesaj kilitleri aynen korunur.

Tekli mesaj API'si `video_job_id` ile hazır çıktıyı kullanır. Personel kayıtlarına da aynı hazır işin çıktısı kopyalanır; müşteri kampanyaları/PDF/görsel/webhook yolları değiştirilmez. Eski multipart tekli video yolu da aynı Python hazırlayıcıyı çağırır; büyük dosyalar ve önizleme için yeni iş akışı kullanılmalıdır.

## Meta sınırı

[Meta'nın resmi medya koleksiyonu](https://www.postman.com/meta/whatsapp-business-platform/folder/13382743-ecb27be5-4d27-4763-bbee-6a8002c04bf3) video için 16 MB, MP4/3GPP ve H.264/AAC koşullarını belirtir. Yeni hazırlayıcı **16.000.000 byte** konservatif sınırını kullanır; bu 16 MiB'nin de altındadır. Diğer medya sınırları değiştirilmedi. Kaynak sınırı WhatsApp sınırı değildir; yalnızca dönüştürülmüş çıktı Meta'ya gider.

## Railway dağıtımı

- API ve worker aynı commit ve `deploy/Dockerfile.railway` ile dağıtılmalı. Pre-deploy: `alembic upgrade head`; yeni revision `005`. Mevcut veriler silinmez. `video_jobs` eklenir, `staff_assets.video_job_id` nullable alanı eklenir.
- Mevcut `python -m app.production_worker` başlatma komutu korunur. Gönderim döngüsünden ayrı bir video thread'i bir seferde bir işi işler; FFmpeg ayrı subprocess'tir. Gönderim lease/heartbeat döngüsü dönüşüm beklemez. Aynı anda çalışan worker'lar PostgreSQL compare-and-set claim ile aynı işi iki kez işlemez.
- API ve worker için `VIDEO_PROCESSING_ENABLED=true`. Ayrıca `VIDEO_INPUT_LIMIT_MB=256`, `VIDEO_MAX_DURATION_SECONDS=1800`, `VIDEO_TIMEOUT_SECONDS=900`, `FFMPEG_PATH=ffmpeg`, `FFPROBE_PATH=ffprobe`. Bu değişkenler `.env.example` içinde yer alır.
- API'de `STAFF_UPLOAD_ORIGIN=https://GERCEK-BACKEND.up.railway.app` ve `PANEL_ORIGIN=https://GERCEK-PANEL.vercel.app` mevcut şekilde kalır. Preview imzalarında üretimde ortak `PANEL_PROXY_SECRET` kullanılır; bu sır tarayıcıya verilmez.
- Video dönüşümü RAM/CPU kullanır: 2 FFmpeg thread'i ve worker başına tek aktif dönüşüm; varsayılan 256 MiB kaynak için worker'a en az 1 GB RAM ayırın. Daha küçük planlarda kaynak limitini düşürün. Çok sayıda worker replika sayısı dönüşüm paralelliğini de artırır.
- Ayrı ölçekleme istenirse `VIDEO_PROCESSING_ENABLED=false` olan mesaj worker'ı yanında aynı DB'ye bağlı `VIDEO_PROCESSING_ENABLED=true python -m app.video_worker` servisi kullanılabilir. Kuyruk PostgreSQL'dir; video servisi Meta'ya bağlanmaz.
- `GET /api/video/tools` yönetici oturumunda çalışan API'nin FFmpeg/FFprobe versiyonlarını ve hazır olma durumunu verir. Worker araçlarının varlığı build kontrolü ve dönüşüm başlangıcında tekrar doğrulanır.

## Depolama ve erişim

Kalıcı işler, kaynak ve çıktı dosyaları PostgreSQL BYTEA alanlarında tutulur. Railway'in API/worker ephemeral diskleri arasında dosya paylaşımına ihtiyaç yoktur. Bounded, geçici medya için mevcut private PostgreSQL kullanılır; yüksek hacimde ayrı private object storage'a geçiş ayrıca planlanabilir.

Kaynak byte'lar dönüşüm başarı/hatası sonrası silinir. Hazır çıktı en fazla 24 saat saklanır; worker süre dolunca temizler. Duyuruya eklenen çıktı mevcut private personel medya saklama yolunu kullanır. DB yedeklerinin geçmiş byte'ları ayrıca kendi saklama politikasına tabidir. Worker kapalıyken temizlik yeniden başladığında yapılır; süresi dolmuş içeriğe erişim o anda da engellenir.

Geçici kaynak, çıktı ve FFmpeg stderr dosyaları OS private geçici dizinlerinde tutulur ve başarı/hata/zaman aşımında kapatılıp silinir. FFmpeg çalışması zaman ve kaynak boyutuyla sınırlıdır; ağ protokolleri ve playlist/concat demuxer'ları açılmaz. Yeniden başlayan worker'ın takılı kalan işleri açık `worker_interrupted` hatasıyla kapanır; otomatik mesaj gönderimi yoktur.

İş durumu ve hazır videoya erişim sahibi kullanıcı/yöneticiyle sınırlıdır. Personel alıcıları ve dosya ekleme yalnızca admin'e açıktır. Oynatıcı, 15 dakika geçerli imzalı salt okunur preview bağlantısı kullanır; HTTP Range/206 desteklenir, `private,no-store` uygulanır. İzin/önizleme URL'lerini reverse proxy loglarında kaydetmeyin. Uvicorn mevcut entry point'te access loglarını kapalı tutar.

## Teşhis

Kullanıcı işlem kimliğini ve Türkçe hatayı görür. Teknik logda aynı job ID, `ffprobe_missing`, `ffmpeg_missing`, `unreadable_input`, `probe_timeout`, `encode_failed`, `conversion_timeout`, `invalid_output` gibi ayrık kodlar ve sınırlandırılmış/redakte edilmiş FFprobe/FFmpeg stderr yer alır. Codec'ler, süre, çözünürlük, kaynak/çıktı boyutu işin `info` alanında bulunur. Meta tokenı/gizli değişkenler loglanmaz.

## Testler

```
cd backend
python -m pytest tests -q
```

Gerçek araç entegrasyon testleri için FFmpeg/FFprobe PATH üzerinde olmalı veya `FFMPEG_PATH` / `FFPROBE_PATH` verilmeli. `tests/test_video_processing.py` gerçek test videoları üretir. Pipeline testleri Meta'ya bağlanmaz. Kuyruk, izin, boyut, aralık preview, kaynak temizliği, mevcut tekli gönderim korumaları ve personel ekleme ayrıca test edilir. Docker testleri `--network none` ile de çalıştırılabilir.

Tarayıcı smoke testi `VIDEO_UI_SAMPLE=/tam/yol/hys-ui-sample.mov` verildiğinde gerçek MOV yükler, dönüşümü bekler, dönüştürülmüş video oynatıcısının metadata'sını doğrular ve duyuruya ekler. Test ortamında `python -m app.video_worker` çalışmalıdır. Meta çağrıları sandbox'ta yasaktır.

### Bu çalışma sırasında doğrulananlar

- macOS üzerinde gerçek FFmpeg/FFprobe fixture testleri ve mevcut uygulama regresyonları çalıştırıldı.
- Railway Dockerfile ile imaj üretildi; çalışan container içinde FFmpeg ve FFprobe **7.1.5** bulunduğu doğrulandı.
- Aynı imajda ağ tamamen kapatılarak **297 test geçti**.
- Ayrı internal Docker ağındaki geçici PostgreSQL 16 ile `004 → 005` migration, eski sentinel verisinin korunması, gerçek MOV dönüşümü, BYTEA kaynak temizliği, imzalı HTTP Range önizleme ve personel ekleme doğrulandı. Test container/veritabanı sonrasında kaldırıldı; canlı veritabanına dokunulmadı.
- Masaüstü/mobil tarayıcı smoke testinde MOV yüklendi, dönüşüm beklendi, hazır MP4 oynatıcısının metadata okuması kontrol edildi, önizlenen video duyuruya eklendi ve simülasyon akışı tamamlandı. TypeScript/Vite build ve 3 Vercel yapılandırma testi geçti.
- Gerçek WhatsApp mesajı/Meta medya yüklemesi/Meta şablon başvurusu yapılmadı. Railway/Vercel production dağıtımı bu çalışma sırasında yapılmadı.

## Video %1 kuyruğunda bekliyorsa

%1, kaynak yüklendi ve iş `queued` durumunda demektir; FFmpeg dönüşümü henüz başlamamıştır. Railway worker servisi API ile aynı committe olmalı; Start Command `python -m app.production_worker`, `VIDEO_PROCESSING_ENABLED=true` ve API ile aynı PostgreSQL `DATABASE_URL` gereklidir. Worker uyumamalı ve deployment başarılı olmalıdır. Redis bağlantısı başarısızsa production worker video thread'ini de başlatamaz; worker logları kontrol edilmelidir. Eski Celery/`app.worker` başlangıç komutu yeni video thread'ini başlatmaz; mevcut Railway komutu kullanılmalıdır.

Yeni durum kontrolü video worker'ının PostgreSQL üzerinden 5 saniyede bir verdiği heartbeat'i izler. 20 saniye içinde heartbeat yoksa panel sessizce “sırayla hazırlanıyor” demek yerine işleme hizmetinin bağlı görünmediğini belirtir. Heartbeat ayrı thread'de olduğundan uzun dönüşümler sırasında kesilmez. Canlı worker varsa sıra numarası ve aktif dönüşüm sayısı gösterilir; kuyruk erişim hatası ayrıca gösterilir. Bekleyen kaynak dosyaları süresi dolmadığı sürece korunur, worker güncellendiğinde yeniden yüklemek gerekmez. Heartbeat olmaması tek başına servisin var olmadığını kanıtlamaz; eski sürüm/yanlış DB/servis erişim sorunu olasılıklarını ayırmak için Railway logları gerekir.

## Şablon başvurusunda “Örnek yüklenemedi”

Bu durum `message_templates` oluşturma isteğinden önceki Resumable Upload aşamasının başarısız olduğunu gösterir; aynı istekte şablon oluşturma çağrısı yapılmamıştır. Önceki sürüm gerçek Meta hata kodunu/metnini kaybettiği için yalnız bu kayıttan token, izin, dosya veya bağlantı sebebi çıkarılamaz.

Yeni sürüm örnek yükleme ve şablon oluşturma aşamalarını ayrı bildirir; Meta kullanıcı hata metni, kod/alt kod ve trace ID gizli bilgiler redakte edilerek kaydedilir. Başvurular tablosunda “Hata ayrıntısı” ve yalnızca GET sorgusu yapan “Meta’da başvuruyu kontrol et” düğmeleri bulunur. Örnek yükleme başarısızlığı veya Meta'nın kesin reddi sonrası aynı adla yeniden açık onay verilerek deneme yapılabilir. Timeout/belirsiz şablon oluşturma yanıtı sonrasında otomatik veya aynı adla kör tekrar yapılmaz; mevcut başvuru Meta’dan sorgulanıp yerel kayıtla eşleştirilir. Genel şablon submit endpoint'i de bu korumayı atlayamaz.
