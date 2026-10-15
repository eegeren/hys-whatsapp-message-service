import json
from contextlib import contextmanager
import pytest
from sqlalchemy import select
from app.core import Session,Message,WebhookItem
from app import incoming_media
from tests.test_webhook_production import envelope,post,message

def seed(client,kind='audio',extra=None):
    item=message();item.pop('text');item['type']=kind;item[kind]={'id':'987654','mime_type':'audio/ogg','caption':'Açıklama','filename':'dosya.ogg',**(extra or {})}
    assert post(client,envelope([item])).status_code==200
    key=client.get('/api/conversations').json()[0]['key'];row=client.get('/api/conversations/'+key).json()['items'][0]
    return row

def mock_media(monkeypatch,url='https://lookaside.fbsbx.com/whatsapp_business/attachments/?id=987654',mime='audio/ogg'):
    calls=[]
    def graph(method,path,**kwargs):
        assert method=='GET' and path=='987654';calls.append(kwargs);return {'url':url,'mime_type':mime}
    monkeypatch.setattr(incoming_media,'graph',graph)
    class Response:
        status_code=200;headers={}
        def iter_bytes(self,*args):yield b'0123456789'
    class Client:
        def __init__(self,**kwargs):assert kwargs['follow_redirects'] is False
        def __enter__(self):return self
        def __exit__(self,*args):pass
        @contextmanager
        def stream(self,*args,**kwargs):yield Response()
    monkeypatch.setattr(incoming_media.httpx,'Client',Client)
    return calls

@pytest.mark.parametrize('kind',['audio','image','video','document','sticker'])
def test_webhook_retains_media_without_secret_and_exposes_content(client,kind):
    row=seed(client,kind)
    assert row['content']=={'kind':kind,'available':True,'filename':'dosya.ogg','caption':'Açıklama'}
    with Session() as db:
        item=json.loads(db.scalar(select(WebhookItem)).payload)
        assert item[kind]['id']=='987654'
    assert '987654' not in json.dumps(row)

def test_authenticated_download_ranges_and_no_cache(client,monkeypatch):
    row=seed(client);calls=mock_media(monkeypatch)
    response=client.get(f"/api/messages/{row['id']}/media",headers={'Range':'bytes=2-5'})
    assert response.status_code==206 and response.content==b'2345'
    assert response.headers['content-range']=='bytes 2-5/10'
    assert response.headers['cache-control']=='private, no-store'
    assert response.headers['content-type'].startswith('audio/ogg')
    assert calls[0]['params']=={'phone_number_id':'123456'}
    assert client.get(f"/api/messages/{row['id']}/media",headers={'Range':'bytes=99-'}).status_code==416
    client.cookies.clear()
    assert client.get(f"/api/messages/{row['id']}/media").status_code==401

@pytest.mark.parametrize('url',['https://evil.example/file','http://lookaside.fbsbx.com/file','https://lookaside.fbsbx.com.evil.example/file','https://user@lookaside.fbsbx.com/file'])
def test_untrusted_download_urls_rejected(client,monkeypatch,url):
    row=seed(client);mock_media(monkeypatch,url=url)
    assert client.get(f"/api/messages/{row['id']}/media").status_code==502

def test_unsafe_html_not_rendered(client,monkeypatch):
    row=seed(client,'document');mock_media(monkeypatch,mime='text/html')
    assert client.get(f"/api/messages/{row['id']}/media").status_code==415

def test_old_missing_media_explicitly_reported(client):
    item=message();item.pop('text');item['type']='audio'
    assert post(client,envelope([item])).status_code==200
    with Session() as db:row=db.scalar(select(Message));id=row.id
    assert client.get(f'/api/messages/{id}/media').status_code==410

def test_location_contact_interactive_and_reaction(client):
    items=[]
    for i,(kind,data) in enumerate([('location',{'latitude':41.0,'longitude':29.0,'address':'İstanbul'}),('contacts',[{'name':{'formatted_name':'Test Kişisi'},'phones':[{'phone':'+905550000000'}]}]),('interactive',{'type':'button_reply','button_reply':{'id':'yes','title':'Evet'}}),('reaction',{'emoji':'👍'})]):
        item=message(f'wamid.{i}');item.pop('text');item['type']=kind;item[kind]=data;items.append(item)
    assert post(client,envelope(items)).status_code==200
    key=client.get('/api/conversations').json()[0]['key'];rows=client.get('/api/conversations/'+key).json()['items']
    assert {r['content']['kind'] for r in rows}=={'location','contacts','interactive','reaction'}
