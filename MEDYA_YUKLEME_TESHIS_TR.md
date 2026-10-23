# Medya yükleme teşhisi

Güncel main ile birleştirme notu: uzak depoda video iş kuyruğu ve FFmpeg dönüşümü zaten mevcut. İlk inceleme eski yerel checkout üzerinde yapıldı; oradaki dönüşüm bulunmadığı tespiti güncel main için geçerli değildir.

Standart /api/* istekleri frontend/vercel.mjs içindeki Railway rewrite üzerinden geçer. VideoProcessor ise /api/video/jobs ile oturum üzerinden kısa ömürlü yükleme izni alır; video baytlarını dönen upload_url adresine PUT ile doğrudan Railway /api/video-upload/* endpoint’ine gönderir. Mevcut ticket, origin, oturum ve CORS kontrolleri korunur. Proxy sırrı tarayıcıya verilmez.

Multipart medya işlemlerine eklenen /api/media/inspect kontrolü Meta’ya bağlanmaz, dosya saklamaz veya dönüştürmez, mesaj göndermez. browser_bytes ve received_bytes karşılaştırılır. Bu endpoint’in conversion_applied=false değeri yalnızca inceleme isteği içindir; önceki video işinde dönüşüm uygulanmadığı anlamına gelmez. Ek inceleme isteği ağ kullanımını artırır. MP4 imza kontrolü codec doğrulaması değildir.

Video işlerinde source_size tarayıcıda beyan edilen boyuttur; upload_job akışı Railway’e ulaşan boyutu bununla karşılaştırır. İş tamamlandığında output_size ve info içindeki source_size/output_size, original/result codec bilgileri, converted/remuxed/compressed alanları dönüşümü açıklar. Bunlar video kuyruğunun mevcut alanlarıdır ve değiştirilmedi.

Boş dosya 422, boyut aşımı 413, içerik/tür uyumsuzluğu 422 olarak ayrılır. JSON olmayan HTTP 413 yanıtları da görünür. FUNCTION_PAYLOAD_TOO_LARGE görülürse Vercel Function sınırı belirtilir; diğer 413 yanıtlarında katman varsayılmaz. Meta medya yükleme hatası aşamayı, yüklenen bayt sayısını ve mesajın gönderilmediğini belirtir. Otomatik gönderim tekrarı eklenmedi.

9.670.000 baytlık yapay MP4 imza dosyası yerel testte eksiksiz alınır. Bu test gerçek codec veya kullanıcının dosyasını doğrulamaz. Canlı dağıtımın Network ve Railway logları incelenmedi; gerçek hatanın kesin nedeni henüz kanıtlanmadı. Gerçek mesaj gönderilmedi.
