from streamlit.testing.v1 import AppTest

def test_actual_app():
    app=AppTest.from_file('../app.py',default_timeout=60).run()
    assert not app.exception
    if not app.metric:
        app.radio(key='data_mode').set_value('샘플 데이터').run()
    assert int(app.metric[0].value)>0
    app.text_input(key='keyword').set_value('NoSuchKeyword123456').run()
    assert not app.exception and app.metric[0].value=='0'
    app.text_input(key='keyword').set_value('').run()
    app.radio(key='data_mode').set_value('샘플 데이터').run()
    assert not app.exception and app.warning
    app.radio(key='pending_scope').set_value('보조 시트').run()
    assert not app.exception and app.metric[0].value=='0'

def test_title_and_visible_rev_navigation():
    app=AppTest.from_file('../app.py',default_timeout=60).run()
    assert not app.exception
    assert any(x.value=='양산 설비 통합 관리' for x in app.title)
    assert any('HW-11' in x.value for x in app.caption)
    assert app.sidebar.radio(key='main_page').value=='Pending 현황'
    assert app.radio(key='main_page').options==['Pending 현황','REV 관리','설비 H/W 이력관리']
    app.radio(key='main_page').set_value('REV 관리').run()
    assert not app.exception
    assert any('REV 관리' in x.value for x in app.header)
    # 실제 데이터가 있는 환경에서는 요약과 18건 이력이 표시됩니다.
    from pathlib import Path
    if (Path(__file__).resolve().parents[1]/'data/default.xlsx').exists():
        assert any('18건' in x.value for x in app.success)
        assert any('rev-history-table' in x.value and '주요 변경내용' in x.value for x in app.markdown)
        history=next(x.value for x in app.markdown if '<table class="rev-history-table">' in x.value)
        assert '<th>출처</th>' not in history
        assert history.count('<th>')==6
        assert 'border:1px solid #64748b' in history
        app.text_input(key='rev_search').set_value('NoSuchRev123456').run()
        assert any('검색 조건' in x.value for x in app.info)
    app.radio(key='main_page').set_value('Pending 현황').run()
    assert not app.exception
    app.radio(key='data_mode').set_value('샘플 데이터').run()
    app.radio(key='main_page').set_value('REV 관리').run()
    assert not app.exception
    assert any('샘플 데이터에는 REV 이력이 없습니다' in x.value for x in app.info)

def test_list_field_filter_and_removed_raw_expander():
    app=AppTest.from_file('../app.py',default_timeout=60).run()
    app.radio(key='data_mode').set_value('샘플 데이터').run()
    assert not app.exception
    assert not any('원문 전체' in x.label for x in app.expander)
    dashboard_total=app.metric[0].value
    app.multiselect(key='list_fields').set_value(['SW']).run()
    assert not app.exception
    tables=[x.value for x in app.dataframe if {'ID','분야'}.issubset(x.value.columns)]
    assert len(tables)==1 and set(tables[0]['분야'])=={'SW'}
    assert app.metric[0].value==dashboard_total
    assert any('S/W'==x for x in app.multiselect(key='list_fields').options)
    app.multiselect(key='list_fields').set_value([]).run()
    assert not app.exception
    assert any('분야 필터에 맞는' in x.value for x in app.info)

def test_binary_status_and_clickable_counts():
    app=AppTest.from_file('../app.py',default_timeout=60).run()
    app.radio(key='data_mode').set_value('샘플 데이터').run()
    assert not app.exception
    assert any(x.value=='양산 설비 통합 관리' for x in app.title)
    assert not any('확인 필요' in x.value for x in app.caption)
    status=next(x for x in app.sidebar.multiselect if x.label=='상태')
    assert status.options==['완료','미완료']
    app.button(key='kpi_done').click().run()
    assert not app.exception
    table=next(x.value for x in app.dataframe if {'ID','분야'}.issubset(x.value.columns))
    assert set(table['상태'])=={'완료'}
    app.button(key='reset_counts').click().run()
    app.button(key='kpi_open').click().run()
    table=next(x.value for x in app.dataframe if {'ID','분야'}.issubset(x.value.columns))
    assert set(table['상태'])=={'미완료'}
    app.button(key='count_분야_0_완료').click().run()
    assert not app.exception
    if not any('분야 필터에 맞는' in x.value for x in app.info):
        table=next(x.value for x in app.dataframe if {'ID','분야'}.issubset(x.value.columns))
        assert table['분야'].nunique()==1 and set(table['상태'])=={'완료'}
    app.button(key='reset_counts').click().run()
    app.button(key='count_설비_0_미완료').click().run()
    assert not app.exception
    table=next(x.value for x in app.dataframe if {'ID','분야'}.issubset(x.value.columns))
    assert table['설비'].nunique()==1 and set(table['상태'])=={'미완료'}


def test_pending_row_selection_and_filter_reset():
    import hashlib
    import json
    from html import escape
    app=AppTest.from_file('../app.py',default_timeout=60).run()
    app.radio(key='data_mode').set_value('샘플 데이터').run()
    assert not any(x.label=='상세 항목 선택' for x in app.selectbox)
    frame=next(x.value for x in app.dataframe if 'ID' in x.value.columns)
    table_key='pending_rows_'+hashlib.sha256(json.dumps(['sample',frame['ID'].tolist()],ensure_ascii=False).encode()).hexdigest()[:20]
    app.session_state[table_key]={'selection':{'rows':[1],'columns':[],'cells':[]}}
    app.run()
    assert not app.exception
    detail=next(x.value for x in app.markdown if 'aria-label="Pending 항목 상세"' in x.value)
    assert escape(frame.iloc[1]['내용']) in detail
    app.text_input(key='keyword').set_value(frame.iloc[0]['ID']).run()
    assert not app.exception
    filtered=next(x.value for x in app.dataframe if 'ID' in x.value.columns)
    detail=next(x.value for x in app.markdown if 'aria-label="Pending 항목 상세"' in x.value)
    assert escape(filtered.iloc[0]['내용']) in detail
