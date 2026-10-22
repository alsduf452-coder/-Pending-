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


def test_age_and_monthly_filters():
    from datetime import date
    today=date(2026,10,22)
    assert hw.installation_age('2025-10-22','Diffuser',today)['days']==365
    assert '#fee2e2' in hw.installation_age('2025-10-22','Diffuser',today)['style']
    assert hw.installation_age('2025-10-23','Diffuser',today)['days']==364
    assert hw.installation_age('2020-01-01','RFG',today)['days'] is None
    assert hw.installation_age('no date','Diffuser',today)['days'] is None
    assert '미래' in hw.installation_age('2027-01-01','Diffuser',today)['label']
    logs=fixture()['workLogs']
    logs.append({**logs[0],'id':'setup','workType':'초기 셋업','workDate':'2025-01-01'})
    logs.append({**logs[0],'id':'other','workDate':'2026-01-01','targetPart':'Matcher'})
    counts,rows=hw.monthly_work(logs,'A4CVD15I',2025)
    assert len(counts)==12 and len(rows)==1
    assert sum(sum(v for k,v in r.items() if k!='월') for r in counts)==len(rows)
    assert len(hw.monthly_work(logs,'A4CVD15I',2025,mode='전체 작업')[1])==2
    assert not hw.monthly_work(logs,'A4CVD15I',2026,part='Diffuser')[1]
    assert len(hw.monthly_work(logs,'A4CVD15I',2026,part='Matcher')[1])==1
    assert not hw.monthly_work(logs,'A4CVD15I',2025,chamber='Chamber B')[1]
    assert not hw.is_replacement(logs[1])


def test_archive_restore_and_backup_retains_history(tmp_path):
    path=tmp_path/'hw.sqlite3';hw.import_backup(path,encoded(fixture()),'등록자')
    row=hw.records(path,'workLogs')[0]
    with pytest.raises(ValueError):hw.archive_work(path,row['id'],'담당자','',row['_version'])
    hw.archive_work(path,row['id'],'삭제자','중복 정리',row['_version'])
    assert hw.records(path,'workLogs')==[]
    archived=hw.records(path,'workLogs',include_deleted=True)[0]
    assert archived['deletionReason']=='중복 정리'
    assert len(hw.records(path,'spacingMeasurements'))==1
    restored=tmp_path/'restored.sqlite3';hw.import_backup(restored,hw.backup_bytes(path),'백업복원')
    assert hw.records(restored,'workLogs')==[]
    with pytest.raises(ValueError):hw.archive_work(path,row['id'],'복원자','복원',row['_version'],restore=True)
    hw.archive_work(path,row['id'],'복원자','이력 복구',archived['_version'],restore=True)
    assert len(hw.records(path,'workLogs'))==1
    assert hw.records(path,'workLogs')[0]['restorationReason']=='이력 복구'
    assert {'IMPORT','ARCHIVE','RESTORE'}.issubset({r['action'] for r in hw.audit_records(path)})


def test_monthly_controls_and_card_actions(tmp_path):
    db=setup_ui(tmp_path);hw.import_backup(db,encoded(fixture()),'등록자')
    app=AppTest.from_file(tmp_path/'app.py',default_timeout=60).run()
    app.radio(key='main_page').set_value('설비 H/W 이력관리').run()
    assert not app.exception
    assert app.selectbox(key='monthly_part_A4CVD15I').options[1:9]==hw.PARTS[:8]
    app.selectbox(key='monthly_year_A4CVD15I').set_value(2025).run()
    app.selectbox(key='monthly_chamber_A4CVD15I').set_value('전체 Chamber').run()
    assert not app.exception
    app.radio(key='hw_section').set_value('작업 이력').run()
    app.button(key='card_edit_WL1').click().run()
    assert not app.exception and app.session_state['hw_edit_id']=='WL1'
    app.button(key='card_trace_WL1').click().run()
    assert not app.exception and app.radio(key='hw_section').value=='부품 추적'
    assert app.text_input(key='hw_trace_sn').value=='NEW'
    app.radio(key='hw_section').set_value('작업 이력').run()
    app.button(key='card_archive_WL1').click().run()
    next(x for x in app.text_input if x.label=='삭제 담당자 *').set_value('삭제자')
    next(x for x in app.text_input if x.label=='삭제 사유 *').set_value('중복')
    next(x for x in app.button if x.label=='삭제 보관 확인').click().run()
    assert not app.exception and not hw.records(db,'workLogs')
    next(x for x in app.text_input if x.label=='복원 담당자 *').set_value('복원자')
    next(x for x in app.text_input if x.label=='복원 사유 *').set_value('복원 테스트')
    next(x for x in app.button if x.label=='작업 이력 복원').click().run()
    assert not app.exception and len(hw.records(db,'workLogs'))==1


