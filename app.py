from pathlib import Path
import pandas as pd
import plotly.express as px
import streamlit as st
from pending_store import set_default, source_key, add_item, read_items, apply_edits, update_item, read_history, EDITABLE, read_revisions, save_revision, suggest_revision, read_revision_history, REV_FIELDS
from pending_data import MAIN, load_pending, filter_pending, summary, safe_export, excel_bytes, load_revision, revision_display, revision_table_html, binary_status, drilldown_pending

APP_NAME='양산 설비 PENDING 통합 관리'
APP_VERSION='HW-05'
LOGO_SVG='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><path fill="#8cba3d" d="M32 3 48 16 41 29 27 35 23 24Z"/><path fill="#f2b52d" d="M43 30 61 42 47 57 34 48 30 36Z"/><path fill="#a54c92" d="M29 36 42 48 28 61 13 48 19 38Z"/><path fill="#ed4641" d="M3 34 17 19 30 26 28 37 16 41Z"/></svg>'
st.set_page_config(page_title=APP_NAME,page_icon=LOGO_SVG,layout='wide')


def select_count(group=None,value=None,state=None):
    st.session_state['count_selection']={'group':group,'value':value,'state':state}
    st.session_state.pop('list_fields',None)


def reset_counts():
    st.session_state.pop('count_selection',None)

st.markdown("""<style>
[data-testid="stAppViewContainer"],.stApp {background:#e2e8f0;color:#172b4d}
[data-testid="stSidebar"] {background:#cbd5e1}
[data-baseweb="select"]>div,[data-testid="stTextInput"] input,[data-testid="stTextArea"] textarea,[data-testid="stNumberInput"] input,[data-testid="stDateInput"] input {background:#f1f5f9!important;color:#172b4d!important;border-color:#64748b!important}
[data-baseweb="select"]>div:focus-within,[data-testid="stTextInput"] input:focus,[data-testid="stTextArea"] textarea:focus {outline:2px solid #2563eb!important;outline-offset:1px}
[data-baseweb="popover"] [role="listbox"] {background:#f1f5f9;color:#172b4d}
[data-baseweb="tag"] {background:#bfdbfe!important;color:#173c72!important}
[data-baseweb="radio"] {color:#172b4d}
label[data-baseweb="radio"]:has(input:checked) {background:#bfdbfe;border-radius:6px;outline:1px solid #64748b;padding:4px}
[data-testid="stButton"] button,[data-testid="stDownloadButton"] button {border:1px solid #64748b;background:#f1f5f9;color:#173c72}
[data-testid="stButton"] button:hover,[data-testid="stDownloadButton"] button:hover {background:#bfdbfe;border-color:#1d4ed8;color:#15396b}
[data-testid="stExpander"] {background:#e8eef5;border-color:#94a3b8}
[data-testid="stForm"] {border-color:#94a3b8}
</style>""",unsafe_allow_html=True)
st.markdown('''<style>
.block-container {padding-top:2rem;max-width:1500px}
[data-testid="stMetric"] {background:#f1f5f9;border:1px solid #e4e9f2;border-radius:14px;padding:20px}
h1 {letter-spacing:-.7px;font-size:clamp(16px,2.2vw,30px)!important;white-space:nowrap} .sidebar-brand {display:flex;align-items:center;gap:5px;white-space:nowrap;font-size:clamp(10px,1.1vw,14px);font-weight:700;margin:12px 0} .sidebar-brand svg {width:26px;height:26px;flex-shrink:0} div[class*=st-key-kpi_] button p {font-size:28px;font-weight:700} div[class*=st-key-kpi_] button {width:100%;min-height:70px} [data-testid="stSidebar"] {border-right:1px solid #e4e9f2}
</style>''',unsafe_allow_html=True)

@st.cache_data(show_spinner=False)
def parse(data): return load_pending(data)

@st.cache_data(show_spinner=False)
def parse_revision(data): return load_revision(data)

