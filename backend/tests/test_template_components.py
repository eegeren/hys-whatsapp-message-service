"""Template sends use mock Graph/upload functions only; no real message tests."""
import json
import pytest
import httpx
from fastapi import HTTPException
from app.core import Contact,Session,Template,settings
from tests.test_workflows import event,signed

@pytest.fixture
def sender(monkeypatch):
    import app.messaging as messaging
    calls=[]
    monkeypatch.setattr(settings,'dry_run',False)
    monkeypatch.setattr(settings,'live_send_enabled',True)
    monkeypatch.setattr(messaging,'connection_ok',lambda db:True)
    def graph(method,path,payload=None,params=None):
        calls.append(('message',payload))
        return {'messages':[{'id':'wamid.mock-components'}]}
    def upload(filename,content,content_type):
        calls.append(('upload',filename,content_type))
        return '987654321'
    monkeypatch.setattr(messaging,'graph',graph)
    monkeypatch.setattr(messaging,'upload_media',upload)
    return calls

def template_id(components,body='Legacy body',language='tr'):
    with Session() as db:
        template=Template(name='component_template',status='APPROVED',category='MARKETING',
                          language=language,body=body,components=json.dumps(components))
        db.add(template);db.commit();return template.id

def send(client,id,**fields):
    return client.post('/api/conversations/send',json={'phone':'+905321234567','template_id':id,**fields})

def test_static_header_footer_and_buttons_need_no_manual_variables(client,sender):
    id=template_id([
        {'type':'HEADER','format':'TEXT','text':'HYS'},
        {'type':'BODY','text':'Merhaba'},
        {'type':'FOOTER','text':'İletişim tercihleriniz için yanıt verin'},
        {'type':'BUTTONS','buttons':[{'type':'URL','text':'Site','url':'https://example.com'},
           {'type':'PHONE_NUMBER','text':'Ara','phone_number':'+905321234567'},
           {'type':'QUICK_REPLY','text':'STOP'}]},
    ])
    result=send(client,id,variables={})
    assert result.status_code==200,result.text
    payload=sender[0][1]['template']
    assert payload['components']==[{'type':'button','sub_type':'quick_reply','index':'2',
                                 'parameters':[{'type':'payload','payload':'STOP'}]}]
    assert result.json()['body'].startswith('HYS\nMerhaba\nİletişim tercihleriniz')
    assert 'Site → https://example.com' in result.json()['body']

def test_header_body_and_dynamic_url_keep_independent_order_and_language(client,sender):
    id=template_id([
        {'type':'HEADER','format':'TEXT','text':'Başlık {{1}}'},
        {'type':'BODY','text':'{{2}} / {{1}} / {{1}}'},
        {'type':'BUTTONS','buttons':[{'type':'URL','text':'Sabit','url':'https://example.com'},
           {'type':'PHONE_NUMBER','text':'Ara','phone_number':'+905321234567'},
           {'type':'URL','text':'Sipariş','url':'https://example.com/order/{{1}}'}]},
    ],language='en_US')
    response=send(client,id,variables={'2':'B','1':'A'},header_variables={'1':'H'},button_variables={'2':'ORD-42'})
    assert response.status_code==200,response.text
    payload=sender[0][1]['template']
    assert payload['language']=={'code':'en_US'}
    assert payload['components']==[
        {'type':'header','parameters':[{'type':'text','text':'H'}]},
        {'type':'body','parameters':[{'type':'text','text':'A'},{'type':'text','text':'B'}]},
        {'type':'button','sub_type':'url','index':'2','parameters':[{'type':'text','text':'ORD-42'}]},
    ]
    assert 'Başlık H\nB / A / A' in response.json()['body']
    assert 'https://example.com/order/ORD-42' in response.json()['body']

@pytest.mark.parametrize('kind,media_type,filename',[('IMAGE','image',''),('VIDEO','video',''),('DOCUMENT','document','katalog.pdf')])
def test_media_link_template_components(client,sender,kind,media_type,filename):
    id=template_id([{'type':'HEADER','format':kind},{'type':'BODY','text':'Merhaba {{1}}'}])
    response=send(client,id,variables={'1':'Ali'},header_media={'link':'https://example.com/asset','filename':filename})
    assert response.status_code==200,response.text
    media={'link':'https://example.com/asset'}
    if filename:media['filename']=filename
    assert sender[0][1]['template']['components'][0]=={'type':'header','parameters':[{'type':media_type,media_type:media}]}
    assert len(sender)==1

@pytest.mark.parametrize('kind,mime,filename,content',[
    ('IMAGE','image/png','resim.png',b'\x89PNG\r\n\x1a\nmock'),
    ('VIDEO','video/mp4','video.mp4',b'\x00\x00\x00\x18ftypisom'),
    ('DOCUMENT','application/pdf','katalog.pdf',b'%PDF-1.7 mock'),
])
def test_file_uploaded_only_after_valid_single_send(client,sender,kind,mime,filename,content):
    id=template_id([{'type':'HEADER','format':kind},{'type':'BODY','text':'Dosyalı mesaj'}])
    response=client.post('/api/conversations/send-with-media',data={'data':json.dumps({'phone':'+905321234567','template_id':id,'variables':{}})},files={'file':(filename,content,mime)})
    assert response.status_code==200,response.text
    assert response.json()['status']=='accepted'
    assert response.json()['delivery_status']=='unknown'
    assert [call[0] for call in sender]==['upload','message']
    header=sender[1][1]['template']['components'][0]
    assert header['parameters'][0][kind.lower()]['id']=='987654321'
    if kind=='DOCUMENT':assert header['parameters'][0]['document']['filename']==filename