def test_measurement_diagrams_and_color_direction():
    from hw_ui import flatness_color, flatness_diagram_svg, spacing_diagram_svg, spacing_table_html, MEASURE_BLUE, MEASURE_RED
    assert flatness_color(-40,-40,19)==MEASURE_BLUE
    assert flatness_color(19,-40,19)==MEASURE_RED
    assert flatness_color(None,-40,19)=='#e2e8f0'
    assert flatness_color(0,0,0)=='#64748b'
    grid=[[-40,19,0,None,1,2,3]]*5
    svg=flatness_diagram_svg(grid)
    assert 'R1C1' in svg and 'R5C7' in svg and 'flatshade' in svg
    assert MEASURE_BLUE in svg and MEASURE_RED in svg
    assert '>0<' in svg and '>—<' in svg
    spacing=[867.2,None,886.4,888.1,885.1,872.6,883.6,890.0,884.7]
    html=spacing_table_html(spacing);diagram=spacing_diagram_svg(spacing)
    assert '867.2' in html and '미측정' in html
    assert 'GATE VALVE' in diagram and 'WINDOW' in diagram
    assert 'P6 · G/V 중앙' in diagram and 'P9 · 중앙 좌' in diagram
    assert 'RdBu' not in svg+diagram


def test_measurement_split_ui_and_chamber_history(tmp_path):
    db=setup_ui(tmp_path);data=fixture()
    data['equipments'][0]['chambers'].append({'chamberId':'Chamber B','initialParts':{},'installedParts':{}})
    b={**data['spacingMeasurements'][0],'id':'SP_B','chamberId':'Chamber B','relatedWorkLogId':None}
    data['spacingMeasurements'].append(b)
    hw.import_backup(db,encoded(data),'등록자')
    app=AppTest.from_file(tmp_path/'app.py',default_timeout=60).run()
    app.radio(key='main_page').set_value('설비 H/W 이력관리').run()
    app.selectbox(key='hw_chamber_A4CVD15I').set_value('Chamber B').run()
    app.radio(key='hw_section').set_value('Spacing').run()
    assert not app.exception
    headers=[x.value for x in app.subheader]
    assert any('왼쪽 50%' in x for x in headers) and any('오른쪽 50%' in x for x in headers)
    histories=[x for x in headers if '측정 이력 ·' in x]
    assert histories and all('Chamber B' in x for x in histories)
    assert not any(x.label=='측정 기록 선택' for x in app.selectbox)
    app.radio(key='hw_section').set_value('Flatness').run()
    assert not app.exception
    app.selectbox(key='hw_chamber_A4CVD15I').set_value('Chamber A').run()
    assert not app.exception
    assert any('낮은 값 · 파랑' in x.value and '높은 값 · 빨강' in x.value for x in app.caption)
    assert any('Chamber A Diffuser 측정 이력' in x.value for x in app.subheader)
    key='preview_flatnessMeasurements_FL1_1'
    app.session_state[key]={'edited_rows':{0:{'Col 1':-10.0}},'added_rows':[],'deleted_rows':[]}
    app.run()
    assert not app.exception
    next(x for x in app.text_input if x.label=='수치 변경자 *').set_value('수치 편집자')
    next(x for x in app.button if x.label=='편집한 측정값 저장').click().run()
    assert not app.exception
    assert hw.records(db,'flatnessMeasurements')[0]['grid'][0][0]==-10
    assert hw.records(db,'flatnessMeasurements')[0]['grid'][0][1] is None
