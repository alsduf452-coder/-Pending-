from streamlit.testing.v1 import AppTest

def test_actual_app():
    app=AppTest.from_file('../app.py',default_timeout=60).run()
    assert not app.exception
    if not app.metric:
        app.sidebar.radio[0].set_value('샘플 데이터').run()
    assert int(app.metric[0].value)>0
    app.text_input(key='keyword').set_value('NoSuchKeyword123456').run()
    assert not app.exception and app.metric[0].value=='0'
    app.text_input(key='keyword').set_value('').run()
    app.sidebar.radio[0].set_value('샘플 데이터').run()
    assert not app.exception and app.warning
    app.sidebar.radio[1].set_value('보조 시트').run()
    assert not app.exception and app.metric[0].value=='0'
