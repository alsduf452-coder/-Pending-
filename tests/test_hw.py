import base64
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import shutil
from zipfile import ZipFile
import pytest
from streamlit.testing.v1 import AppTest
import hw_store as hw
from hw_ui import full_backup


def fixture():
    return {'mode':'sample','equipments':[{'id':'A4CVD15I','name':'설비15','chambers':[{'chamberId':'Chamber A','initialParts':{'Diffuser':{'sn':'OLD','installedDate':'2025-01-01'}},'installedParts':{}}]}],
            'workLogs':[{'id':'WL1','equipmentId':'A4CVD15I','chamberId':'Chamber A','workDate':'2025-02-01','workType':'부품 교체','details':'부품 교체','beforeSn':'OLD','afterSn':'NEW','targetPart':'Diffuser','attachments':None}],
            'spacingMeasurements':[{'id':'SP1','equipmentId':'A4CVD15I','chamberId':'Chamber A','measuredAt':'2025-02-01','values':[0,None,2,3,4,5,6,7,8],'unit':'mils','relatedWorkLogId':'WL1'}],
            'flatnessMeasurements':[{'id':'FL1','equipmentId':'A4CVD15I','chamberId':'Chamber A','measuredAt':'2025-02-01','type':'Diffuser','grid':[[0,None,2,3,4,5,6]]*5,'unit':'mils'}],
            'spacingStandards':[{'pointIndex':i,'label':f'P{i}'} for i in range(1,10)]}


def encoded(data):return json.dumps(data,ensure_ascii=False).encode()


def test_import_validation_dedup_and_original_values(tmp_path):
    raw=fixture();raw['workLogs'][0]['details']=''
    plan=hw.parse_import(encoded(raw))
    assert not plan['errors'] and plan['warnings']
    db=tmp_path/'hw.sqlite3'
    result=hw.import_backup(db,encoded(raw),'등록자')
    assert result['added']==13
    assert hw.import_backup(db,encoded(raw),'등록자')['added']==0
    assert hw.records(db,'workLogs')[0]['details']==''
    assert hw.records(db,'spacingMeasurements')[0]['values'][:2]==[0,None]
    assert hw.records(db,'flatnessMeasurements')[0]['grid'][0][:2]==[0,None]
    invalid=deepcopy(raw);invalid['spacingMeasurements'][0]['values']=[None]
    assert hw.parse_import(encoded(invalid))['errors']
    with pytest.raises(ValueError):hw.import_backup(tmp_path/'bad.sqlite3',encoded(invalid),'人')
    assert hw.records(tmp_path/'bad.sqlite3','equipments')==[]
    invalid['workLogs'].append(deepcopy(invalid['workLogs'][0]))
    assert any('중복' in r['사유'] for r in hw.parse_import(encoded(invalid))['errors'])
    invalid=deepcopy(raw);invalid['flatnessMeasurements'][0]['chamberId']='없는챔버'
    assert hw.parse_import(encoded(invalid))['errors']
    invalid=deepcopy(raw);invalid['flatnessMeasurements'][0].pop('grid');invalid['flatnessMeasurements'][0]['gridRows']=[{'cells':x} for x in raw['flatnessMeasurements'][0]['grid']]
    assert not hw.parse_import(encoded(invalid))['errors']


def test_edit_concurrency_attachments_backup_and_calculations(tmp_path):
    db=tmp_path/'hw.sqlite3';hw.import_backup(db,encoded(fixture()),'가져오기')
    current=hw.records(db,'workLogs')[0]
    updated={**current,'details':'수정 내용','pendingLink':{'source':'excel-hash','id':'SW:6','title':'관련 이슈'}}
    raw=b'file bytes'
    hw.save_record(db,'workLogs',updated,'수정자',current['_version'],[{'name':'check.pdf','mime':'application/pdf','data':raw}])
    with pytest.raises(ValueError,match='다른 화면'):hw.save_record(db,'workLogs',updated,'다른 사용자',current['_version'])
    saved=hw.records(db,'workLogs')[0]
    assert hw.get_blob(db,saved['attachments'][0]['blobId'])['data']==raw
    restored=tmp_path/'restored.sqlite3'
    hw.import_backup(restored,hw.backup_bytes(db),'복원자')
    assert hw.records(restored,'workLogs')[0]['pendingLink']['source']=='excel-hash'
    assert hw.get_blob(restored,saved['attachments'][0]['blobId'])['data']==raw
    assert any(r['actor']=='수정자' for r in hw.audit_records(restored))
    assert hw.spacing_deltas([0,None,2,3,4,5,6,7,8])['5−1']==4
    assert hw.spacing_deltas([0,None,2,3,4,5,6,7,8])['5−2'] is None
    assert hw.flatness_span([[0,None],[2,-1]])==3
    eq=hw.records(db,'equipments')[0]
    assert hw.installed_parts(eq,'Chamber A',[saved])[0]['sn']=='NEW'
    assert any(r['구분']=='장착 후 기록' for r in hw.trace_sn([eq],[saved],'NEW'))
    data_dir=tmp_path/'data';data_dir.mkdir();shutil.copyfile(db,data_dir/'hw_history.sqlite3')
    archive=full_backup(data_dir)
    with ZipFile(BytesIO(archive)) as z:
        assert 'data/hw_history.sqlite3' in z.namelist()
        assert 'RESTORE.txt' in z.namelist()


