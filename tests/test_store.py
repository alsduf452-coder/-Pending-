from pathlib import Path
import pytest
from pending_store import *
from test_pending import workbook

def test_default_and_restart(tmp_path):
    content=workbook(); original=tmp_path/'original.xlsx';original.write_bytes(content)
    default=tmp_path/'default.xlsx';set_default(content,default)
    assert default.read_bytes()==original.read_bytes()
    with pytest.raises(Exception): set_default(b'bad file',default)
    assert default.read_bytes()==content
    db=tmp_path/'items.sqlite3';key=source_key(content)
    v={'설비':'CVD15I','분야':'SW','상태':'미완료','내용':'신규 테스트'}
    identifier=add_item(db,key,v)
    d=read_items(db,key)
    assert len(d)==1 and d.iloc[0]['ID']==identifier
    assert read_items(db,'other-file').empty
    assert original.read_bytes()==content
    with pytest.raises(ValueError): add_item(db,key,{**v,'내용':'  '})
    assert len(read_items(db,key))==1

def test_registration_screen(tmp_path):
    import shutil
    from streamlit.testing.v1 import AppTest
    root=Path(__file__).resolve().parents[1]
    for name in ['app.py','pending_data.py','pending_store.py']:
        shutil.copyfile(root/name,tmp_path/name)
    (tmp_path/'data').mkdir()
    (tmp_path/'data/source.xlsx').write_bytes(workbook())
    app=AppTest.from_file(tmp_path/'app.py',default_timeout=60).run()
    assert not app.exception
    before=int(app.metric[0].value)
    app.text_area(key='new_text').set_value('새로운 화면 등록 테스트')
    next(b for b in app.button if b.label=='Pending 저장').click().run()
    assert not app.exception
    assert int(app.metric[0].value)==before+1
    again=AppTest.from_file(tmp_path/'app.py',default_timeout=60).run()
    assert not again.exception
    assert int(again.metric[0].value)==before+1
    selected=next(w for w in again.selectbox if w.label=='상세 항목 선택').value
    again.text_input(key=f'actor_{selected}').set_value('화면 테스트')
    again.text_area(key=f'edit_{selected}_진행 사항').set_value('현장 조치 완료')
    next(b for b in again.button if b.label=='완료 처리 후 저장').click().run()
    assert not again.exception
    history=read_history(tmp_path/'data/pending.sqlite3',source_key((tmp_path/'data/source.xlsx').read_bytes()),selected)
    assert '진행 사항' in history['변경 필드'].tolist()
    assert '완료일' in history['변경 필드'].tolist()

def test_edits_history_and_conflict(tmp_path):
    db=tmp_path/'db.sqlite3';content=workbook();key=source_key(content)
    original=load_pending(content);row=original.iloc[0].to_dict()
    assert update_item(db,key,row,{'상태':'미완료','진행 사항':'부품 대기'},'김담당')==2
    changed=apply_edits(db,key,original)
    assert changed.iloc[0]['상태']=='미완료'
    assert original.iloc[0]['상태']=='완료'
    assert len(read_history(db,key,row['ID']))==2
    assert read_history(db,'other').empty
    with pytest.raises(ValueError): update_item(db,key,row,{'상태':'완료'},'다른 사용자')
    assert len(read_history(db,key))==2
    assert update_item(db,key,changed.iloc[0].to_dict(),{'상태':'완료','완료일':'2026-10-22'},'김담당')==2
    assert apply_edits(db,key,original).iloc[0]['완료일']=='2026-10-22'
    assert apply_edits(db,'other',original).iloc[0]['완료일']==''
