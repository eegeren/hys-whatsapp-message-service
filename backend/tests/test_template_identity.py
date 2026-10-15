import copy
import json
import pytest
from fastapi import HTTPException
from app.core import Template, Session, settings
from app.bulk import canonical_components, definition_hash, legacy_definition_hash, definition_matches, check_live_template

def sample():
    return [{'type':'HEADER','format':'IMAGE','example':{'header_handle':['https://example.com/old']}},
            {'type':'BODY','text':'Merhaba {{1}}','example':{'body_text':[['HYS']]}},
            {'type':'BUTTONS','buttons':[{'type':'URL','text':'Firsatlar','url':'https://example.com/{{1}}','example':['one']},
                                         {'type':'QUICK_REPLY','text':'IPTAL'}]}]

def make_template(components):
    return Template(name='marketing_image',language='tr',category='MARKETING',status='APPROVED',meta_id='777',body='Merhaba {{1}}',components=json.dumps(components))

def test_review_samples_and_component_order_do_not_change_definition():
    original=sample(); updated=copy.deepcopy(original)
    updated[0]['example']['header_handle']=['https://example.com/new-signed-url']
    updated[1]['example']['body_text']=[['Another sample']]
    updated.reverse()
    assert definition_hash(make_template(original))==definition_hash(make_template(updated))
    assert canonical_components(original)==canonical_components(updated)

@pytest.mark.parametrize('change',['body','format','button_url','button_order','language'])
def test_actual_definition_changes_remain_blocked(change):
    t=make_template(sample());cfg={'definition_hash':definition_hash(t),'definition_hash_version':2}
    parts=sample()
    if change=='body':parts[1]['text']='Degisen metin'
    elif change=='format':parts[0]['format']='VIDEO'
    elif change=='button_url':parts[2]['buttons'][0]['url']='https://different.example/{{1}}'
    elif change=='button_order':parts[2]['buttons'].reverse()
    else:t.language='en_US'
    t.components=json.dumps(parts)
    assert not definition_matches(t,cfg)

def test_legacy_draft_is_compatible_only_with_exact_saved_definition():
    t=make_template(sample());cfg={'definition_hash':legacy_definition_hash(t)}
    assert definition_matches(t,cfg)
    t.components=json.dumps([{'type':'BODY','text':'Changed'}])
    assert not definition_matches(t,cfg)

@pytest.mark.parametrize('version',[1,2])
def test_readonly_remote_check_ignores_samples_but_rejects_actual_change(monkeypatch,version):
    import app.bulk as bulk
    monkeypatch.setattr(settings,'dry_run',False)
    monkeypatch.setattr(settings,'live_send_enabled',True)
    monkeypatch.setattr(bulk,'connection_ok',lambda db:True)
    t=make_template(sample())
    cfg={'phone_number_id':settings.meta_phone_number_id,'waba_id':settings.meta_waba_id,
         'definition_hash':definition_hash(t) if version==2 else legacy_definition_hash(t)}
    if version==2:cfg['definition_hash_version']=2
    remote=sample();remote[0]['example']['header_handle']=['https://example.com/new']
    calls=[]
    def graph(method,path,**kwargs):
        assert method=='GET' and path==settings.meta_waba_id+'/message_templates'
        calls.append(method)
        return {'data':[{'id':t.meta_id,'name':t.name,'language':t.language,'category':t.category,'status':'APPROVED','components':remote}]}
    monkeypatch.setattr(bulk,'graph',graph)
    with Session() as db:
        check_live_template(t,cfg,db)
        remote[1]['text']='Changed real content'
        with pytest.raises(HTTPException) as error:check_live_template(t,cfg,db)
        assert error.value.status_code==403
    assert calls==['GET','GET']
