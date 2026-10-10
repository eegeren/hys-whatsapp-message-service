import re
import httpx
from datetime import datetime,timezone
from email.utils import parsedate_to_datetime
from fastapi import HTTPException
from app.core import settings

RATE_CODES=(4,80007,130429,131056)
NO_RETRY_CODES=(131026,131049,130472,131048)
def delivery_error_message(code):
    return {131026:'Meta mesajı teslim edemedi; alıcı hesabı veya cihazı kaynaklı olabilir. Kesin alt neden bildirilmedi. Otomatik tekrar yapılmaz.',
            131049:'Meta sağlıklı mesajlaşma etkileşimi kuralları nedeniyle teslimatı engelledi. Otomatik tekrar yapılmaz.',
            130472:'Alıcı Meta deney grubunda; pazarlama mesajı bu alıcıya gönderilemedi. Otomatik tekrar yapılmaz.',
            131048:'Meta spam/kalite sınırı uyguladı. Kampanya duraklatılır; hesap kalitesini kontrol edin.',
            131056:'Aynı alıcı için Meta hız sınırına ulaşıldı. Beklenerek yeniden denenecek.',
            130429:'Meta gönderim hız sınırına ulaşıldı. Kuyruk bekleyerek yeniden deneyecek.'}.get(code,'Meta teslimat hatası.')

def retry_after_seconds(value):
    try:return max(0,min(86400,int(value)))
    except (ValueError,TypeError):
        try:return max(0,min(86400,int((parsedate_to_datetime(value)-datetime.now(timezone.utc)).total_seconds())))
        except (ValueError,TypeError,OverflowError):return 0

