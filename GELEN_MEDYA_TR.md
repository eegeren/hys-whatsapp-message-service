# HYS Connect: gelen mesaj içerikleri

Sorunun nedeni: webhook alıcısı yalnızca metin, buton ve durum alanlarını saklıyordu. Gelen audio/image/video/document/sticker alanları atıldığı için mesaj gövdesi `[audio]` vb. yer tutucularla kaydediliyordu. Önceki sohbet ekranı da yalnızca gövdeyi çiziyordu.

Düzeltme:
- İmzalı ve hesap kimliği doğrulanmış webhook'tan medya kimliği, MIME, açıklama ve dosya adı mevcut WebhookItem tablosuna kaydedilir. Ek migration veya veri sıfırlama gerekmez.
- Sohbet detayı medya türünü döndürür. Ses ve video oynatılır; fotoğraf/çıkartma görüntülenir; belgeler açılır/indirilir. Konum, kişi kartı, seçim yanıtı ve tepkiler de çizilir.
- GET /api/messages/{message_id}/media oturum gerektirir. Yalnızca gelen mesajın kayıtlı dosyasına erişir. Her açılışta Meta'dan güncel dosya adresi alınır; erişim tokenı ve Meta adresi tarayıcıya verilmez.
- HTTPS Meta medya alanları izin listesiyle sınırlıdır; yönlendirme izlenmez. Tür/boyut sınırları uygulanır. Geçici dosya en fazla 1 MiB bellekte, devamı işletim sisteminin geçici dosyasında tutulur; yanıt bitince kapatılır. Ses/video için byte-range desteklenir. Yanıtlar private/no-store'dur.
- Dosyalar bu değişiklikle kalıcı arşivlenmez. Meta'da silinmiş veya süresi dolmuş dosyalar için yeniden gönderim gerekir.

Eski kayıtlar: önceki sürümün atmış olduğu dosya kimlikleri geri getirilemez. Ekran bu durumu Türkçe açıklar; `[audio]` artık oynatılabilir dosyaymış gibi gösterilmez. Dağıtımdan sonra gelen yeni mesajlar için kimlik tutulur.

Doğrulama: sahte Meta yanıtlarıyla webhook saklama, yetkilendirme, güvenli indirme, aralık istekleri, tehlikeli dosya/adres reddi ve eksik eski kayıt testleri; izole tarayıcıda gerçek örnek OGG oynatma ve medya arayüzü kontrolleri. Testlerde WhatsApp mesajı gönderilmez.
