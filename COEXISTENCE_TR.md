# Mevcut WhatsApp Business numarası ve Coexistence

Mevcut numaranız henüz Coexistence yöntemiyle bağlanmadığından bu proje numarayı kaydetmez, taşımaz, silmez veya WhatsApp Business uygulamasını kapatmaz. İlk bağlantı testleri için ayrı Meta API test numarası kullanın.

## Tamamlanması gerekenler

1. Yetkili Meta Business portfolio, uygun WABA ve WhatsApp Business Platform uygulaması.
2. Meta'nın mevcut hesabınız, ülkeniz, numaranız ve işletme uygulamanız için Coexistence uygunluğu. Uygunluk bu yazılım tarafından doğrulanamaz.
3. Meta'nın resmî Embedded Signup / WhatsApp Business App onboarding akışına erişim. Gerekirse ilgili çözüm sağlayıcısı üzerinden uygun akış; sıradan numara migration işlemi yerine Coexistence seçeneğinin açıkça sunulması gerekir.
4. Hesap sahibinin bu akışta gerekli izinleri vermesi ve bağlantıyı resmî ekranlarda tamamlaması. Bu sürüm Embedded Signup açmaz veya numara onboarding çağrısı yapmaz.
5. Bağlantı tamamlandıktan sonra doğru WABA ID, phone number ID, uygulama sırrı ve yetkili tokenın güvenli alınması.
6. HTTPS webhook aboneliği ve imza doğrulaması; test alıcısıyla gönderim ve teslimat/okundu webhook doğrulaması.
7. Numaranın WhatsApp Business uygulamasında çalışmaya devam ettiğinin işletme sahibi tarafından kontrol edilmesi.

API Ayarları ekranındaki bağlantı testi yalnızca Graph API erişimini ve WABA-numara ilişkisini kontrol eder. Coexistence durumunu veya mobil uygulamayla eşzamanlı çalışmayı kanıtlamaz. Üretim/test ortam etiketi `.env` içinden belirlenir; gerçek numara özelliği otomatik tahmin edilmez.

İşletme başlatmalı mesajlar onaylı şablon gerektirir. İç duyuru ücretsiz varsayılmaz. Güncel ücretler hesap ve kategori bazında Meta kaynaklarından doğrulanmadan gerçek maliyet gösterilmez.

## Resmî başlangıç kaynakları

- [Meta WhatsApp Cloud API koleksiyonu](https://www.postman.com/meta/whatsapp-business-platform/collection/wlk6lh4/whatsapp-cloud-api)
- [Meta WhatsApp Embedded Signup dokümantasyonu](https://developers.facebook.com/docs/whatsapp/embedded-signup/)
- [Meta Business App onboarding](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/whatsapp-business-app-onboarding)
- [Meta WhatsApp fiyatlandırma](https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing)
- [Meta webhook imza örneği](https://github.com/fbsamples/whatsapp-api-examples/tree/main/signature-validation-with-webhooks-payloads)

8 Ekim 2026 araştırmasında Meta'nın bazı doğrudan dokümantasyon sayfaları 429/erişim hatası verdi; hesap bazlı Coexistence koşulları ve fiyatlar doğrulanamadı. Bu nedenle destek/uygunluk veya sabit fiyat sözü verilmez. Kurulum günü resmî hesabınızdaki mevcut yönergeleri kontrol edin.
