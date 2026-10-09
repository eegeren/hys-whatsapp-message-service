from datetime import timedelta
import pytest

from app.core import Message, Session, Template, now, settings


def add_customer(client, number, *, verified=False):
    created = client.post('/api/contacts/customer', json={
        'first_name': 'Test', 'phone': number,
    })
    assert created.status_code == 200, created.text
    contact_id = created.json()['id']
    if verified:
        consent = client.put(f'/api/contact/{contact_id}/consent', json={
            'verified': True,
            'scope': 'marketing',
            'source': 'Ayrı test formu',
            'evidence': 'local-test-evidence',
            'consent_date': '2026-10-08',
            'iys_manual_verified': True,
        })
        assert consent.status_code == 200, consent.text
    return contact_id


def test_conversation_views_only_contain_recorded_messages(client):
    with Session() as db:
        db.add_all([
            Message(phone='+905321234567', body='Gerçek webhook içeriği', direction='in', status='received', unread=True),
            Message(phone='+905321234567', body='API kabulü', direction='out', status='accepted', meta_id='wamid.recorded'),
        ])
        db.commit()

    rows = client.get('/api/conversations').json()
    assert len(rows) == 1
    assert rows[0]['phone'] == '+905321234567'
    assert rows[0]['unread'] == 1
    detail = client.get('/api/conversations/' + rows[0]['key']).json()
    assert [item['body'] for item in detail['items']] == ['Gerçek webhook içeriği', 'API kabulü']
    assert detail['items'][1]['status'] == 'accepted'


def test_bulk_preview_normalizes_deduplicates_and_requires_hys_permission(client):
    add_customer(client, '+905321234567', verified=True)
    add_customer(client, '+905331234567', verified=False)
    content = 'Telefon,izin\n0532 123 45 67,izinli\n+905321234567,izinli\n05331234567,izinli\nabc,izinli\n'
    response = client.post('/api/bulk/preview', files={
        'file': ('recipients.csv', content.encode(), 'text/csv'),
    })
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['unique_count'] == 2
    assert result['duplicate_count'] == 1
    assert result['invalid_count'] == 1
    assert result['eligible_count'] == 1
    assert result['excluded_count'] == 1
    assert 'tek başına izin sayılmaz' in result['permission_notice']


def test_bulk_campaign_requires_approved_marketing_and_never_sends(client):
    add_customer(client, '+905321234567', verified=True)
    preview = client.post('/api/bulk/preview', files={
        'file': ('recipients.csv', b'phone\n05321234567\n', 'text/csv'),
    }).json()
    draft = client.post('/api/templates', json={
        'name': 'workspace_draft', 'body': 'Merhaba', 'category': 'MARKETING',
    }).json()
    data = {'token': preview['token'], 'template_id': draft['id'], 'variables': {}}
    assert client.post('/api/bulk/campaign', json=data).status_code == 403

    with Session() as db:
        template = db.get(Template, draft['id'])
        template.status = 'APPROVED'
        db.commit()
    response = client.post('/api/bulk/campaign', json=data)
    assert response.status_code == 200, response.text
    campaign_id = response.json()['campaign']['id']
    assert client.get(f'/api/bulk/campaign/{campaign_id}').json()['total'] == 0
    assert client.get('/api/messages').json()['total'] == 0


def test_direct_send_stays_locked_in_dry_run_without_calling_meta(client, monkeypatch):
    import app.messaging as messaging

    def unexpected_graph(*args, **kwargs):
        raise AssertionError('Meta must not be called while DRY_RUN is enabled')

    monkeypatch.setattr(messaging, 'graph', unexpected_graph)
    monkeypatch.setattr(settings, 'dry_run', True)
    response = client.post('/api/conversations/send', json={
        'phone': '+905321234567', 'body': 'No real message',
    })
    assert response.status_code == 403
    assert 'DRY_RUN' in response.json()['detail']
    assert client.get('/api/messages').json()['total'] == 0


def test_new_message_eligibility_normalizes_phone_and_reports_window_and_permission(client):
    add_customer(client, '+905321234567', verified=True)
    with Session() as db:
        db.add(Message(
            phone='+905321234567', body='incoming event', direction='in',
            status='received', created=now() - timedelta(minutes=5),
        ))
        db.commit()

    response = client.get('/api/conversations/eligibility', params={
        'phone_number': '0532 123 45 67',
    })
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['phone'] == '+905321234567'
    assert result['contact_found'] is True
    assert result['service_window_open'] is True
    assert result['template_required'] is False
    assert result['text_allowed'] is False
    assert result['sender_ready'] is False
    assert result['allowed'] is False


def test_first_template_message_does_not_require_local_consent_or_24h_window(client, monkeypatch):
    import app.messaging as messaging

    add_customer(client, '+905321234567', verified=False)
    with Session() as db:
        template = Template(name='external_permission_template', language='tr',
                            category='MARKETING', status='APPROVED', body='Merhaba {{1}}', components='[]')
        db.add(template)
        db.commit()
        template_id = template.id

    sent = []
    def accepted_graph(method, path, payload=None, params=None):
        sent.append((method, path, payload))
        return {'messages': [{'id': 'wamid.mock-accepted'}]}

    monkeypatch.setattr(messaging, 'graph', accepted_graph)
    monkeypatch.setattr(messaging, 'connection_ok', lambda db: True)
    monkeypatch.setattr(settings, 'dry_run', False)
    monkeypatch.setattr(settings, 'live_send_enabled', True)
    response = client.post('/api/conversations/send', json={
        'phone': '0532 123 45 67', 'template_id': template_id,
        'parameters': ['Müşteri'],
    })
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'accepted'
    assert response.json()['delivery_status'] == 'unknown'
    assert sent[0][2]['type'] == 'template'
    assert sent[0][2]['to'] == '905321234567'


