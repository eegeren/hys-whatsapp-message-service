"""Isolated staff UI sandbox. Every outbound Meta call is forbidden."""
import os,json
if os.environ.get('HYS_STAFF_UI_SANDBOX')!='1' or 'hys-ui-staff-' not in os.environ.get('DATABASE_URL',''):raise RuntimeError('Use an isolated staff UI database')
from sqlalchemy import select
from app.core import *
from app.main import app,ph
from app import staff,meta,media_templates
settings.dry_run=True
settings.live_send_enabled=False
settings.staff_upload_origin=''
def forbidden(*args,**kwargs):raise AssertionError('No outbound Meta in staff UI tests')
media_templates.graph=forbidden;media_templates.upload_template_sample=forbidden;staff.graph=forbidden;staff.upload_media=forbidden;meta.graph=forbidden
with Session() as db:
    if not db.scalar(select(User.id)):
        db.add(User(username='uiadmin',password=ph.hash('UITestPassword123!'),role='admin'))
        db.add(Contact(kind='staff',first_name='Test Personeli',phone='+905321234567',store='Test Mağazası'))
        for kind in ('DOCUMENT','VIDEO'):
            body='HYS personel duyurusu ektedir.'
            db.add(Template(name='hys_personel_'+kind.lower(),body=body,language='tr',category='UTILITY',status='APPROVED',components=json.dumps([{'type':'HEADER','format':kind},{'type':'BODY','text':body}])))
        db.commit()
