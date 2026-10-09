# Toplu gönderim incelemesi — 9 Ekim 2026

Kampanya 8 salt okunur veritabanı incelemesi:

| Son durum | Alıcı sayısı |
|---|---:|
| Okundu | 124 |
| Teslim edildi (henüz okundu bildirimi yok) | 116 |
| Gönderildi (henüz teslim bildirimi yok) | 15 |
| Başarısız | 29 |
| Durduruldu / iptal edildi | 194 |
| Bekliyor / yeniden deneme / gönderim sürüyor | 0 |

Toplam 478 kayıt bulunuyor. Sayılar son servis doğrulamasındaki anlık görüntüdür; yeni webhook bildirimleriyle ilerleyebilir. Son durumlar birbirini dışlar; webhook olaylarının ham sayısı alıcı sayısı değildir. 235 bekleyen bilgisi güncel kayıtlarla uyuşmuyor. Kampanya önce duraklatılmış, sonra devam ettirilmiş ve en son durdurulmuş (`cancelled`). İnceleme kampanyayı yeniden açmaz veya iptal edilen mesajları tekrar kuyruğa almaz.

## Son durumunda başarısız olan kayıtlar

| Meta kodu | Sayı | Panel açıklaması |
|---|---:|---|
| 131049 | 12 | Meta sağlıklı mesajlaşma etkileşimi kuralları nedeniyle teslimatı engelledi. |
| 131026 | 11 | Teslim edilemedi. Alıcı hesabı/cihazı kaynaklı olabilir; kesin alt neden bu koddan belirlenemez. |
| 130472 | 6 | Alıcı Meta deney grubunda; pazarlama mesajı gönderilemedi. |

Webhook geçmişinde 131026 kodu 14 benzersiz mesaj için var; bunların 3'ünün son durumu artık başarısız değil. Son teslimat/okunma kanıtı önceliklidir. Geçmiş hata olayları silinmez. Bu kampanyada 130429, 131056 veya HTTP hız sınırı hatası kanıtı bulunmadı. Güvenli log özetlerinde işleyici istisnası görülmedi.

## Kuyruk davranışı

- Mevcut veritabanı üzerinden işleyiciler arasında paylaşılan saniyede en fazla bir istek sınırı ve günlük sınır korunur. 100 kayıt seçmek 100 paralel API isteği demek değildir.
- Kesin reddedilmiş geçici hız sınırları (4, 80007, 130429, 131056 veya uygun HTTP 429) için artan bekleme ve küçük rastgele sapma uygulanır; varsa Meta Retry-After süresi önceliklidir. En fazla 5 girişim yapılır. Bekleme gönderici genelinde paylaşılır.
- 131026, 131049 ve 130472 otomatik tekrar edilmez. 131048 kalite/spam kısıtında kampanya duraklatılır ve mesaj otomatik tekrar edilmez.
- Kabul edilmiş, gönderilmiş, teslim edilmiş, okunmuş, başarısız veya sonucu belirsiz kayıtlar işleyici tarafından tekrar gönderilmez. Yanıtı belirsiz zaman aşımı otomatik tekrar edilmez.
- Duraklatılmış veya durdurulmuş kampanyalar çalıştırılmaz. İlk 100 kaydın duraklatılmış olması diğer aktif kampanyaların önünü kesmez.
- API kabulü teslimat sayılmaz; gönderildi/teslim/okundu webhook kanıtıyla güncellenir. Geç gelen sent bildirimi başarısızlığı silmez; delivered/read kanıtı son durumu ilerletebilir.
- Panelde her alıcının son durumu, hata açıklaması ve planlanan yeniden deneme zamanı sayfalı listede gösterilir. Hatalı alıcılar mevcut Excel dışa aktarımından indirilebilir.

Gerçek mesaj gönderimi yapılmadan geçici test veritabanı ve sahte API yanıtlarıyla doğrulama yapılır. Gerçek sırlar, alıcı listesi, mevcut gönderim bayrakları veya veritabanı kayıtları değiştirilmez. Meta'nın resmî hata sayfası inceleme sırasında HTTP 429 verdi; hesap özelindeki güncel Meta kapasitesinin artırıldığı veya doğrulandığı iddia edilmez.
