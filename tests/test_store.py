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
