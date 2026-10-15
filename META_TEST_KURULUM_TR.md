# Meta test numarası bağlantısı

Gerçek kimlik bilgilerini yalnızca proje kökündeki **.env** dosyasına yazın:

`C:\Users\YUSUFEGE.EREN\Documents\ChatGPT\hys-whatsapp-msg\.env`

`backend/.env` veya `frontend/.env` oluşturmayın. `.env.example` yalnızca boş örnek dosyadır; gerçek token koymayın. Kök `.env` Git tarafından dışlanır ve Docker image içine kopyalanmaz. Frontend'e `VITE_*` adıyla gizli değer aktarmayın.

## Doldurulacak alanlar

| Değişken | Girilecek bilgi |
|---|---|
| META_ACCESS_TOKEN | Meta uygulamanızın WhatsApp API Setup ekranından test erişim tokenı. Gizlidir; geçici token süresi dolduğunda yenileyin. |
| META_PHONE_NUMBER_ID | **Meta test numarasının Phone Number ID** değeri. Telefon numarasının kendisi değildir. |
| META_WABA_ID | Test numarasının bağlı olduğu WhatsApp Business Account ID. |
| META_APP_SECRET | Meta uygulamasının App Secret değeri. Webhook imza doğrulamasında kullanılır; salt okunur bağlantı testi için gerekli değildir. |
| META_VERIFY_TOKEN | Kendinizin oluşturacağı rastgele gizli webhook doğrulama değeri. Meta callback kurulumu sırasında aynı değer girilir. Bağlantı testi için gerekli değildir. |
| META_GRAPH_API_VERSION | Hesabınızda desteklenen Graph API sürümü; örnekte v25.0 bulunur. Meta panelinizde desteklendiğini doğrulayın. |

Aşağıdaki kilitler **korunmalıdır**:

```dotenv
DRY_RUN=true
LIVE_SEND_ENABLED=false
META_ENVIRONMENT=test
```

Mevcut WhatsApp Business üretim numaranızın ID değerini girmeyin. Test/üretim etiketi Meta'dan otomatik tespit edilmez; doğru test numarasını Meta panelinden seçmek gerekir. Uygulama numara taşıma, kayıt veya silme işlemi yapmaz.

## Yerel Windows sürümü

Yerel backend kök `.env` dosyasını okur. `BASLAT_YEREL.bat` veritabanını yerel SQLite dosyasına yönlendirir ve DRY_RUN/gerçek gönderim kilitlerini ayrıca uygular.

Dosyayı kaydettikten sonra `DURDUR_YEREL.bat`, ardından `BASLAT_YEREL.bat` çalıştırın. Mevcut hys hesabı ve veriler korunur.

## Docker Compose

`docker-compose.yml` içindeki `api` backend hizmeti ile `worker` ve `beat` hizmetlerinde:

```yaml
env_file: .env
```

Compose kökteki dosyayı okuyup değişkenleri container süreçlerinin ortamına aktarır; dosyanın container'a bind mount edilmesi gerekmez. Pydantic bu süreç ortamını kullanır. PostgreSQL parolası/DATABASE_URL zaten eşleştirilerek oluşturulmuştur; bunları Meta kurulumu için değiştirmeyin.

Yerel sürümü kapatın; Docker Desktop hazırken proje kökünde:

```powershell
docker compose up -d --build
```

Yalnızca `.env` değiştiğinde, mevcut kurulu Compose hizmetlerini yeniden oluşturun:

```powershell
docker compose up -d --force-recreate api worker beat
```

Sıradan container restart ortam değerlerini yeniden yüklemez. Ortam içeriklerini terminale döken `docker compose config`, `docker inspect`, `printenv` veya `Get-Content .env` çıktısını paylaşmayın. Bu bilgisayarda Docker kurulu olmadığından konteyner çalıştırma kontrolü yapılmamıştır.

## Panelden salt okunur kontrol

`http://localhost:3000` → **WhatsApp API Ayarları** → **Gerçek API bağlantısını test et**.

Yalnızca yönetici kullanabilir. Panel isteği yerelde POST olsa da Meta'ya yapılan işlemler yalnızca:

1. `GET /{PHONE_NUMBER_ID}?fields=id,display_phone_number,verified_name`
2. `GET /{WABA_ID}/phone_numbers?fields=id` (gerektiğinde cursor ile sayfalama)

Token yalnızca HTTPS Authorization başlığındadır; URL'ye eklenmez. Sayfalama yanıtındaki haricî URL izlenmez. Yönlendirmeler takip edilmez. Hatalar panelde Türkçe ve gizli değerleri içermeyen açıklamalarla gösterilir. Yanlış/eksik token, ID uyuşmazlığı ve başarısız kontrolde bağlantı doğrulanmış sayılmaz.

Bu düğme **mesaj göndermez**, şablon oluşturmaz, numara kaydetmez ve Coexistence yapmaz. Başarı yalnızca API erişimini ve numaranın WABA ilişkisini gösterir; mesaj teslimatını doğrulamaz. DRY_RUN kuyruğu simülasyonda kalır; müşteri ve personel gönderimleri kapalıdır.

Resmî Meta kaynakları ve Coexistence sınırları için README_TR.md ve COEXISTENCE_TR.md dosyalarına bakın.
