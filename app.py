from pathlib import Path
import pandas as pd
import plotly.express as px
import streamlit as st
from pending_store import set_default, source_key, add_item, read_items
from pending_data import MAIN, load_pending, filter_pending, summary, safe_export, excel_bytes

st.set_page_config(page_title='Pending Intelligence',page_icon='📊',layout='wide')
st.markdown('''<style>
.block-container {padding-top:2rem;max-width:1500px}
[data-testid="stMetric"] {background:white;border:1px solid #e4e9f2;border-radius:14px;padding:20px}
h1 {letter-spacing:-1.4px} [data-testid="stSidebar"] {border-right:1px solid #e4e9f2}
</style>''',unsafe_allow_html=True)

@st.cache_data(show_spinner=False)
def parse(data): return load_pending(data)

st.sidebar.title('📊 Pending Intelligence')
st.sidebar.caption('PECVD 양산 설비 · 통합 조회')
upload = st.sidebar.file_uploader('Pending Excel 업로드',type=['xlsx'],help='원본을 수정하거나 서버에 저장하지 않습니다.')
local = Path(__file__).parent/'data'/'source.xlsx'
saved_default = Path(__file__).parent/'data'/'default.xlsx'
db_path = Path(__file__).parent/'data'/'pending.sqlite3'
mode = st.sidebar.radio('데이터 선택',['실제 Excel','샘플 데이터'])
st.title('Pending Intelligence')
st.caption('CVD15I / CVD45I · 현황을 한눈에, 원문까지 정확하게')
try:
    if mode == '샘플 데이터':
        st.warning('샘플 데이터 모드입니다. 아래 항목은 가상 예시이며 실제 설비 현황이 아닙니다.')
        df = pd.read_csv(Path(__file__).parent/'data'/'sample.csv',keep_default_na=False)
        source = '가상 샘플 데이터'
    elif upload is not None:
        content=upload.getvalue(); df = parse(content); source=upload.name
    elif saved_default.exists() or local.exists():
        chosen=saved_default if saved_default.exists() else local
        content=chosen.read_bytes(); df = parse(content); source=f'기본 Excel ({chosen.name})'
    else:
        st.info('왼쪽 「Pending Excel 업로드」를 클릭해 원본 파일을 선택해주세요. 화면을 먼저 체험하려면 「샘플 데이터」를 선택하세요.')
        st.stop()
except Exception as exc:
    st.error(f'파일을 읽을 수 없습니다: {exc}')
    st.info('암호가 없는 .xlsx 파일인지, 원본과 동일한 시트·열 구조인지 확인해주세요.')
    st.stop()