@pytest.mark.parametrize('fields',[{}, {'header_media':{'link':'http://example.com/a'}},
    {'header_media':{'link':'https://127.0.0.1/a'}}, {'header_media':{'link':'https://user:pass@example.com/a'}}])
def test_missing_or_invalid_media_prevents_api_call(client,sender,fields):
    id=template_id([{'type':'HEADER','format':'IMAGE'},{'type':'BODY','text':'Merhaba'}])
    assert send(client,id,variables={},**fields).status_code==422
    assert sender==[]

def test_missing_dynamic_button_suffix_prevents_api_call(client,sender):
    id=template_id([{'type':'BODY','text':'Merhaba'},{'type':'BUTTONS','buttons':[{'type':'URL','text':'İncele','url':'https://example.com/{{1}}'}]}])
    assert send(client,id,variables={}).status_code==422
    assert sender==[]

def test_media_file_dry_run_auth_optout_and_bad_signature_never_upload(client,sender,monkeypatch):
    id=template_id([{'type':'HEADER','format':'IMAGE'},{'type':'BODY','text':'Merhaba'}])
    def request(content=b'\x89PNG\r\n\x1a\nmock'):
        return client.post('/api/conversations/send-with-media',data={'data':json.dumps({'phone':'+905321234567','template_id':id,'variables':{}})},files={'file':('x.png',content,'image/png')})
    monkeypatch.setattr(settings,'dry_run',True)
    assert request().status_code==403
    monkeypatch.setattr(settings,'dry_run',False)
    assert request(b'not-an-image').status_code==422
    with Session() as db:db.add(Contact(kind='customer',first_name='Ret',phone='+905321234567',opted_out=True));db.commit()
    assert request().status_code==403
    client.post('/api/logout')
    assert request().status_code==401
    assert sender==[]

def test_media_upload_failure_never_sends_message_and_reports_error(client,sender,monkeypatch):
    import app.messaging as messaging
    id=template_id([{'type':'HEADER','format':'DOCUMENT'},{'type':'BODY','text':'PDF'}])
    def failed_upload(*args):raise HTTPException(502,{'code':131053,'message':'Meta medya dosyasını kabul etmedi.','ambiguous':True})
    monkeypatch.setattr(messaging,'upload_media',failed_upload)
    result=client.post('/api/conversations/send-with-media',data={'data':json.dumps({'phone':'+905321234567','template_id':id,'variables':{}})},files={'file':('a.pdf',b'%PDF-1.7 mock','application/pdf')})
    assert result.json()['status']=='failed'
    assert '131053' in result.json()['error']
    assert sender==[]

def test_message_error_code_is_not_reported_as_accepted(client,sender,monkeypatch):
    import app.messaging as messaging
    id=template_id([{'type':'HEADER','format':'TEXT','text':'Sabit'},{'type':'BODY','text':'Merhaba'}])
    def failed_graph(*args,**kwargs):raise HTTPException(502,{'code':132012,'message':'Başlık türü eşleşmiyor.'})
    monkeypatch.setattr(messaging,'graph',failed_graph)
    result=send(client,id,variables={})
    assert result.json()['status']=='failed'
    assert '132012' in result.json()['error']

def test_named_parameters_preserve_meta_parameter_names(client,sender):
    id=template_id([{'type':'BODY','text':'Merhaba {{customer_name}}'}])
    assert send(client,id,variables={'customer_name':'Ali'}).status_code==200
    assert sender[0][1]['template']['components'][0]['parameters']==[{'type':'text','text':'Ali','parameter_name':'customer_name'}]

def test_quick_reply_webhook_preserves_optout_and_dedup(client):
    payload=event([{'id':'wamid.mock-button','from':'905321234567','type':'button','button':{'text':'STOP','payload':'STOP'}}])
    assert signed(client,payload).status_code==200
    assert signed(client,payload).json()['duplicate']
    with Session() as db:
        assert db.query(Contact).filter(Contact.phone=='+905321234567').one().opted_out
    assert client.get('/api/messages?direction=in').json()['items'][0]['body']=='STOP'

def test_upload_media_uses_cloud_api_multipart(monkeypatch):
    import app.meta as meta
    real_client=httpx.Client
    captured=[]
    def transport(request):
        captured.append(request)
        assert request.url.path.endswith('/123456/media')
        assert request.headers['content-type'].startswith('multipart/form-data;')
        assert b'name="messaging_product"' in request.content and b'whatsapp' in request.content
        assert b'filename="a.pdf"' in request.content
        return httpx.Response(200,json={'id':'987654321'})
    monkeypatch.setattr(meta.httpx,'Client',lambda **kwargs:real_client(transport=httpx.MockTransport(transport),**kwargs))
    assert meta.upload_media('a.pdf',b'%PDF-1.7','application/pdf')=='987654321'
    assert len(captured)==1