st.sidebar.markdown(f'<div class="sidebar-brand">{LOGO_SVG}<span>{APP_NAME}</span></div>',unsafe_allow_html=True)
st.sidebar.caption('PECVD 양산 설비 · 통합 조회')
page=st.sidebar.radio('화면 선택',['Pending 현황','REV 관리','설비 H/W 이력관리'],key='main_page')
pending_filters=st.sidebar.container() if page=='Pending 현황' else None
upload = st.sidebar.file_uploader('Pending Excel 업로드',type=['xlsx'],help='파일 선택 또는 끌어놓기로 업로드합니다. 기본값 저장 버튼을 누르면 별도 복사본을 보관합니다.')
local = Path(__file__).parent/'data'/'source.xlsx'
saved_default = Path(__file__).parent/'data'/'default.xlsx'
db_path = Path(__file__).parent/'data'/'pending.sqlite3'
mode = st.sidebar.radio('데이터 선택',['실제 Excel','샘플 데이터'],key='data_mode')
st.title(APP_NAME)
st.caption(f'화면 버전 {APP_VERSION}')
with st.sidebar.expander('실행 정보 확인'):
    st.text(f'화면 버전: {APP_VERSION}')
    st.text(f'실행 파일: {Path(__file__).resolve()}')
st.caption('CVD15I / CVD45I · 현황을 한눈에, 원문까지 정확하게')
if page == '설비 H/W 이력관리':
    from hw_ui import render_hw
    data_dir=Path(__file__).parent/'data'
    hw_context=None
    if mode=='실제 Excel':
        pending_content=upload.getvalue() if upload is not None else saved_default.read_bytes() if saved_default.exists() else local.read_bytes() if local.exists() else None
        if pending_content:
            try:
                pending_source=source_key(pending_content)
                pending_frame=apply_edits(db_path,pending_source,pd.concat([parse(pending_content),read_items(db_path,pending_source)],ignore_index=True))
                hw_context={'source':pending_source,'frame':binary_status(pending_frame)}
            except Exception as exc:
                st.warning(f'Pending 연결용 파일을 읽지 못했습니다. H/W는 독립적으로 사용할 수 있습니다: {exc}')
    render_hw(data_dir,hw_context)
    st.stop()

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
if page == 'REV 관리':
    st.header('REV 관리 · 통합 이력')
    st.caption(f'데이터 출처: {source}')
    if mode == '샘플 데이터':
        st.info('샘플 데이터에는 REV 이력이 없습니다. 왼쪽에서 실제 Excel을 선택해주세요.')
        st.stop()
    revision=parse_revision(content)
    if not revision['sheet']:
        st.warning('선택한 Excel에서 REV 관리 시트를 찾지 못했습니다. 첫 시트 이름이 Rev 관리인지 확인해주세요.')
        st.stop()
    st.subheader(revision['title'] or 'CVD15I / CVD45I Pending List 통합 이력 관리')
    st.caption(f"라인: {revision['line'] or '미기재'} · 공정: {revision['process'] or '미기재'} · 원본 시트: {revision['sheet']}")
    st.info('요약표는 Excel 원본 기준입니다. 아래 REV 이력에는 화면에서 등록·수정한 내용도 포함됩니다. Pending 항목의 추가·수정은 REV에 자동 등록되지 않습니다.')
    totals=revision['summary']
    st.subheader('분야별 요약 · Excel 기준')
    # Excel과 같은 가로 배열. 저장된 수식 값이 없으면 추정하지 않습니다.
    st.dataframe(totals.set_index('구분').T,use_container_width=True)
    st.caption('총 건수·조치 건수·조치율은 Excel 저장값이며 수식을 재계산하지 않습니다. 고객사 요청은 Total과 별도 집계입니다.')
    rev_source=source_key(content)
    try:
        revisions=read_revisions(db_path,rev_source,revision['history'])
    except Exception as exc:
        st.error(f'REV 저장소를 읽지 못했습니다: {exc}')
        st.stop()
    if st.session_state.pop('rev_saved',False):
        st.success('REV를 저장하고 변경 이력을 기록했습니다. 검색 중이면 검색어를 지워 전체 목록을 확인하세요.')
        for input_key in ['new_rev_category','new_rev_text','new_rev_date','new_rev_author','new_rev_notes','new_rev_actor']:
            st.session_state.pop(input_key,None)
    with st.expander('＋ 새 REV 등록',expanded=True):
        st.caption('원본 Excel은 보존합니다. 신규 REV와 수정 사항은 기존 데이터베이스에 저장되어 재실행 후에도 유지됩니다.')
        with st.form('add_revision',clear_on_submit=False):
            new_rev_no=st.text_input('REV 번호 *',value=suggest_revision(revisions),key=f'new_rev_no_{len(revisions)}',max_chars=6)
            new_rev_category=st.text_input('구분',key='new_rev_category',placeholder='예: H/W, S/W, 공정')
            new_rev_text=st.text_area('주요 변경내용 *',key='new_rev_text',max_chars=20000)
            from datetime import datetime
            from zoneinfo import ZoneInfo
            new_rev_date=st.date_input('변경일자 *',value=datetime.now(ZoneInfo('Asia/Seoul')).date(),key='new_rev_date')
            new_rev_author=st.text_input('작성자 *',key='new_rev_author',max_chars=200)
            new_rev_notes=st.text_area('변경점 Key Word / 비고',key='new_rev_notes',max_chars=10000)
            new_rev_actor=st.text_input('등록자 *',key='new_rev_actor',max_chars=200)
            if st.form_submit_button('새 REV 저장'):
                try:
                    save_revision(db_path,rev_source,revision['history'],{'Rev No.':new_rev_no,'구분':new_rev_category,'주요 변경내용':new_rev_text,'변경일자':new_rev_date,'작성자':new_rev_author,'변경점 Key Word / 비고':new_rev_notes},new_rev_actor)
                    st.session_state['rev_saved']=True
                    st.rerun()
                except Exception as exc:
                    st.error(f'저장하지 못했습니다: {exc}')
    if not revisions.empty:
        last=revisions.iloc[-1]
        st.success(f"목록 마지막 REV: {last['Rev No.']} · 변경일: {last['변경일자']} · 이력 {len(revisions)}건")
    raw_revisions=revisions
    revisions,display_changes=revision_display(raw_revisions)
    with st.expander(f'표시 정리 내역 · {len(display_changes)}개 셀'):
        st.caption('원본 Excel과 저장된 데이터는 보존하고, 화면·REV CSV 표기만 정리했습니다. 수정 폼에서 저장하면 정리된 값도 변경 이력에 기록됩니다.')
        if display_changes.empty: st.info('정리가 필요한 표기가 없습니다.')
        else:
            st.dataframe(display_changes,hide_index=True,use_container_width=True)
            st.download_button('표시 정리 내역 CSV',safe_export(display_changes).to_csv(index=False).encode('utf-8-sig'),'rev_display_changes.csv','text/csv')
    st.subheader('REV 변경 이력')
    rev_query=st.text_input('REV 이력 검색',placeholder='변경내용 / 작성자 / 키워드 검색',key='rev_search')
    filtered=revisions
    for term in rev_query.split():
        filtered=filtered[filtered.astype(str).agg(' '.join,axis=1).str.contains(term,case=False,regex=False)]
    if filtered.empty:
        st.info('검색 조건에 맞는 REV 이력이 없습니다.')
    else:
        # escape=True로 Excel의 HTML을 실행하지 않고, 줄바꿈이 보이는 전체 표를 제공합니다.
        table=revision_table_html(filtered)
        st.markdown("""<style>
        .rev-history-scroll {overflow:auto;max-height:700px;border:1px solid #dbe3ef;border-radius:10px;background:white}
        .rev-history-table {width:100%;border-collapse:collapse;font-size:14px;min-width:950px}
        .rev-history-table th {background:#e7eef9;padding:12px;text-align:left;position:sticky;top:0;z-index:1}
        .rev-history-table td {padding:12px;vertical-align:top;white-space:pre-wrap;border:1px solid #e3e9f2;overflow-wrap:anywhere}
        .rev-history-table td:nth-child(3) {min-width:380px;width:46%}
        .rev-history-table tr:nth-child(even) {background:#f7f9fc}
        </style>"""+'<div class="rev-history-scroll">'+table+'</div>',unsafe_allow_html=True)
        st.caption('표 안에서 스크롤하면 전체 이력을 볼 수 있습니다. 변경내용은 줄바꿈을 유지합니다.')
        selected_rev=st.selectbox('REV 상세 선택',list(reversed(filtered.index.tolist())),format_func=lambda i:f"REV {filtered.loc[i,'Rev No.']} · {filtered.loc[i,'변경일자']}")
        st.subheader(f"REV {filtered.loc[selected_rev,'Rev No.']} 상세")
        for field in ['구분','주요 변경내용','변경일자','작성자','변경점 Key Word / 비고','원본 행','출처']:
            st.text(f"{field}: {filtered.loc[selected_rev,field]}")
        current_rev=raw_revisions.loc[selected_rev].to_dict()
        with st.expander('✏️ 선택한 REV 수정'):
            st.caption('날짜는 원문 표기를 유지합니다. 새 날짜는 YYYY-MM-DD 형식으로 입력해주세요. 변경자는 직접 입력하며 로그인 인증 정보가 아닙니다.')
            with st.form(f"edit_rev_{rev_source}_{current_rev['ID']}_{current_rev['버전']}"):
                rev_values={}
                for field in REV_FIELDS:
                    label='REV 번호' if field=='Rev No.' else field
                    if field in ['주요 변경내용','변경점 Key Word / 비고','구분','변경일자','작성자']:
                        rev_values[field]=st.text_area(label,value=str(filtered.loc[selected_rev,field]),key=f"rev_edit_{current_rev['ID']}_{current_rev['버전']}_{field}",max_chars=20000)
                    else:
                        rev_values[field]=st.text_input(label,value=str(filtered.loc[selected_rev,field]),key=f"rev_edit_{current_rev['ID']}_{current_rev['버전']}_{field}",max_chars=6)
                rev_actor=st.text_input('변경자 *',key=f"rev_actor_{current_rev['ID']}",max_chars=200)
                if st.form_submit_button('REV 수정 저장'):
                    try:
                        count=save_revision(db_path,rev_source,revision['history'],rev_values,rev_actor,current_rev)
                        if count:
                            st.session_state['rev_saved']=True
                            st.rerun()
                        else: st.info('변경된 내용이 없습니다.')
                    except Exception as exc:
                        st.error(f'저장하지 못했습니다: {exc}')
        with st.expander('선택한 REV의 등록·변경 기록'):
            audit=read_revision_history(db_path,rev_source,current_rev['ID'])
            if audit.empty: st.info('앱에서 등록·수정한 기록이 없습니다.')
            else: st.dataframe(audit,hide_index=True,use_container_width=True)
    st.download_button('REV 이력 CSV 다운로드',safe_export(filtered.drop(columns=['ID','버전'])).to_csv(index=False).encode('utf-8-sig'),'excel_rev_history.csv','text/csv')
    with st.expander('REV 전체 등록·변경 기록'):
        audit=read_revision_history(db_path,rev_source)
        if audit.empty: st.info('앱에서 등록·수정한 기록이 없습니다.')
        else:
            st.dataframe(audit,hide_index=True,use_container_width=True)
            st.download_button('REV 등록·변경 기록 CSV',safe_export(audit).to_csv(index=False).encode('utf-8-sig'),'rev_changes.csv','text/csv')
    st.stop()