def setup_ui(tmp_path):
    root=Path(__file__).resolve().parents[1]
    for name in ['app.py','pending_data.py','pending_store.py','hw_ui.py','hw_store.py']:
        shutil.copyfile(root/name,tmp_path/name)
    (tmp_path/'data').mkdir()
    return tmp_path/'data/hw_history.sqlite3'


def test_hw_without_pending_excel_and_all_screens(tmp_path):
    db=setup_ui(tmp_path)
    app=AppTest.from_file(tmp_path/'app.py',default_timeout=60).run()
    app.radio(key='main_page').set_value('설비 H/W 이력관리').run()
    assert not app.exception
    assert any('아직 H/W 데이터' in r.value for r in app.info)
    hw.import_backup(db,encoded(fixture()),'준비')
    app.run()
    assert not app.exception
    for section in ['작업 이력','부품 추적','Spacing','Flatness','데이터 관리','설비 현황']:
        app.radio(key='hw_section').set_value(section).run()
        assert not app.exception,section


def test_hw_work_registration_ui_and_audit(tmp_path):
    db=setup_ui(tmp_path);hw.import_backup(db,encoded(fixture()),'준비')
    app=AppTest.from_file(tmp_path/'app.py',default_timeout=60).run()
    app.radio(key='main_page').set_value('설비 H/W 이력관리').run()
    app.radio(key='hw_section').set_value('작업 이력').run()
    # New form precedes the edit form. Fill required inputs in the new form.
    next(x for x in app.text_area if x.label=='작업 내용 *').set_value('화면 신규 점검')
    next(x for x in app.text_input if x.label=='등록·변경자 *').set_value('작업자')
    next(x for x in app.button if x.label=='작업 이력 저장').click().run()
    assert not app.exception
    assert len(hw.records(db,'workLogs'))==2
    assert any(r['actor']=='작업자' for r in hw.audit_records(db))


def test_pending_work_link_roundtrip(tmp_path):
    from test_pending import workbook
    db=setup_ui(tmp_path)
    source=tmp_path/'data/default.xlsx';source.write_bytes(workbook())
    data=fixture()
    data['equipments'][0]['id']='A4CVD45I'
    for kind in ['workLogs','spacingMeasurements','flatnessMeasurements']:
        for r in data[kind]:r['equipmentId']='A4CVD45I'
    hw.import_backup(db,encoded(data),'준비')
    app=AppTest.from_file(tmp_path/'app.py',default_timeout=60).run()
    app.button(key='pending_to_hw').click().run()
    assert not app.exception
    assert app.radio(key='main_page').value=='설비 H/W 이력관리'
    assert app.radio(key='hw_section').value=='작업 이력'
    next(x for x in app.text_area if x.label=='작업 내용 *').set_value('Pending 관련 교체')
    next(x for x in app.text_input if x.label=='등록·변경자 *').set_value('연결 작업자')
    next(x for x in app.button if x.label=='작업 이력 저장').click().run()
    saved=hw.records(db,'workLogs')[-1]
    assert saved['pendingLink']['id']=='SW:6'
    import hashlib
    assert saved['pendingLink']['source']==hashlib.sha256(source.read_bytes()).hexdigest()
    selector=next(x for x in app.selectbox if x.label=='작업 상세 선택')
    selector.set_value(saved['id']).run()
    app.button(key='hw_back_pending').click().run()
    assert not app.exception
    assert app.radio(key='main_page').value=='Pending 현황'
    assert app.text_input(key='keyword').value=='SW:6'
    assert any('관련 H/W 작업 이력' in x.label for x in app.expander)