def test_free_text_reply_needs_open_window_but_not_local_permission_record(client, monkeypatch):
    import app.messaging as messaging

    add_customer(client, '+905321234567', verified=False)
    with Session() as db:
        db.add(Message(
            phone='+905321234567', body='Son gelen mesaj', direction='in',
            status='received', created=now() - timedelta(minutes=2),
        ))
        db.commit()

    def accepted_graph(*args, **kwargs):
        return {'messages': [{'id': 'wamid.mock-reply'}]}

    monkeypatch.setattr(messaging, 'graph', accepted_graph)
    monkeypatch.setattr(messaging, 'connection_ok', lambda db: True)
    monkeypatch.setattr(settings, 'dry_run', False)
    monkeypatch.setattr(settings, 'live_send_enabled', True)
    response = client.post('/api/conversations/send', json={
        'phone': '+905321234567', 'body': 'Teşekkürler, yardımcı olalım.',
    })
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'accepted'


def test_opted_out_number_is_blocked_for_direct_template_send(client, monkeypatch):
    import app.messaging as messaging

    contact_id = add_customer(client, '+905321234567')
    client.put(f'/api/contact/{contact_id}/consent', json={'verified': False, 'opted_out': True})
    with Session() as db:
        template = Template(name='blocked_template', language='tr', category='MARKETING',
                            status='APPROVED', body='Merhaba', components='[]')
        db.add(template); db.commit(); template_id = template.id
    def unexpected_graph(*args, **kwargs):
        raise AssertionError('Opted-out recipients must not reach Meta')
    monkeypatch.setattr(messaging, 'graph', unexpected_graph)
    monkeypatch.setattr(messaging, 'connection_ok', lambda db: True)
    monkeypatch.setattr(settings, 'dry_run', False)
    monkeypatch.setattr(settings, 'live_send_enabled', True)
    response = client.post('/api/conversations/send', json={
        'phone': '+905321234567', 'template_id': template_id,
    })
    assert response.status_code == 403
    assert 'reddi' in response.json()['detail']


def test_bulk_preview_skips_blank_rows_without_counting_invalid(client):
    content = 'phone,name\n05321234567,A\n,\n,,\n05331234567,B\n'
    response = client.post('/api/bulk/preview', files={
        'file': ('recipients.csv', content.encode(), 'text/csv'),
    })
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['skipped_count'] == 2
    assert result['invalid_count'] == 0


@pytest.mark.parametrize('body,values,expected,preview', [
    ('Merhaba {{1}}', {'1': 'Ayşe "Hanım"'}, ['Ayşe "Hanım"'], 'Merhaba Ayşe "Hanım"'),
    ('{{2}}: {{ 1 }} / {{1}}', {'2': 'İstanbul', '1': '{{2}}'},
     ['{{2}}', 'İstanbul'], 'İstanbul: {{2}} / {{2}}'),
    ('Merhaba', {}, [], 'Merhaba'),
])
def test_template_text_fields_convert_to_meta_parameters(client, monkeypatch, body, values, expected, preview):
    import app.messaging as messaging
    with Session() as db:
        template=Template(name='text_field_template',status='APPROVED',category='MARKETING',body=body,components='[]')
        db.add(template);db.commit();template_id=template.id
    captured=[]
    def fake_graph(method,path,payload=None,params=None):
        captured.append(payload)
        return {'messages':[{'id':'wamid.mock-fields'}]}
    monkeypatch.setattr(messaging,'graph',fake_graph)
    monkeypatch.setattr(messaging,'connection_ok',lambda db:True)
    monkeypatch.setattr(settings,'dry_run',False)
    monkeypatch.setattr(settings,'live_send_enabled',True)
    response=client.post('/api/conversations/send',json={
        'phone':'+905321234567','template_id':template_id,'variables':values,
    })
    assert response.status_code==200,response.text
    assert response.json()['body']==preview
    template_payload=captured[0]['template']
    actual=template_payload.get('components',[{'parameters':[]}])[0]['parameters']
    assert actual==[{'type':'text','text':value} for value in expected]


@pytest.mark.parametrize('values',[{}, {'1':' '}, {'1':'A','2':'B'}, {'2':'B'}])
def test_missing_or_unexpected_template_fields_never_call_meta(client,monkeypatch,values):
    import app.messaging as messaging
    with Session() as db:
        template=Template(name='required_field_template',status='APPROVED',category='MARKETING',body='Merhaba {{1}}',components='[]')
        db.add(template);db.commit();template_id=template.id
    captured=[]
    monkeypatch.setattr(messaging,'graph',lambda *args,**kwargs:captured.append(args))
    monkeypatch.setattr(messaging,'connection_ok',lambda db:True)
    monkeypatch.setattr(settings,'dry_run',False)
    monkeypatch.setattr(settings,'live_send_enabled',True)
    response=client.post('/api/conversations/send',json={
        'phone':'+905321234567','template_id':template_id,'variables':values,
    })
    assert response.status_code==422
    assert captured==[]
    assert client.get('/api/messages').json()['total']==0