st.caption('Excel 첫 시트의 요약과 변경 이력은 위쪽 「REV 관리」 메뉴에서 볼 수 있습니다.')
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
    df=apply_edits(db_path,key,pd.concat([df,extra],ignore_index=True))
    if st.session_state.pop('edit_saved',False):
        st.success('수정 내용을 저장하고 변경 이력을 기록했습니다.')
    st.caption(f'화면 등록 항목 {len(extra)}건 포함 · 같은 Excel 파일을 기준으로 추가 항목을 보관합니다.')
    if st.session_state.pop('item_saved',False):
        st.success('항목을 저장했습니다. 대시보드·목록·다운로드에 반영했습니다. 필터 조건에 따라 목록에서 숨겨질 수 있습니다.')
    with st.expander('＋ 새 Pending 항목 등록'):
        st.caption('추가 항목은 이 PC의 data/pending.sqlite3에 저장됩니다. 원본 Excel은 변경하지 않습니다. 클라우드에서는 재배포 시 로컬 저장 내용이 사라질 수 있습니다.')
        with st.form('new_pending',clear_on_submit=True):
            c1,c2,c3=st.columns(3)
            new_eq=c1.selectbox('설비 *',['CVD15I','CVD45I'],key='new_eq')
            new_field=c2.selectbox('분야 *',MAIN,key='new_field')
            new_state=c3.selectbox('상태 *',['미완료','완료'],key='new_state')
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
df=binary_status(df)
pending_filters.markdown('#### Pending 현황 필터')
scope=pending_filters.radio('조회 범위',['주요 5개 분야','보조 시트','모든 시트'],key='pending_scope')
count_context=(source_key(content) if mode=='실제 Excel' else 'sample',scope)
if st.session_state.get('count_context')!=count_context:
    reset_counts()
    st.session_state['count_context']=count_context