def graph(method,path,payload=None,params=None,files=None,content=None):
    if settings.deployment_send_lock and method.upper()=='POST' and path.rstrip('/').endswith('/messages'):
        raise HTTPException(403,'Dağıtım gönderim kilidi açık; gerçek mesaj gönderimi kapalı.')
    if not all([settings.meta_access_token,settings.meta_phone_number_id,settings.meta_waba_id]):
        raise HTTPException(503,'Meta bağlantısı eksik. Proje kökündeki .env dosyasında META_ACCESS_TOKEN, META_PHONE_NUMBER_ID ve META_WABA_ID alanlarını doldurup backend hizmetini yeniden başlatın.')
    if not all(re.fullmatch(r'[0-9]+',value) for value in (settings.meta_phone_number_id,settings.meta_waba_id)):
        raise HTTPException(422,'Meta telefon numarası ID ve WABA ID yalnızca rakamlardan oluşmalıdır; telefon numarasını değil Meta ID değerlerini girin.')
    if not re.fullmatch(r'v\d+\.\d+',settings.meta_graph_api_version): raise HTTPException(422,'Geçersiz Graph sürümü')
    try:
        with httpx.Client(timeout=60 if files or content is not None else 20,follow_redirects=False,trust_env=False) as client:
            request_body={'content':content} if content is not None else {'data':payload,'files':files} if files else {'json':payload}
            headers={'Authorization':('OAuth ' if content is not None else 'Bearer ')+settings.meta_access_token}
            if content is not None:headers.update({'file_offset':'0','Content-Type':'application/octet-stream'})
            response=client.request(method,f'https://graph.facebook.com/{settings.meta_graph_api_version}/{path}',headers=headers,params=params,**request_body)
        result=response.json()
    except httpx.TimeoutException: raise HTTPException(502,'Meta bağlantısı zaman aşımına uğradı. İnternet erişimini kontrol edip tekrar deneyin.')
    except (httpx.HTTPError,ValueError): raise HTTPException(502,'Meta yanıtı doğrulanamadı. İnternet erişimini ve Graph API sürümünü kontrol edin.')
    if response.is_error:
        error=result.get('error',{});code=error.get('code','?')
        messages={190:'Meta erişim tokenı geçersiz veya süresi dolmuş. .env dosyasındaki META_ACCESS_TOKEN değerini yenileyin.',100:'Meta ID veya istenen alan geçersiz ya da erişim izni yok. Test numarasının ID ve WABA ID değerlerini kontrol edin.',10:'Meta uygulamasının bu işlem için yetkisi yok. Token izinlerini kontrol edin.',200:'Meta hesabına erişim izni yok. WABA ve token yetkilerini kontrol edin.'}
        message=messages.get(code,'Meta isteği reddetti. Hesap erişimini ve API ayarlarını kontrol edin.')
        if code==131030:message='Meta bu alıcıyı test numarasının doğrulanmış alıcı listesinde bulamadı. Meta API Setup ekranında alıcıyı ekleyip doğrulayın.'
        if code==131026:message='Meta bu numaraya mesajı teslim edemedi. Numaranın WhatsApp kullanabildiğini ve alıcının hesabının etkin olduğunu kontrol edin.'
        if code==131047:message='24 saatlik müşteri hizmeti penceresi kapanmış. Meta onaylı bir şablon seçin.'
        if code==131049:message='Meta bu mesajı alıcıya teslim etmedi. Alıcı durumu ve Meta mesajlaşma kurallarını kontrol edin; otomatik yeniden deneme yapılmadı.'
        template_errors={132000:'Şablon değişken sayısı Meta tanımıyla eşleşmiyor. Şablonları yenileyip tüm alanları doldurun.',132001:'Bu ad ve dilde onaylı Meta şablonu bulunamadı. Şablonları yenileyin.',132007:'Meta şablonun biçimini reddetti. Şablon durumunu kontrol edin.',132012:'Başlık, medya veya değişken türü Meta şablonuyla eşleşmiyor.',132015:'Meta bu şablonu duraklattı; etkin onaylı şablon seçin.',132016:'Meta bu şablonu devre dışı bıraktı; farklı onaylı şablon seçin.',131052:'Meta medya bağlantısından dosyayı indiremedi. Dosyanın herkese açık ve uygun biçimde olduğunu kontrol edin.',131053:'Meta medya dosyasını kabul etmedi. Dosya türünü, boyutunu ve video kodlamasını kontrol edin.'}
        if code in template_errors:message=template_errors[code]
        if response.status_code==429 or code in RATE_CODES:message='Meta istek sınırına ulaşıldı. Bir süre bekleyip tekrar deneyin.'
        if code in NO_RETRY_CODES or code in (130429,131056):message=delivery_error_message(code)
        raise HTTPException(502,{'message':message,'code':code,'retryable':code not in NO_RETRY_CODES and (response.status_code==429 or code in RATE_CODES),'ambiguous':response.status_code>=500,'retry_after':retry_after_seconds(response.headers.get('Retry-After'))})
    return result

def upload_media(filename,content,content_type):
    result=graph('POST',f'{settings.meta_phone_number_id}/media',{'messaging_product':'whatsapp'},files={'file':(filename,content,content_type)})
    media_id=result.get('id')
    if not isinstance(media_id,str) or not re.fullmatch(r'\d+',media_id):raise HTTPException(502,'Meta medya yükleme kimliğini doğrulayamadı; mesaj gönderilmedi.')
    return media_id


def upload_template_sample(asset):
    """Resumable file handle for template approval, distinct from a sending media ID."""
    from app.template_components import validate_upload
    validate_upload('IMAGE',asset)
    session=graph('POST','app/uploads',params={'file_name':asset.filename,'file_length':len(asset.content),'file_type':asset.content_type})
    upload_id=session.get('id','')
    if not isinstance(upload_id,str) or not re.fullmatch(r'upload:[A-Za-z0-9_:=+-]+(?:\?sig=[A-Za-z0-9_.=-]+)?',upload_id):raise HTTPException(502,'Meta örnek görsel yükleme oturumu doğrulanamadı.')
    result=graph('POST',upload_id,content=asset.content)
    handle=result.get('h')
    if not isinstance(handle,str) or not re.fullmatch(r'[0-9]:[A-Za-z0-9_:=+./-]{1,2000}',handle):raise HTTPException(502,'Meta örnek görsel yükleme tanıtıcısını doğrulayamadı.')
    return handle
