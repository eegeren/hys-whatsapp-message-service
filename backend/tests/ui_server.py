"""Explicit fake Graph server for isolated Playwright tests; no outbound calls."""
import os
if os.environ.get('HYS_UI_SANDBOX_MOCK')!='1' or 'hys-ui-' not in os.environ.get('DATABASE_URL',''):
    raise RuntimeError('UI mock requires an isolated temporary database')
from app.core import settings
settings.meta_access_token='ui-test-only-token'
settings.meta_app_secret='ui-test-only-secret'
settings.meta_verify_token='ui-test-only-verify'
settings.meta_environment='test'
settings.meta_phone_number_id='123456'
settings.meta_waba_id='654321'
settings.meta_test_phone_number_id='123456'
settings.meta_test_waba_id='654321'
settings.meta_production_phone_number_ids=''
settings.meta_test_recipients='+905321234567'
settings.meta_test_message_enabled=True
settings.dry_run=True
settings.live_send_enabled=False
from app.main import app
from app import test_messages
def fake(method,path,payload=None,params=None):
    if method=='POST' and path=='123456/messages':return {'messages':[{'id':'wamid.ui-test-only','message_status':'accepted'}]}
    if method=='GET' and path=='654321':return {'id':'654321'}
    if method=='GET' and path=='123456':return {'id':'123456','account_mode':'SANDBOX'}
    if method=='GET' and path=='654321/phone_numbers':return {'data':[{'id':'123456','account_mode':'SANDBOX'}]}
    if method=='GET' and path=='654321/message_templates':return {'data':[{'name':'hello_world','language':'en_US','status':'APPROVED'}]}
    raise AssertionError('Unexpected mock request; outbound network forbidden')
test_messages.graph=fake
from app import campaigns,bulk,messaging,worker
from app.core import Session,Template
from sqlalchemy import select
def template_fake(method,path,payload=None,params=None):
    if method!='GET' or path!='654321/message_templates':raise AssertionError('No real Meta calls in UI tests')
    with Session() as db:
        return {'data':[{'id':f'ui-template-{t.id}','name':t.name,'language':t.language,'category':t.category,'status':'APPROVED','components':__import__('json').loads(t.components) or [{'type':'BODY','text':t.body}]} for t in db.scalars(select(Template))]}
campaigns.graph=template_fake
bulk.graph=template_fake
messaging.graph=fake
worker.graph=fake
def forbid_media_upload(*args,**kwargs):raise AssertionError('UI previews and DRY_RUN must not upload to Meta')
bulk.upload_media=forbid_media_upload
messaging.upload_media=forbid_media_upload
from pathlib import Path
bulk.MEDIA_DIR=Path(os.environ['DATABASE_URL'].removeprefix('sqlite:///')).parent/'bulk-media'
test_messages.LOCAL_ENV_PATH=Path(os.environ['DATABASE_URL'].removeprefix('sqlite:///')).parent/'ui.env'
test_messages.LOCAL_ENV_PATH.write_text('META_TEST_RECIPIENTS=\n',encoding='utf-8')