base = df[df['분야'].isin(MAIN)] if scope=='주요 5개 분야' else df[~df['분야'].isin(MAIN)] if scope=='보조 시트' else df
with pending_filters:
    eq=st.multiselect('설비',sorted(base['설비'].unique()),default=sorted(base['설비'].unique()))
    fields=st.multiselect('분야',sorted(base['분야'].unique()),default=sorted(base['분야'].unique()))
    states=st.multiselect('상태',['완료','미완료'],default=['완료','미완료'])
    st.caption('필터를 모두 해제하면 조회 결과는 0건입니다. 미기재 설비는 추정하지 않습니다.')
query=st.text_input('통합 키워드 검색',key='keyword',placeholder='예: Leak / Robot / 담당자 이름 · 공백으로 여러 단어 검색')
with st.expander('질문 형태로 키워드 찾기'):
    st.caption('로컬 규칙 기반입니다. 예: Robot 관련 미완료 항목 알려줘. 아래 검색 결과는 질문의 설비·상태·키워드 조건을 추가로 적용합니다.')
    question=st.text_input('질문 검색')
    question_terms=question
    if question:
        import re
        for token in ['관련','항목','알려줘','보여줘','찾아줘','어떤','있나요','있어','목록','현황','건수','완료','미완료','CVD15I','CVD45I']:
            question_terms=question_terms.replace(token,' ')
        question_terms=re.sub(r'[?？.,]',' ',question_terms).strip()