if mode == '실제 Excel':
    if upload is not None and st.sidebar.button('이 Excel을 기본값으로 저장'):
        try:
            set_default(content, saved_default)
            st.sidebar.success('기본 Excel 저장 완료! 다음 실행부터 업로드 없이 불러옵니다.')
        except (OSError, ValueError) as exc:
            st.sidebar.error(f'기본값 저장 실패: {exc}')
    key=source_key(content)
    try:
        extra=read_items(db_path,key)
    except Exception as exc:
        st.error(f'추가 항목 저장소를 읽지 못했습니다: {exc}')
        st.stop()
    df=pd.concat([df,extra],ignore_index=True)
    st.caption(f'화면 등록 항목 {len(extra)}건 포함 · 같은 Excel 파일을 기준으로 추가 항목을 보관합니다.')
    if st.session_state.pop('item_saved',False):
        st.success('항목을 저장했습니다. 대시보드·목록·다운로드에 반영했습니다. 필터 조건에 따라 목록에서 숨겨질 수 있습니다.')
    with st.expander('＋ 새 Pending 항목 등록'):
        st.caption('추가 항목은 이 PC의 data/pending.sqlite3에 저장됩니다. 원본 Excel은 변경하지 않습니다. 클라우드에서는 재배포 시 로컬 저장 내용이 사라질 수 있습니다.')
        with st.form('new_pending',clear_on_submit=True):
            c1,c2,c3=st.columns(3)
            new_eq=c1.selectbox('설비 *',['CVD15I','CVD45I'],key='new_eq')
            new_field=c2.selectbox('분야 *',MAIN,key='new_field')
            new_state=c3.selectbox('상태 *',['미완료','완료','확인 필요'],key='new_state')
            new_text=st.text_area('Pending 내용 *',key='new_text',max_chars=10000)
            new_owner=st.text_input('담당자',key='new_owner',max_chars=200)
            new_unit=st.text_input('Unit',key='new_unit',max_chars=200)
            new_date=st.date_input('발생일',value=None,key='new_date')
            new_target=st.date_input('목표일',value=None,key='new_target')
            new_cause=st.text_area('원인',key='new_cause',max_chars=10000)
            new_progress=st.text_area('진행 사항',key='new_progress',max_chars=10000)
            new_action=st.text_area('조치내용',key='new_action',max_chars=10000)
            new_done=st.date_input('완료일',value=None,key='new_done')
            if st.form_submit_button('Pending 저장'):
                try:
                    add_item(db_path,key,{'설비':new_eq,'분야':new_field,'상태':new_state,'내용':new_text,'담당자':new_owner,'Unit':new_unit,'발생일':new_date,'목표일':new_target,'원인':new_cause,'진행 사항':new_progress,'조치내용':new_action,'완료일':new_done})
                    st.session_state['item_saved']=True
                    st.rerun()
                except (ValueError, OSError) as exc:
                    st.error(str(exc))
else:
    st.info('샘플 모드에서는 실제 항목을 저장하지 않습니다. 실제 Excel 모드에서 등록해주세요.')
st.caption(f'데이터 출처: {source} · 원본 보존 · 외부 AI 전송 없음')
scope=st.sidebar.radio('조회 범위',['주요 5개 분야','보조 시트','모든 시트'])
base = df[df['분야'].isin(MAIN)] if scope=='주요 5개 분야' else df[~df['분야'].isin(MAIN)] if scope=='보조 시트' else df
with st.sidebar:
    eq=st.multiselect('설비',sorted(base['설비'].unique()),default=sorted(base['설비'].unique()))
    fields=st.multiselect('분야',sorted(base['분야'].unique()),default=sorted(base['분야'].unique()))
    states=st.multiselect('상태',['완료','미완료','확인 필요'],default=['완료','미완료','확인 필요'])
    st.caption('필터를 모두 해제하면 조회 결과는 0건입니다. 미기재 설비는 추정하지 않습니다.')
query=st.text_input('통합 키워드 검색',key='keyword',placeholder='예: Leak / Robot / 담당자 이름 · 공백으로 여러 단어 검색')
with st.expander('질문 형태로 키워드 찾기'):
    st.caption('로컬 규칙 기반입니다. 예: Robot 관련 미완료 항목 알려줘. 아래 검색 결과는 질문의 설비·상태·키워드 조건을 추가로 적용합니다.')
    question=st.text_input('질문 검색')
    question_terms=question
    if question:
        import re
        for token in ['관련','항목','알려줘','보여줘','찾아줘','어떤','있나요','있어','목록','현황','건수','완료','미완료','확인 필요','CVD15I','CVD45I']:
            question_terms=question_terms.replace(token,' ')
        question_terms=re.sub(r'[?？.,]',' ',question_terms).strip()
view=filter_pending(base,eq,fields,states,query)
if question:
    asked_eq=[x for x in ['CVD15I','CVD45I'] if x in question.upper()]
    if asked_eq: view=view[view['설비'].isin(asked_eq)]
    asked_state='미완료' if '미완료' in question else '확인 필요' if '확인 필요' in question else '완료' if '완료' in question else None
    if asked_state: view=view[view['상태']==asked_state]
    view=filter_pending(view,view['설비'].unique(),view['분야'].unique(),view['상태'].unique(),question_terms)
    st.caption(f'질문 해석: 설비 {asked_eq or "전체"} / 상태 {asked_state or "전체"} / 키워드 {question_terms or "없음"} · 사이드바 조건과 함께 적용')
