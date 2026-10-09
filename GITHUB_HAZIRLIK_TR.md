# GitHub hazırlık denetimi

9 Ekim 2026 başlangıç durumunda mevcut Git deposunun dalı `master`, erişilebilir commit sayısı 0, takip edilen dosya sayısı 0 ve remote listesi boştu. Yeniden `git init` yapılması gerekmez. Mevcut `.git` ve uygulama verileri silinmez.

## Geçmişte bulunan kalıntılar

Yerel nesne taramasında 219 blob ve 131 tree incelendi. Erişilebilir commit geçmişi yoktu; fakat **erişilemeyen eski nesnelerde** iki token/sır eşleşmesi ve üç gerçek test alıcısı numarası kalıntısı bulundu. Sır veya telefon değerleri rapora yazılmadı. Bu eski nesneler temiz ilk commit'in ağacına dahil değildir; normal `git push origin main` yalnızca gerekli erişilebilir nesneleri taşır.

Bu bulgu nedeniyle daha önce ifşa edilmiş Meta Access Token yenilenmeli ve eskisi iptal edilmelidir. Daha önce ifşa edilmiş App Secret ve Verify Token için de koordineli yenileme planı [Railway/Vercel rehberinde](RAILWAY_VERCEL_KURULUM_TR.md) bulunur. Mevcut çalışan `.env` değerleri bu hazırlıkta değiştirilmez.

Eski nesneler kurtarma/snapshot verisi olabileceğinden otomatik `git gc --prune=now`, reflog silme veya `.git` silme uygulanmaz. Temiz commit sonrası yalnızca `main` dalını yeni bir dizine `git clone --no-local --single-branch --branch main <yerel-depo-yolu> <yeni-dizin>` ile klonlamak eski erişilemeyen nesneleri taşımayan ayrı bir çalışma kopyası sağlar. Eski klasör/snapshot'ların silinmesi ayrı onaylı veri saklama kararıdır. `.git` dizinini ZIP olarak paylaşmayın.

Eğer bir sır başka bir GitHub deposuna veya geçmiş commit'e daha önce push edilmişse, yerel temiz commit bunu geri almaz. İlgili anahtarı hemen iptal/yenilemek, ilgili remote geçmişini koordineli temizlemek ve gerekiyorsa hosting sağlayıcısında önbellek/fork temizliğini istemek gerekir. Verilen hedef deponun dal başlıkları yükleme öncesinde kontrol edildi; mevcut dal bulunmadı. Başka uzak depolardaki geçmiş doğrulanmış sayılmaz.

## Yüklemeye aday dosyalar

- `.gitignore` genel env, node_modules/Python cache, özel anahtarlar, DB/yedek/log/medya ve müşteri dosyalarını dışlar.
- Excel/CSV dosyaları varsayılan olarak dışlanır. İki incelenmiş boş aktarım şablonu ve yalnızca sahte numaralı `backend/tests/fixtures/recipients.xls` test dosyası izinlidir.
- `.env.example` gerçek token, numara/WABA kimliği, alıcı veya tünel adresi içermez. Güvenli örnekler ve kapalı gönderim varsayılanları kullanılır. Ayrı deployment örnekleri sır içermez.
- Güncel sırlar ve bilinen gerçek test alıcısı numarası aday dosyalarda aranır. Şüpheli değerler terminale veya rapora yazılmaz.
- README Railway/Vercel servis sırası, kesin komutlar, env dosyaları, webhook ve veri taşıma planını açıklar.

GitHub hedefi kullanıcı tarafından verilen `https://github.com/eegeren/hys-whatsapp-message-service.git` adresidir. İlk hazırlıkta push yapılmadı. Kullanıcının sonraki **"git e yükle"** isteğiyle temiz ilk commit ve normal `main` push'u için açık onay alındı; force push veya başka geçmişlerin silinmesi onaylanmadı.

## Son doğrulama

187 backend testi sahte Meta yanıtları ve geçici veritabanıyla geçti. Vercel frontend build'i başarılı; runtime bağımlılık denetiminde açık bulunmadı. İzinli iki Excel'in alıcı satırlarının boş olduğu ve XLS test fixture'ının yalnızca beklenen sentetik numaraları içerdiği kontrol edildi.

Yerel `main` dalı ve `origin` adresi hazırlandı; 100 güvenli kaynak/doküman dosyası staging alanına alındı. Git yazar bilgisi başlangıçta eksikti; onaylı yükleme sırasında mevcut GitHub oturumundan `eegeren` hesabı doğrulandı ve hesabın GitHub noreply adresi yalnızca yerel Git yapılandırmasına kaydedildi. Staging taramasında sır veya gerçek alıcı eşleşmesi bulunmadı. Uygulama sırları/veritabanı değiştirilmedi; gerçek WhatsApp mesajı gönderilmedi.