view=filter_pending(base,eq,fields,states,query)
if question:
    asked_eq=[x for x in ['CVD15I','CVD45I'] if x in question.upper()]
    if asked_eq: view=view[view['설비'].isin(asked_eq)]
    asked_state='미완료' if '미완료' in question else '완료' if '완료' in question else None
    if asked_state: view=view[view['상태']==asked_state]
    view=filter_pending(view,view['설비'].unique(),view['분야'].unique(),view['상태'].unique(),question_terms)
    st.caption(f'질문 해석: 설비 {asked_eq or "전체"} / 상태 {asked_state or "전체"} / 키워드 {question_terms or "없음"} · 사이드바 조건과 함께 적용')
total=len(view); done=int((view['상태']=='완료').sum())
kpi_total,kpi_done,kpi_open,kpi_rate=st.columns(4)
kpi_total.metric('전체 건수',f'{total:,}')
kpi_done.caption('완료 · 숫자를 누르면 목록 조회')
kpi_done.button(f'{done:,}',key='kpi_done',on_click=select_count,kwargs={'state':'완료'},use_container_width=True)
kpi_open.caption('미완료 · 숫자를 누르면 목록 조회')
kpi_open.button(f'{total-done:,}',key='kpi_open',on_click=select_count,kwargs={'state':'미완료'},use_container_width=True)
kpi_rate.metric('완료율',f'{done/total*100 if total else 0:.1f}%')
st.caption('현재 필터 기준 · 완료율 = 완료 ÷ 전체')
with st.expander('집계 및 완료 판정 기준'):
    st.write('완료는 상태 O/○/완료만 인정합니다. 고객사 요청 상단 표는 H/I 두 값이 모두 완료일 때 완료이며, 39행 이후 표는 J열을 사용합니다. 완료로 명시되지 않은 항목과 공란은 모두 미완료로 분류합니다.')
    st.write('기본 집계는 HW(설계)·공정·SW·전장·기타만 포함합니다. 보조 시트는 별도 조회합니다. 날짜 기반 지연 판정은 하지 않습니다. REV 원본 요약은 REV 관리에서 확인할 수 있습니다.')