total=len(view); done=int((view['상태']=='완료').sum()); unknown=int((view['상태']=='확인 필요').sum())
for col,label,value in zip(st.columns(4),['전체 건수','완료','미완료 · 확인 필요 포함','완료율'],[f'{total:,}',f'{done:,}',f'{total-done:,}',f'{done/total*100 if total else 0:.1f}%']):
    col.metric(label,value)
st.caption(f'현재 필터 기준 · 미완료 {total-done-unknown}건 / 확인 필요 {unknown}건 · 완료율 = 완료 ÷ 전체')
with st.expander('집계 및 완료 판정 기준'):
    st.write('완료는 상태 O/○/완료만 인정합니다. 고객사 요청 상단 표는 H/I 두 값이 모두 완료일 때 완료이며, 39행 이후 표는 J열을 사용합니다. 공란은 확인 필요입니다. 미완료 카드에는 확인 필요를 포함합니다.')
    st.write('기본 집계는 HW(설계)·공정·SW·전장·기타만 포함합니다. 보조 시트는 중복 가능성이 있어 별도 조회합니다. 중복 제거, 연도 추정, 날짜 기반 지연 판정은 하지 않습니다. Rev 관리·Robot Teaching·이미지·도형은 구조화하지 않습니다. 요약 수식 대신 상세 행을 집계합니다.')
if view.empty:
    st.info('조건에 맞는 항목이 없습니다. 필터 또는 검색어를 조정해주세요.')
else:
    left,right=st.columns(2)
    for col,group in [(left,'분야'),(right,'설비')]:
        with col:
            st.subheader(f'{group}별 현황')
            agg=summary(view,group)
            melted=agg.melt(id_vars=[group],value_vars=['완료','미완료','확인 필요'],var_name='상태',value_name='건수')
            fig=px.bar(melted,x=group,y='건수',color='상태',color_discrete_map={'완료':'#2563eb','미완료':'#f59e0b','확인 필요':'#94a3b8'},barmode='stack')
            fig.update_layout(margin=dict(l=0,r=0,t=10,b=0),height=290,legend_title_text='',paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)')
            st.plotly_chart(fig,use_container_width=True)
            st.dataframe(agg,hide_index=True,use_container_width=True)
    st.subheader('Pending List')
    st.dataframe(view[['ID','설비','분야','상태','Unit','내용','담당자','목표일','시트','원본 행']],hide_index=True,use_container_width=True)
    st.subheader('항목 상세')
    selected=st.selectbox('상세 항목 선택',view['ID'].tolist(),format_func=lambda x:f"{x} · {view.loc[view['ID']==x,'내용'].iloc[0][:65]}")
    record=view.loc[view['ID']==selected].iloc[0]
    st.caption(f"항목 출처: {record['시트']} / 원본 행 {record['원본 행'] or "해당 없음"}")
    for key in ['설비','분야','상태','원문 상태','Unit','내용','발생일','담당자','원인','진행 사항','목표일','조치내용','완료일','조치자','45호기 적용 여부']:
        st.text(f"{key}: {record[key] or '미기재'}")
    with st.expander('원문 전체 · 숫자는 Excel 열 번호'):
        st.text(record['원문 전체'])
a,b=st.columns(2)
a.download_button('↓ 조회 결과 CSV',safe_export(view).to_csv(index=False).encode('utf-8-sig'),'pending_filtered.csv','text/csv',use_container_width=True)
b.download_button('↓ 조회 결과 Excel',excel_bytes(view),'pending_filtered.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',use_container_width=True)
st.caption('다운로드에는 현재 검색·필터 결과가 반영됩니다. Excel에는 분야별·설비별 집계 시트도 포함됩니다.')
