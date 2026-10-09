import os,tempfile
from pathlib import Path
import pytest
root=Path(tempfile.mkdtemp(prefix='hys-tests-'))
os.environ['DATABASE_URL']='sqlite:///'+str(root/'test.db').replace('\\','/')
os.environ['DRY_RUN']='true'
os.environ['META_APP_SECRET']='test-secret'
os.environ['META_PHONE_NUMBER_ID']='123456'
os.environ['META_VERIFY_TOKEN']='verify-test'
os.environ['META_ACCESS_TOKEN']='unit-test-only-token'
os.environ['META_WABA_ID']='654321'
os.environ['META_GRAPH_API_VERSION']='v25.0'
os.environ['META_ENVIRONMENT']='test'
os.environ['LIVE_SEND_ENABLED']='false'
os.environ['BOOTSTRAP_TOKEN']='unit-test-only-bootstrap'
os.environ['META_TEST_MESSAGE_ENABLED']='false'
os.environ['META_TEST_PHONE_NUMBER_ID']=''
os.environ['META_TEST_RECIPIENTS']=''
from app.core import Base,engine
from app.main import app
from fastapi.testclient import TestClient
@pytest.fixture(autouse=True)
def database():
    Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
    yield
@pytest.fixture
def client():
    with TestClient(app) as c:
        c.headers['X-HYS-Request']='1'
        assert c.post('/api/setup',json={'username':'admin','password':'TestPassword123!','bootstrap_token':'unit-test-only-bootstrap'}).status_code==200
        assert c.post('/api/login',json={'username':'admin','password':'TestPassword123!'}).status_code==200
        yield c