if view.empty:
    st.info('조건에 맞는 항목이 없습니다. 필터 또는 검색어를 조정해주세요.')
else:
    left,right=st.columns(2)
    for col,group in [(left,'분야'),(right,'설비')]:
        with col:
            st.subheader(f'{group}별 현황')
            agg=summary(view,group)
            melted=agg.melt(id_vars=[group],value_vars=['완료','미완료'],var_name='상태',value_name='건수')
            fig=px.bar(melted,x=group,y='건수',color='상태',color_discrete_map={'완료':'#2563eb','미완료':'#f59e0b'},barmode='stack')
            fig.update_layout(margin=dict(l=0,r=0,t=10,b=0),height=270,legend_title_text='',paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)')
            st.plotly_chart(fig,use_container_width=True)
            headers=st.columns([1.5,1,1,1,1.2])
            for c,label in zip(headers,[group,'완료','미완료','전체','완료율(%)']): c.markdown(f'**{label}**')
            for row_number,row in agg.iterrows():
                cells=st.columns([1.5,1,1,1,1.2])
                label={'HW(설계)':'H/W 설계','SW':'S/W'}.get(row[group],row[group])
                cells[0].write(label)
                for cell,status in zip(cells[1:3],['완료','미완료']):
                    cell.button(f"{int(row[status]):,}",key=f'count_{group}_{row_number}_{status}',help=f'{label} · {status} 목록 보기',on_click=select_count,args=(group,row[group],status),use_container_width=True)
                cells[3].write(str(int(row['전체'])))
                cells[4].write(f"{row['완료율(%)']:.1f}")
    st.caption('분야·설비 표의 완료 또는 미완료 숫자를 누르면 아래 Pending List가 해당 조건으로 바뀝니다.')
st.subheader('Pending List')
field_labels={'HW(설계)':'H/W 설계','SW':'S/W'}
list_fields=st.multiselect('Pending List 분야 필터',options=sorted(base['분야'].unique()),default=sorted(base['분야'].unique()),format_func=lambda x:field_labels.get(x,x),key='list_fields')
selection=st.session_state.get('count_selection')
if selection:
    selected_label=' / '.join(str(x) for x in [selection.get('value'),selection.get('state')] if x)
    st.info(f'숫자 선택 조건: {selected_label}')
    st.button('숫자 선택 해제 · 전체 목록',key='reset_counts',on_click=reset_counts)
list_view=drilldown_pending(view[view['분야'].isin(list_fields)],selection)
st.caption(f'목록 {len(list_view)}건 · 사이드바·검색 조건에 추가 적용됩니다. 아래 다운로드도 이 목록 기준입니다. 상단 대시보드는 사이드바 조건을 유지합니다.')
if list_view.empty:
    st.info('분야 필터에 맞는 Pending 항목이 없습니다.')
