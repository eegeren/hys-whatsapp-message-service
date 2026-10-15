"""Build send-time components from approved template definitions, never from client JSON."""
import ipaddress
import json
import re
from dataclasses import dataclass
from urllib.parse import urlsplit
from fastapi import HTTPException

PLACEHOLDER=re.compile(r'{{\s*([A-Za-z_][A-Za-z_0-9]*|\d+)\s*}}')
MEDIA_TYPES={'IMAGE':('image',5*1024*1024,{'image/jpeg','image/png'}),
             'VIDEO':('video',16*1024*1024,{'video/mp4','video/3gpp'}),
             'DOCUMENT':('document',100*1024*1024,{'application/pdf'})}

@dataclass
class MediaUpload:
    filename:str
    content_type:str
    content:bytes

def definitions(template):
    try:items=json.loads(template.components)
    except (ValueError,TypeError):raise HTTPException(422,'Meta şablon bileşenleri okunamadı. Şablonları yenileyin.')
    if not isinstance(items,list) or any(not isinstance(item,dict) for item in items):raise HTTPException(422,'Geçersiz Meta şablon bileşenleri.')
    types=[str(item.get('type','')).upper() for item in items]
    if any(t not in ('HEADER','BODY','FOOTER','BUTTONS','CAROUSEL') for t in types) or len(types)!=len(set(types)):
        raise HTTPException(422,'Bu şablon özel veya tekrarlanan bileşenler içeriyor; standart başlık, metin, alt metin ve buton şablonu seçin.')
    return {str(item['type']).upper():item for item in items}

def variable_keys(text):
    keys=list(dict.fromkeys(PLACEHOLDER.findall(text)))
    if keys and all(key.isdigit() for key in keys):
        keys=sorted({str(int(key)) for key in keys},key=int)
        if keys!=[str(i) for i in range(1,len(keys)+1)]:raise HTTPException(422,'Şablon değişken sırası desteklenmiyor; Meta şablonunu kontrol edin.')
    elif any(key.isdigit() for key in keys):raise HTTPException(422,'Şablonda sayısal ve adlandırılmış değişkenler birlikte kullanılamaz.')
    return keys

def fill(text,values):
    return PLACEHOLDER.sub(lambda m:values[str(int(m[1])) if m[1].isdigit() else m[1]],text)

def text_parameters(text,values,legacy=None):
    keys=variable_keys(text)
    if values is not None:
        if legacy:raise HTTPException(422,'Şablon değişkenlerini tek bir biçimde gönderin.')
        if set(values)!=set(keys):raise HTTPException(422,'Seçilen şablonun tüm değişkenlerini doldurun.')
    else:
        legacy=legacy or []
        if len(legacy)!=len(keys):raise HTTPException(422,'Şablon değişkenlerinin tümünü doldurun.')
        values=dict(zip(keys,legacy))
    if any(not value.strip() or len(value)>4096 for value in values.values()):raise HTTPException(422,'Şablon değişkenleri boş olamaz ve en fazla 4096 karakter olabilir.')
    params=[{'type':'text','text':values[key],**({'parameter_name':key} if not key.isdigit() else {})} for key in keys]
    return params,fill(text,values)

def public_media_link(value):
    try:
        parsed=urlsplit(value.strip())
        host=parsed.hostname
        if parsed.scheme!='https' or not host or parsed.username or parsed.password or parsed.port not in (None,443):raise ValueError()
        if host.casefold()=='localhost' or host.casefold().endswith(('.localhost','.local','.internal')):raise ValueError()
        try:address=ipaddress.ip_address(host)
        except ValueError:address=None
        if address is not None and not address.is_global:raise ValueError()
    except ValueError:raise HTTPException(422,'Medya için kimlik bilgisi içermeyen, dışarıdan erişilebilir bir HTTPS bağlantısı girin.')
    return value.strip()

def validate_upload(kind,upload):
    _,limit,mimes=MEDIA_TYPES[kind]
    if upload.content_type not in mimes:raise HTTPException(422,'Şablon başlığı için dosya türü uygun değil. Görsel: JPEG/PNG; video: MP4/3GP; belge: PDF.')
    if not upload.content or len(upload.content)>limit:raise HTTPException(422,f'Dosya boş veya {limit//(1024*1024)} MB boyut sınırını aşıyor.')
    signatures={'image/jpeg':upload.content.startswith(b'\xff\xd8'),
                'image/png':upload.content.startswith(b'\x89PNG\r\n\x1a\n'),
                'application/pdf':upload.content.startswith(b'%PDF-'),
                'video/mp4':upload.content[4:8]==b'ftyp','video/3gpp':upload.content[4:8]==b'ftyp'}
    if not signatures.get(upload.content_type):raise HTTPException(422,'Dosya içeriği belirtilen medya türüyle eşleşmiyor.')

