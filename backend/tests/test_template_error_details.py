import httpx,pytest
from fastapi import HTTPException
from app import meta
from app.core import settings

def test_graph_retains_safe_meta_reason_code_and_trace(monkeypatch):
    def handler(request):
        return httpx.Response(400,json={'error':{'code':100,'error_subcode':2388040,'message':'Invalid parameter','error_user_title':'Template error','error_user_msg':'Header rejected '+settings.meta_access_token,'fbtrace_id':'trace-123'}})
    original=httpx.Client
    monkeypatch.setattr(meta.httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    with pytest.raises(HTTPException) as e:meta.graph('POST','app/uploads',params={'file_type':'video/mp4'})
    detail=e.value.detail
    assert detail['code']==100 and detail['subcode']==2388040 and detail['trace_id']=='trace-123'
    assert detail['http_status']==400 and detail['ambiguous'] is False
    assert 'Header rejected' in detail['meta_message'] and settings.meta_access_token not in str(detail)
