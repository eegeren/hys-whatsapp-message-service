# Hazır yerel panel akışı — 8 Ekim 2026

Verilen Phone Number ID ve WABA ID yerel ayarlara işlendi, META_TEST_MESSAGE_ENABLED=true yapıldı ve backend/worker yeniden başlatıldı. DRY_RUN=true ve LIVE_SEND_ENABLED=false korunuyor. Numara–WABA ilişkisi ile hello_world / en_US / APPROVED şablonu gerçek salt okunur Meta GET sorgularıyla doğrulandı. API account_mode=LIVE döndürüyor; bu tek başına üretim numarası olarak değerlendirilmez.

Panelde WhatsApp API Ayarları → Test Mesajı Gönder bölümünden tüm adımları tamamlayabilirsiniz:

1. Hazır gösterilen iki kimliği Meta Developers Step 1 geliştirme test ekranıyla karşılaştırın. İki kimlik onay kutusunu işaretleyip “Meta test kimliklerini onayla” düğmesine basın. Sistem bu beyanı sizin yerinize vermez.
2. Kendi telefon numaranızı E.164 biçiminde girin. “Bu kendi telefon numaramdır ve Meta test ekranında ekleyip doğruladım” kutusunu onaylayıp “Kendi numaramı test izin listesine kaydet” düğmesine basın. Yalnızca yerel .env içindeki META_TEST_RECIPIENTS değişir; tek numaralı izin listesi oluşturulur. Token ve diğer gizli değerler korunur. Yeni alıcı mevcut backend'de hemen geçerlidir; yeniden başlatma gerekmez. Bu işlem Meta'da alıcı ekleme/doğrulama yapmaz.
3. “Test Mesajı Gönder” düğmesine basıp açılan tek mesaj onay penceresini tamamlayın. Onaydan sonra gerçek hello_world / en_US isteği yapılır. API kabulü teslimat değildir; imzalı webhook gelene kadar teslimat bilinmiyor gösterilir.

Panelden alıcı kaydı yalnızca yerel .env dosyası bulunan kurulum içindir. Docker'da env_file konteynere dosyayı bağlamaz; dosya yoksa kayıt güvenli biçimde reddedilir. Bu projede çalışan yerel backend için telefon kaydı hazırdır.

77 backend testi, panel derlemesi ve izole tarayıcı testi geçti. Otomatik gönderim testleri sahte Graph API yanıtları kullandı. Gerçek mesaj gönderilmedi; bu işlem kullanıcı onayını bekler. İşletme hesabına veya Coexistence işlemine dokunulmadı.

---

# Güvenli Meta test mesajı

Panel: http://localhost:3000 → WhatsApp API Ayarları → Test Mesajı Gönder.

Kök `.env` dosyasında yalnızca Meta Developers → wp msg → Step 1. Try it out ekranındaki geliştirme test numarasının kimliklerini kullanın:

```dotenv
DRY_RUN=true
LIVE_SEND_ENABLED=false
META_ENVIRONMENT=test
META_TEST_MESSAGE_ENABLED=true
META_PHONE_NUMBER_ID=<Meta test ekranındaki Phone Number ID>
META_TEST_PHONE_NUMBER_ID=<aynı test Phone Number ID>
META_WABA_ID=<Meta test ekranındaki WABA ID>
META_TEST_WABA_ID=<aynı test WABA ID>
META_TEST_RECIPIENTS=<Meta ekranında eklenip doğrulanmış kendi E.164 numaranız>
META_PRODUCTION_PHONE_NUMBER_IDS=<bilinen üretim Phone Number ID değerleri, virgülle; yoksa boş>
```

Access Token, App Secret ve diğer gizli değerleri değiştirmeyin veya paylaşmayın. Mevcut gerçek işletme numarasını bu alanlara yazmayın. Üretim ID engel listesine alınmış numaralar test uç noktasını kullanamaz. Gerçek numaranın kayıt, taşıma, silme ve Coexistence işlemleri bu akışta yapılmaz.

1. Test alıcınızı Meta API Setup / Try it out ekranında ekleyip doğrulayın. Yerel izin listesi bu Meta doğrulamasını kendisi yapmaz; yalnızca yönetici tarafından yapılandırılmış izin listesidir. Birden çok E.164 alıcı virgülle ayrılır.
2. `.env` değişikliklerinden sonra backend ve worker'ı yeniden başlatın. Yerel kurulumda DURDUR_YEREL.bat ardından BASLAT_YEREL.bat; Docker kullanıyorsanız `docker compose up -d --force-recreate api worker beat`. Compose `env_file: .env` ile değerleri aktarır. DRY_RUN açık, LIVE_SEND_ENABLED kapalı kalmalıdır.
3. Panelde salt okunur kontrolü çalıştırın. Numara kimliği, WABA kimliği, WABA numara üyeliği ve hello_world / en_US / APPROVED şablonu Graph GET istekleriyle kontrol edilir. API hatası Türkçe açıklama ve mevcutsa hata koduyla gösterilir.
4. “Meta Test Numarasını Doğrula” alanına test ekranındaki iki kimliği elle girin. İki onay kutusuyla kimlikleri karşılaştırdığınızı ve numaranın Meta tarafından sağlanan geliştirme test numarası olduğunu açıkça onaylayın. Sunucu yeniden GET kontrolleri yapar; kimlikleri, yöneticiyi ve zamanı denetim kaydına yazar.
5. API account_mode=LIVE tek başına üretim kanıtı değildir. Bilinmeyen değer SANDBOX sayılmaz. API yalnızca kimlik ilişkisini ve şablonu doğrular; geliştirme test numarası niteliği yöneticinin Meta ekranını karşılaştırmasına dayanır. Yönetici yanlış beyanda bulunursa API bunu kesin olarak ayırt edemeyebilir; üretim numarası için bu onayı vermeyin.
6. İzin listesindeki kendi numaranızı E.164 olarak girip mesajı hazırlayın. Açılan pencerede alıcının Meta'da doğrulandığını ve tek gerçek mesaj gönderimini ayrıca onaylayın. Sadece hello_world / en_US gönderilir. Hiçbir kampanya/personel kuyruğuna eklenmez.

Yönetici kimlik onayı sadece belirli Phone Number ID ve WABA ID için geçerlidir. Token, API sürümü veya kimlikler değişince yeniden doğrulama gerekir. Mesaj onayı 5 dakika geçerlidir. Sunucu dakikada 1, günde 10 gerçek deneme ve işlem başına dakikada 5 istek sınırını korur. Tekrar onay aynı mesajı yeniden göndermez; zaman aşımında otomatik tekrar yoktur.

API kabulünden sonra WhatsApp mesaj kimliği ve güvenli yanıt gösterilir. İmzalı webhook gelene kadar teslimat bilinmiyor olarak kalır. Mesaj gönderimi için API POST sadece bu açık onaylı test uç noktasında yapılır.

Gerçek gönderim testleri ayrı veritabanı ve sahte Graph yanıtları kullanır; gerçek mesaj yalnızca panelde kullanıcı onayıyla gönderilir.