def build_template(template,data,upload=None,card_uploads=None):
    items=definitions(template);components=[];preview=[];media_kind=None
    header=items.get('HEADER')
    if header:
        kind=str(header.get('format','TEXT')).upper()
        if kind=='TEXT':
            params,text=text_parameters(header.get('text',''),data.header_variables)
            if params:components.append({'type':'header','parameters':params})
            if text:preview.append(text)
            if upload or data.header_media:raise HTTPException(422,'Metin başlıklı şablona medya eklenemez.')
        elif kind in MEDIA_TYPES:
            media_kind=MEDIA_TYPES[kind][0]
            if data.header_variables:raise HTTPException(422,'Medya başlığı için metin değişkeni gerekmiyor.')
            if upload:
                if data.header_media and data.header_media.link:raise HTTPException(422,'Medya için dosya veya bağlantıdan yalnızca birini seçin.')
                validate_upload(kind,upload)
                media={'id':'pending-upload'}
            elif data.header_media and data.header_media.link:
                media={'link':public_media_link(data.header_media.link)}
            else:raise HTTPException(422,'Bu şablonun başlığı için medya dosyası veya HTTPS bağlantısı gerekli.')
            filename=(data.header_media.filename if data.header_media else '') or (upload.filename if upload else '')
            filename=filename.replace('\\','/').rsplit('/',1)[-1][:200]
            if media_kind=='document' and filename:media['filename']=filename
            components.append({'type':'header','parameters':[{'type':media_kind,media_kind:media}]})
            preview.append({'IMAGE':'[Görsel]','VIDEO':'[Video]','DOCUMENT':'[Belge'+(': '+filename if filename else '')+']'}[kind])
        else:raise HTTPException(422,'Bu başlık biçimi desteklenmiyor. Metin, görsel, video veya belge başlıklı şablon seçin.')
    elif upload or data.header_media or data.header_variables:
        raise HTTPException(422,'Seçilen şablonda başlık bulunmuyor.')
    body=items.get('BODY',{}).get('text',template.body)
    params,text=text_parameters(body,data.variables,data.parameters)
    if params:components.append({'type':'body','parameters':params})
    if text:preview.append(text)
    footer=items.get('FOOTER',{}).get('text','')
    if PLACEHOLDER.search(footer):raise HTTPException(422,'Alt metin bileşeni değişken içeremez.')
    if footer:preview.append(footer)
    buttons=items.get('BUTTONS',{}).get('buttons',[])
    if not isinstance(buttons,list):raise HTTPException(422,'Geçersiz şablon butonları.')
    used=set()
    for index,button in enumerate(buttons):
        kind=str(button.get('type','')).upper();label=button.get('text','')
        if kind=='URL':
            url=button.get('url','');keys=variable_keys(url)
            if keys:
                if len(keys)!=1:raise HTTPException(422,'URL butonu tek bir dinamik değişken içermeli.')
                key=str(index);used.add(key);value=data.button_variables.get(key,'')
                if not value.strip() or len(value)>2000:raise HTTPException(422,f'{index+1}. URL butonunun değişkenini doldurun.')
                url=fill(url,{keys[0]:value})
                components.append({'type':'button','sub_type':'url','index':str(index),'parameters':[{'type':'text','text':value}]})
            preview.append(label+' → '+url)
        elif kind=='PHONE_NUMBER':preview.append(label+' → '+button.get('phone_number',''))
        elif kind=='QUICK_REPLY':
            components.append({'type':'button','sub_type':'quick_reply','index':str(index),'parameters':[{'type':'payload','payload':label[:128] or f'hys:{template.id}:{index}'}]})
            preview.append(label)
        else:raise HTTPException(422,f'{index+1}. butonun {kind} türü bu gönderim akışında desteklenmiyor.')
    if set(data.button_variables)!=used:raise HTTPException(422,'Yalnızca dinamik URL butonlarının değişkenlerini doldurun.')
    carousel=items.get('CAROUSEL')
    cards=getattr(data,'cards',[])
    if carousel:
        from types import SimpleNamespace
        approved=carousel.get('cards',[])
        if items.get('HEADER') or template.category!='MARKETING' or not isinstance(approved,list) or not 2<=len(approved)<=10:
            raise HTTPException(422,'Carousel için 2–10 kart içeren onaylı Marketing şablonu seçin.')
        if len(cards)!=len(approved):raise HTTPException(422,'Şablondaki her görsel kartını doldurun.')
        uploads=card_uploads or {}
        if any(i<0 or i>=len(approved) for i in uploads):raise HTTPException(422,'Geçersiz görsel kartı.')
        built=[];formats=set()
        for index,(definition,values) in enumerate(zip(approved,cards)):
            if not isinstance(definition,dict):raise HTTPException(422,'Geçersiz carousel kartı.')
            sub=SimpleNamespace(id=template.id,name=template.name,language=template.language,category=template.category,body='',components=json.dumps(definition.get('components',[])))
            parsed=definitions(sub)
            kind=parsed.get('HEADER',{}).get('format','')
            if 'CAROUSEL' in parsed or kind not in ('IMAGE','VIDEO'):raise HTTPException(422,'Carousel kartı görsel veya video başlığı içermelidir.')
            formats.add(kind)
            args=SimpleNamespace(**values.model_dump(),parameters=[],cards=[])
            # Pydantic nested media must remain an object for the standard builder.
            args.header_media=values.header_media
            payload,card_preview,_=build_template(sub,args,uploads.get(index))
            built.append({'card_index':index,'components':payload.get('components',[])})
            preview.append(f'Kart {index+1}: '+card_preview)
        if len(formats)!=1:raise HTTPException(422,'Carousel kartları aynı medya türünü kullanmalıdır.')
        components.append({'type':'carousel','cards':built})
        media_kind='carousel'
    elif cards or card_uploads:raise HTTPException(422,'Bu şablonda carousel kartları bulunmuyor.')
    result={'name':template.name,'language':{'code':template.language}}
    if components:result['components']=components
    return result,'\n'.join(preview),media_kind
