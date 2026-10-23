import pytest
from app.core import settings
from tests.test_deployment import cloud,proxy_headers


def inspect(client,content,browser_bytes=None,headers=None):
    return client.post('/api/media/inspect',headers=headers or {},data={'browser_bytes':len(content) if browser_bytes is None else browser_bytes},files={'file':('clip.mp4',content,'video/mp4')})


def test_video_967_mb_is_received_intact_without_sending(client,monkeypatch):
    monkeypatch.setattr('app.meta.graph',lambda *a,**k:pytest.fail('Inspection must never call Meta'))
    size=9_670_000
    content=b'\x00\x00\x00\x18ftypisom'+b'x'*(size-12)
    response=inspect(client,content)
    assert response.status_code==200,response.text
    assert response.json()=={'browser_bytes':size,'received_bytes':size,'conversion_applied':False,'output_bytes':size,'codec_validation':'not_performed','message_sent':False}


@pytest.mark.parametrize('content,expected,status',[(b'','boş',422),(b'bad-video','içeriği',422),(b'ftyp'+b'x'*(16*1024*1024),'sınır',413)],ids=['empty','signature','oversize'])
def test_precise_upload_failures(client,content,expected,status):
    response=inspect(client,content)
    assert response.status_code==status
    assert expected in response.json()['detail']


def test_size_mismatch(client):
    response=inspect(client,b'\x00\x00\x00\x18ftypisom',browser_bytes=9_670_000)
    assert response.status_code==422
    assert '9670000' in response.json()['detail'] and '12 bayt' in response.json()['detail']


def test_inspection_preserves_production_auth_and_origin(client,monkeypatch):
    cloud(monkeypatch)
    content=b'\x00\x00\x00\x18ftypisom'
    assert inspect(client,content).status_code==403
    assert inspect(client,content,headers=proxy_headers()).status_code==200
    assert inspect(client,content,headers={**proxy_headers(),'Origin':'https://evil.example'}).status_code==403
    client.cookies.clear()
    assert inspect(client,content,headers=proxy_headers()).status_code==401


def test_meta_media_error_preserves_code_and_size_without_sending(monkeypatch):
    from fastapi import HTTPException
    from app.meta import upload_media
    def reject(*args,**kwargs):
        raise HTTPException(502,{'message':'Meta medya dosyasını kabul etmedi.','code':131053})
    monkeypatch.setattr('app.meta.graph',reject)
    with pytest.raises(HTTPException) as error:
        upload_media('clip.mp4',b'video','video/mp4')
    assert error.value.detail['code']==131053
    assert '5 bayt' in error.value.detail['message']
    assert 'Mesaj gönderilmedi' in error.value.detail['message']


def test_consumed_upload_is_rewound():
    import io
    from starlette.datastructures import UploadFile
    from app.media_io import read_upload
    raw=b'\x00\x00\x00\x18ftypisom'+b'x'*9_669_988
    file=UploadFile(io.BytesIO(raw),size=len(raw),filename='clip.mp4')
    assert file.file.read()==raw
    assert read_upload(file,16*1024*1024)==raw