else:
    st.dataframe(list_view[['ID','설비','분야','상태','Unit','내용','담당자','목표일','시트','원본 행']],hide_index=True,use_container_width=True)
    st.subheader('항목 상세')
    selected=st.selectbox('상세 항목 선택',list_view['ID'].tolist(),format_func=lambda x:f"{x} · {list_view.loc[list_view['ID']==x,'내용'].iloc[0][:65]}")
    record=list_view.loc[list_view['ID']==selected].iloc[0]
    st.caption(f"항목 출처: {record['시트']} / 원본 행 {record['원본 행'] or "해당 없음"}")
    for detail_field in ['설비','분야','상태','Unit','내용','발생일','담당자','원인','진행 사항','목표일','조치내용','완료일','조치자','45호기 적용 여부']:
        st.text(f"{detail_field}: {record[detail_field] or '미기재'}")
    if mode == '실제 Excel':
        def open_hw_work():
            st.session_state['main_page']='설비 H/W 이력관리'
            st.session_state['hw_section']='작업 이력'
            equipment_id='A4'+str(record['설비']) if record['설비'] in ['CVD15I','CVD45I'] else None
            st.session_state['pending_hw_prefill']={'source':key,'id':record['ID'],'title':str(record['내용'])[:160],'equipmentId':equipment_id}
            st.session_state.pop('hw_equipment',None)
        st.button('관련 H/W 작업 등록',key='pending_to_hw',on_click=open_hw_work)
        from hw_store import records as hw_records
        related_work=[r for r in hw_records(Path(__file__).parent/'data'/'hw_history.sqlite3','workLogs') if r.get('pendingLink',{} ) and r['pendingLink'].get('source')==key and r['pendingLink'].get('id')==record['ID']]
        if related_work:
            with st.expander(f'관련 H/W 작업 이력 {len(related_work)}건'):
                st.dataframe(pd.DataFrame([{'작업 ID':r['id'],'설비':r['equipmentId'],'챔버':r['chamberId'],'작업일':r['workDate'],'부품':r.get('targetPart',''),'내용':r.get('details','')} for r in related_work]),hide_index=True,use_container_width=True)
        with st.expander('✏️ 항목 수정 / 완료 처리'):
            st.caption('원본 내용은 보존하며 변경 사항만 별도로 저장합니다. 날짜는 원문을 유지하는 텍스트입니다. 새 날짜는 YYYY-MM-DD로 입력해주세요.')
            with st.form(f'edit_{selected}'):
                actor=st.text_input('변경자 *',key=f'actor_{selected}')
                values={}
                for field in EDITABLE:
                    if field=='상태':
                        values[field]=st.selectbox('변경할 상태',['완료','미완료'],index=['완료','미완료'].index(record[field]),key=f'edit_{selected}_{field}')
                    elif field in ['내용','원인','진행 사항','조치내용']:
                        values[field]=st.text_area(field,value=str(record[field]),key=f'edit_{selected}_{field}',max_chars=10000)
                    else:
                        values[field]=st.text_input(field,value=str(record[field]),key=f'edit_{selected}_{field}',max_chars=1000)
                save=st.form_submit_button('수정 내용 저장')
                complete=st.form_submit_button('완료 처리 후 저장')
                if save or complete:
                    if complete:
                        from datetime import datetime
                        from zoneinfo import ZoneInfo
                        values['상태']='완료'
                        if not values['완료일'].strip(): values['완료일']=datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat()
                    try:
                        count=update_item(db_path,key,record.to_dict(),values,actor)
                        if count:
                            st.session_state['edit_saved']=True
                            st.rerun()
                        else: st.info('변경된 내용이 없습니다.')
                    except Exception as exc:
                        st.error(f'저장하지 못했습니다: {exc}')
        with st.expander('이 항목의 변경 이력'):
            history=read_history(db_path,key,selected)
            if history.empty: st.info('아직 변경 이력이 없습니다.')
            else: st.dataframe(history,hide_index=True,use_container_width=True)
a,b=st.columns(2)
a.download_button('↓ 조회 결과 CSV',safe_export(list_view).to_csv(index=False).encode('utf-8-sig'),'pending_filtered.csv','text/csv',use_container_width=True)
b.download_button('↓ 조회 결과 Excel',excel_bytes(list_view),'pending_filtered.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',use_container_width=True)
st.caption('다운로드에는 현재 검색·필터 결과가 반영됩니다. Excel에는 분야별·설비별 집계 시트도 포함됩니다.')

if mode == '실제 Excel':
    with st.expander('전체 변경 이력'):
        history=read_history(db_path,key)
        if history.empty: st.info('아직 변경 이력이 없습니다.')
        else:
            st.dataframe(history,hide_index=True,use_container_width=True)
            st.download_button('변경 이력 CSV 다운로드',safe_export(history).to_csv(index=False).encode('utf-8-sig'),'pending_history.csv','text/csv')
