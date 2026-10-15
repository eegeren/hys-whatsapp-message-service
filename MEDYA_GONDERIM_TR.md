# Görsel ve video gönderimi

Yeni Mesaj → Yeni sohbet başlat veya kapalı müşteri hizmeti penceresindeki sohbet: Meta onaylı Marketing şablonunda IMAGE / VIDEO başlığı bulunmalıdır. Şablonu seçip JPG/PNG/MP4 dosyası ekleyin, normal metin kutularına değişkenleri yazın ve önizlemeyi kontrol edin. Şablonun sabit metni değiştirilemez. Belge ve metin şablonlarının mevcut tekli gönderimleri de korunur.

Yeni Mesaj → Mevcut sohbeti yanıtla veya açık hizmet penceresindeki sohbet düzenleyicisi: Son 24 saatte müşteriden gerçek gelen mesaj kaydı varsa “Görsel veya video ekle” alanı kullanılabilir. Açıklama isteğe bağlıdır, en fazla 1024 karakterdir. Şablonsuz görsel/video kapalı pencerede backend tarafından engellenir.

Toplu Mesaj: İzinli Excel/CSV listesini yükleyin, APPROVED / MARKETING durumundaki IMAGE veya VIDEO başlıklı şablonu seçin, dosyayı ekleyip değişkenleri doldurun. Alıcıları ve medyayı kontrol ettikten sonra Gönder’e basın. Dosya bir kez Meta’ya yüklenip bütün izinli alıcılara aynı medya header kimliğiyle gönderilir. İsteğe bağlı örnek alıcı gönderiminden sonra toplu aşamada yeniden yükleme ve örnek alıcıya ikinci mesaj yapılmaz.

JPG/PNG sınırı 5 MB, MP4 sınırı 16 MB’dır. MIME türü, dosya imzası, boş dosya ve boyut backend’de kontrol edilir. MP4 için H.264 video ve varsa AAC ses gerekir; codec uygunluğu ve işleme hatalarının nihai kontrolünü Meta yapar. Dosya seçimi veya önizleme gerçek yükleme/gönderim değildir. DRY_RUN modunda Meta’ya medya yüklenmez. Access Token ve App Secret arayüze taşınmaz.

Meta medya/gönderim hataları Türkçe ve mevcut hata koduyla gösterilir. API kabulü teslim edildi anlamına gelmez; teslimat ve okundu durumlarını gerçek webhook bildirir. Testlerde yalnızca geçici veritabanları ve sahte API cevapları kullanılır.
