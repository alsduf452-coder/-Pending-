"""Streamlit 설비 H/W 이력관리 화면."""
from datetime import datetime
from io import BytesIO
import json
import math
from pathlib import Path
import sqlite3
import tempfile
from uuid import uuid4
from zipfile import ZipFile, ZIP_DEFLATED
from zoneinfo import ZoneInfo
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import hw_store as store
from pending_data import safe_export


def today(): return datetime.now(ZoneInfo('Asia/Seoul')).date()


def text(value): return '' if value is None else str(value)


def table(rows):
    if rows:st.dataframe(pd.DataFrame(rows),hide_index=True,use_container_width=True)
    else:st.info('등록된 기록이 없습니다.')


def show_audit(path,identifier=None):
    rows=store.audit_records(path,identifier)
    if not rows:st.info('변경 이력이 없습니다.');return
    readable=[]
    for r in rows:
        before=json.loads(r['before_json']) if r['before_json'] else {}
        after=json.loads(r['after_json']) if r['after_json'] else {}
        fields=[key for key in set(before)|set(after) if before.get(key)!=after.get(key)]
        stamp=pd.to_datetime(r['timestamp'],utc=True).tz_convert('Asia/Seoul').strftime('%Y-%m-%d %H:%M:%S KST')
        for field in sorted(fields):
            readable.append({'시각':stamp,'변경자':r['actor'],'작업':r['action'],'종류':store.KINDS[r['kind']],'항목 ID':r['entity_id'],'필드':field,'변경 전':json.dumps(before.get(field),ensure_ascii=False),'변경 후':json.dumps(after.get(field),ensure_ascii=False)})
    df=pd.DataFrame(readable)
    st.dataframe(df,hide_index=True,use_container_width=True)
    st.download_button('변경 이력 CSV',safe_export(df).to_csv(index=False).encode('utf-8-sig'),'hw_audit.csv','text/csv',key=f'audit_{identifier or "all"}')


def filter_rows(rows,equipment,chamber,query=''):
    result=[r for r in rows if r.get('equipmentId')==equipment and (chamber=='전체' or r.get('chamberId')==chamber)]
    for word in query.split(): result=[r for r in result if word.casefold() in json.dumps(r,ensure_ascii=False).casefold()]
    return result


def pending_picker(context,equipment,current=None):
    links={}
    if context:
        frame=context['frame']
        eq=equipment.removeprefix('A4')
        for _,row in frame[frame['설비'].str.contains(eq,regex=False)].iterrows():
            links[row['ID']]={'source':context['source'],'id':row['ID'],'title':str(row['내용'])[:160]}
    if current:
        existing_key=current['id']
        # 다른 Excel에 저장된 링크는 별도 키로 유지하여 같은 행 번호로 바뀌지 않게 합니다.
        if not context or current.get('source')!=context['source']:existing_key='기존 연결 유지'
        links[existing_key]=current
    options=['연결 없음']+list(links)
    default=next((k for k,v in links.items() if v==current),'연결 없음')
    selected=st.selectbox('관련 Pending',options,index=options.index(default),format_func=lambda k:k if k=='연결 없음' else f"{links[k]['id']} · {links[k].get('title','')[:60]}")
    return links.get(selected)


def show_pending_link(link,context):
    if not link: return
    st.caption(f"관련 Pending: {link['id']} · {link.get('title','')}")
    if context and link.get('source')==context['source']:
        matched=context['frame'][context['frame']['ID']==link['id']]
        if not matched.empty:
            st.write('현재 Pending 상태:',matched.iloc[0]['상태'])
            def back():
                st.session_state['main_page']='Pending 현황'
                st.session_state['keyword']=link['id']
                st.session_state.pop('count_selection',None)
                st.session_state.pop('list_fields',None)
            st.button('연결된 Pending 조회',on_click=back,key='hw_back_pending')
            st.caption('사이드바 필터로 가려지면 조회 범위·설비·분야·상태를 전체로 선택해주세요.')
            return
    st.warning('현재 선택한 Excel에서 연결 대상을 찾지 못했습니다. 연결과 H/W 기록은 보존됩니다.')


def attachments(path,item):
    for i,attachment in enumerate(item.get('attachments') or []):
        if not isinstance(attachment,dict):continue
        st.caption(attachment.get('name','첨부파일'))
        blob=store.get_blob(path,attachment['blobId']) if attachment.get('blobId') else None
        if blob:
            if blob['mime'] in ['image/png','image/jpeg']:
                try:st.image(blob['data'],caption=blob['name'],width=500)
                except Exception:st.info('이미지 미리보기를 표시하지 못했습니다. 다운로드해 확인해주세요.')
            st.download_button('첨부파일 다운로드',blob['data'],blob['name'],blob['mime'],key=f'blob_{item["id"]}_{i}')
        else:
            st.info('백업에는 파일 경로만 있고 실제 파일이 없습니다. 필요한 원본 파일을 작업 수정에서 첨부해주세요.')


def work_form(path,equipment,chambers,context,current=None):
    current=current or {};identifier=current.get('id') or 'new'
    version=current.get('_version')
    with st.form(f'work_form_{identifier}_{version}'):
        ch=st.selectbox('작업 챔버',chambers,index=chambers.index(current['chamberId']) if current.get('chamberId') in chambers else 0,disabled=bool(current))
        work_date=st.text_input('작업일 * · YYYY-MM-DD',value=current.get('workDate',today().isoformat()))
        work_time=st.text_input('작업 시각 · HH:MM',value=(current.get('workTimestamp') or '')[11:16])
        work_order=st.number_input('같은 날 작업 순서',min_value=1,step=1,value=int(current.get('workOrder') or 1))
        types=['초기 셋업','부품 교체','교체/PM','점검','Tuning','CSD 조정','재측정','기타']
        if current.get('workType') and current['workType'] not in types:types.append(current['workType'])
        work_type=st.selectbox('작업 유형',types,index=types.index(current.get('workType') or '점검'))
        parts=store.PARTS.copy()
        if current.get('targetPart') and current['targetPart'] not in parts:parts.append(current['targetPart'])
        part=st.selectbox('대상 부품',parts,index=parts.index(current.get('targetPart') or '기타 부품'))
        before=st.text_input('교체 전 S/N',value=current.get('beforeSn',''))
        after=st.text_input('교체 후 S/N',value=current.get('afterSn',''))
        reason=st.text_area('작업 사유',value=current.get('reason',''))
        details=st.text_area('작업 내용 *',value=current.get('details',''),max_chars=20000)
        statuses=['정상완료','조치필요','모니터링중','이슈발생']
        status=st.selectbox('작업 결과',statuses,index=statuses.index(current.get('issueStatus','정상완료')) if current.get('issueStatus','정상완료') in statuses else 0)
        worker=st.text_input('작업자',value=current.get('worker',''))
        prefill=st.session_state.get('pending_hw_prefill')
        if prefill and prefill.get('equipmentId') not in [None,equipment]:prefill=None
        pending=pending_picker(context,equipment,current.get('pendingLink') or prefill)
        photos=st.file_uploader('첨부 · PNG/JPG/PDF, 개당 10MB',type=['png','jpg','jpeg','pdf'],accept_multiple_files=True,key=f'work_photos_{identifier}_{version}')
        actor=st.text_input('등록·변경자 *',max_chars=200)
        if st.form_submit_button('작업 이력 저장'):
            try:
                if work_time and not __import__('re').fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',work_time):raise ValueError('시각은 HH:MM 형식으로 입력해주세요.')
                item={**store.snapshot_record(current),'id':current.get('id') or 'WORK-'+uuid4().hex,'equipmentId':equipment,'chamberId':ch,'workDate':work_date,'workTimestamp':work_date+(' '+work_time if work_time else ''),'workOrder':work_order,'workType':work_type,'targetPart':part,'beforeSn':before.strip(),'afterSn':after.strip(),'reason':reason,'details':details.strip(),'issueStatus':status,'worker':worker,'pendingLink':pending}
                uploads=[{'name':f.name,'data':f.getvalue(),'mime':'application/pdf' if f.name.lower().endswith('.pdf') else 'image/png' if f.name.lower().endswith('.png') else 'image/jpeg'} for f in photos]
                store.save_record(path,'workLogs',item,actor,version,uploads)
                st.session_state.pop('pending_hw_prefill',None)
                st.session_state['hw_saved']='작업 이력을 저장했습니다. Pending 완료 상태는 별도로 처리해주세요.'
                st.rerun()
            except Exception as exc:st.error(f'저장 실패: {exc}')


def measurement_form(path,kind,equipment,chambers,logs,current=None):
    current=current or {};spacing=kind=='spacingMeasurements';identifier=current.get('id','new');version=current.get('_version')
    with st.form(f'measure_{kind}_{identifier}_{version}'):
        ch=st.selectbox('측정 챔버',chambers,index=chambers.index(current['chamberId']) if current.get('chamberId') in chambers else 0,disabled=bool(current))
        date=st.text_input('측정일 * · YYYY-MM-DD',value=current.get('measuredAt',today().isoformat()))
        timing_options=['초기 셋업','작업 전','작업 후','정기 점검']
        timing=st.selectbox('측정 시점',timing_options,index=timing_options.index(current.get('timing','작업 후')) if current.get('timing','작업 후') in timing_options else 0)
        title=st.text_input('작업 제목',value=current.get('workTitle',''))
        part_type=st.selectbox('Flatness 종류',['Diffuser','Susceptor'],index=1 if current.get('type')=='Susceptor' else 0) if not spacing else None
        sn=st.text_input('측정 부품 S/N',value=current.get('partSnAtMeasurement',current.get('partSn','')))
        diffuser=st.text_input('Diffuser S/N',value=current.get('diffuserSn',''))
        susceptor=st.text_input('Susceptor S/N',value=current.get('susceptorSn',''))
        choices={r['id']:r for r in logs if r['equipmentId']==equipment}
        if current.get('relatedWorkLogId') and current['relatedWorkLogId'] not in choices:
            choices[current['relatedWorkLogId']]={'workDate':'기존 연결','details':''}
        options=['연결 없음']+list(choices)
        related=st.selectbox('관련 작업 이력',options,index=options.index(current.get('relatedWorkLogId')) if current.get('relatedWorkLogId') in options else 0,format_func=lambda x:x if x=='연결 없음' else f"{x} · {choices[x]['workDate']}")
        st.caption('단위 mils · 빈칸은 미측정으로 유지합니다. 0은 실제 측정값입니다.')
        values=current.get('values',[None]*9) if spacing else current.get('grid',[[None]*7 for _ in range(5)])
        df=pd.DataFrame([values],columns=[f'P{i}' for i in range(1,10)]) if spacing else pd.DataFrame(values,columns=[f'C{i}' for i in range(1,8)])
        df=df.astype(float)
        editor=st.data_editor(df,num_rows='fixed',use_container_width=True,key=f'grid_{kind}_{identifier}_{version}')
        notes=st.text_area('비고',value=current.get('notes',''))
        actor=st.text_input('등록·변경자 *',max_chars=200)
        if st.form_submit_button('측정 기록 저장'):
            try:
                def number(v):return None if pd.isna(v) else float(v)
                grid=[[number(v) for v in row] for row in editor.to_numpy().tolist()]
                item={**store.snapshot_record(current),'id':current.get('id') or 'MEASURE-'+uuid4().hex,'equipmentId':equipment,'chamberId':ch,'measuredAt':date,'timing':timing,'workTitle':title,'diffuserSn':diffuser,'susceptorSn':susceptor,'relatedWorkLogId':None if related=='연결 없음' else related,'unit':'mils','notes':notes,'gaugeTool':'MCT-2009LT' if spacing else 'Laser-L730'}
                if related!='연결 없음' and choices[related].get('chamberId') not in [None,ch]:raise ValueError('관련 작업 이력의 챔버가 다릅니다.')
                if spacing:item.update(values=grid[0],partSnAtMeasurement=sn)
                else:item.update(grid=grid,type=part_type,partSn=sn,rows=5,cols=7,maxMinSpan=store.flatness_span(grid))
                store.save_record(path,kind,item,actor,version)
                st.session_state['hw_saved']='측정 기록을 저장했습니다.';st.rerun()
            except Exception as exc:st.error(f'저장 실패: {exc}')


def measurement_view(path,kind,equipment,chamber,chambers,all_logs):
    spacing=kind=='spacingMeasurements'
    query=st.text_input('측정 기록 검색',key=f'search_{kind}')
    rows=filter_rows(store.records(path,kind),equipment,chamber,query)
    with st.expander('＋ 새 측정 등록'):
        measurement_form(path,kind,equipment,chambers,all_logs)
    if not rows:st.info('해당 조건의 측정 기록이 없습니다.');return
    indexed={r['id']:r for r in rows}
    selected=st.selectbox('측정 기록 선택',list(indexed),format_func=lambda x:f"{indexed[x]['measuredAt']} · {indexed[x]['chamberId']} · {indexed[x].get('workTitle','')} · {x}")
    r=indexed[selected]
    st.write('측정기:',r.get('gaugeTool',''),' / 단위:',r.get('unit',''))
    st.caption(f"S/N: {r.get('partSnAtMeasurement',r.get('partSn',''))} · {r.get('timing','')} · {r.get('notes','')}")
    if r.get('isAmbiguous'):st.warning(r.get('ambiguityReason') or '원본에서 검토 대상으로 표시된 측정입니다. 값을 자동 보정하지 않았습니다.')
    source=r.get('source',{})
    if source:st.caption(f"원문 출처: {source.get('fileName','')} / {source.get('sheetName','')} / {source.get('cellRange','')}")
    if spacing:
        layout=[[r['values'][point-1] for point in row] for row in store.POINT_LAYOUT]
        labels=[[f'P{point}: '+('미측정' if r['values'][point-1] is None else str(r['values'][point-1])) for point in row] for row in store.POINT_LAYOUT]
        st.caption('실제 배치: ①⑥② / ⑨⑤⑦ / ④⑧③')
        st.dataframe(pd.DataFrame(labels),hide_index=True,use_container_width=True)
        table([{'차이':k,'측정값(mils)':v} for k,v in store.spacing_deltas(r['values']).items()])
        grid=layout
    else:
        grid=r['grid']
        st.dataframe(pd.DataFrame(grid,columns=[f'C{i}' for i in range(1,8)]),use_container_width=True)
        st.metric('Max − Min (측정된 위치 기준)',text(store.flatness_span(grid))+' mils')
        if r.get('maxMinSpan') is not None and r['maxMinSpan']!=store.flatness_span(grid):st.info('백업에 저장된 Max−Min과 현재 측정값 계산이 다릅니다. 원본값을 자동 변경하지 않았습니다.')
    fig=go.Figure(go.Heatmap(z=grid,colorscale='RdBu',connectgaps=False,colorbar={'title':'mils'},hoverongaps=False))
    fig.update_layout(title='측정 분포 · 빈 위치는 미측정',height=340,yaxis={'autorange':'reversed'})
    st.plotly_chart(fig,use_container_width=True)
    if not spacing:
        surface=go.Figure(go.Surface(z=grid,colorscale='RdBu',connectgaps=False))
        surface.update_layout(title='Flatness 3D · 보간 없이 표시',height=420,scene={'zaxis_title':'mils'})
        st.plotly_chart(surface,use_container_width=True)
    with st.expander('측정 기록 수정'):
        measurement_form(path,kind,equipment,chambers,all_logs,r)
    with st.expander('이 측정의 변경 이력'):show_audit(path,r['id'])
    export=pd.DataFrame([{'ID':row['id'],'설비':row['equipmentId'],'챔버':row['chamberId'],'측정일':row['measuredAt'],'종류':'Spacing' if spacing else row['type'],'측정값':json.dumps(row['values'] if spacing else row['grid']),'비고':row.get('notes','')} for row in rows])
    export_buttons(export,'hw_measure_'+kind)


def export_buttons(df,name):
    a,b=st.columns(2)
    a.download_button('CSV 다운로드',safe_export(df).to_csv(index=False).encode('utf-8-sig'),name+'.csv','text/csv',key=name+'_csv')
    buf=BytesIO()
    with pd.ExcelWriter(buf,engine='openpyxl') as w:safe_export(df).to_excel(w,index=False,sheet_name='조회 결과')
    b.download_button('Excel 다운로드',buf.getvalue(),name+'.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',key=name+'_xlsx')


def full_backup(data_dir):
    buf=BytesIO()
    with tempfile.TemporaryDirectory(dir=data_dir) as tmp:
        with ZipFile(buf,'w',ZIP_DEFLATED) as z:
            for name in ['pending.sqlite3','hw_history.sqlite3']:
                source=data_dir/name
                if source.exists():
                    target=Path(tmp)/name
                    conn=sqlite3.connect(f'{source.resolve().as_uri()}?mode=ro',uri=True)
                    dest=sqlite3.connect(target)
                    try:conn.backup(dest)
                    finally:conn.close();dest.close()
                    z.write(target,'data/'+name)
            for name in ['default.xlsx','source.xlsx']:
                if (data_dir/name).exists():z.write(data_dir/name,'data/'+name)
            z.writestr('RESTORE.txt','앱 종료 후 data 폴더를 먼저 백업하고 이 ZIP의 data 폴더를 복사하세요. 코드와 가상환경은 별도 설치가 필요합니다. DB와 Excel은 같은 백업 묶음을 사용하세요.')
    return buf.getvalue()


def data_management(path,data_dir):
    st.subheader('데이터 가져오기 · 백업')
    st.caption('JSON은 가져오기 전에 검증합니다. 동일 ID가 이미 있으면 기존 기록을 보존하고 건너뜁니다. 이 화면은 외부 서버에 접속하지 않습니다.')
    upload=st.file_uploader('H/W JSON 백업 업로드',type=['json'],key='hw_import')
    if upload:
        try:
            current={k:store.records(path,k) for k in store.KINDS}
            plan=store.parse_import(upload.getvalue(),current)
            table([{'종류':store.KINDS[k],'가져올 유효 항목':len(rows),'기존 ID 중복':sum(r['id'] in {e['id'] for e in current[k]} for r in rows)} for k,rows in plan['records'].items()])
            if plan['mode']=='sample':st.warning('백업의 모드가 sample입니다. 실제 원본과 대조한 데이터인지 검토해주세요. 자동으로 실제 데이터라고 확정하지 않습니다.')
            if not plan['native']:st.info('AI Studio 백업의 독립된 과거 수정·삭제 이력 목록은 포함되어 있지 않습니다. 각 항목의 원문 audit 필드는 보존됩니다.')
            if plan['errors']:
                st.error(f'가져올 수 없는 항목 {len(plan["errors"])}건');table(plan['errors'])
            if plan['warnings']:
                with st.expander(f'원본 검토 및 첨부 경로 안내 {len(plan["warnings"])}건'):table(plan['warnings'])
            actor=st.text_input('가져오기 담당자',key='hw_import_actor')
            approved=st.checkbox('데이터 출처와 미리보기를 검토했습니다.',key='hw_import_reviewed')
            partial=st.checkbox('오류 항목은 제외하고 유효 항목만 가져옵니다.',key='hw_import_partial') if plan['errors'] else False
            if st.button('검토한 데이터 가져오기',disabled=not approved):
                result=store.import_backup(path,upload.getvalue(),actor,partial)
                st.success(f"새로 가져옴 {result['added']}건 / 기존 ID 보존 {result['skipped']}건 / 오류 제외 {result['errors']}건")
                st.caption('위쪽 메뉴에서 설비 현황이나 작업 이력으로 이동해 확인하세요.')
        except Exception as exc:st.error(f'가져오기 실패: {exc}')
    st.divider()
    st.download_button('H/W 전체 백업 JSON · 첨부·변경 이력 포함',store.backup_bytes(path),'HW_Full_Backup_'+today().isoformat()+'.json','application/json')
    st.caption('H/W 백업 JSON을 위 입력창에 올리면 비어 있는 저장소로 복원할 수 있습니다. 기존 ID는 덮어쓰지 않습니다.')
    if st.button('Pending·REV·H/W 통합 백업 ZIP 준비'):
        st.session_state['hw_full_backup']=full_backup(data_dir)
        st.session_state['hw_full_backup_time']=datetime.now(ZoneInfo('Asia/Seoul')).strftime('%Y-%m-%d %H:%M:%S KST')
    if st.session_state.get('hw_full_backup'):
        st.caption('백업 생성 시각: '+st.session_state['hw_full_backup_time']+' · 이후 변경사항은 준비 버튼을 다시 눌러 반영하세요.')
        st.download_button('통합 백업 ZIP 다운로드',st.session_state['hw_full_backup'],'Pending_HW_Backup_'+today().isoformat()+'.zip','application/zip')
    st.caption('통합 ZIP 복원: 앱을 종료하고 기존 data 폴더를 백업한 뒤 ZIP 안의 data 폴더를 복사합니다. 서로 다른 시각에 만든 DB와 Excel을 섞지 마세요. Temp의 파일은 정리될 수 있으므로 회사에서 허용한 위치에 백업하세요.')
    with st.expander('H/W 전체 변경 이력'):show_audit(path)


def render_hw(data_dir,context=None):
    path=data_dir/'hw_history.sqlite3'
    st.header('설비 H/W 이력관리')
    st.caption('로컬 저장 · 기존 Pending·REV 저장소 보존 · Firebase 자동 접속 없음')
    conn=store.connection(path)
    try:sample_import=bool(conn.execute("SELECT 1 FROM imports WHERE mode='sample'").fetchone())
    finally:conn.close()
    if sample_import:st.warning('가져온 데이터에 sample 모드로 내보낸 백업이 포함되어 있습니다. 실제 원본과 대조 전에는 검증된 운영 데이터로 간주하지 마세요.')
    if st.session_state.pop('hw_saved',None):st.success('저장했습니다. 변경 이력을 기록했습니다.')
    section=st.radio('H/W 메뉴',['설비 현황','작업 이력','부품 추적','Spacing','Flatness','데이터 관리'],horizontal=True,key='hw_section')
    if section=='데이터 관리':data_management(path,data_dir);return
    equipments=store.records(path,'equipments')
    with st.expander('＋ 설비 등록'):
        with st.form('new_equipment'):
            identifier=st.text_input('설비 ID * · 예: A4CVD15I')
            name=st.text_input('설비 이름 *')
            customer=st.text_input('고객사')
            chamber_names=st.text_input('챔버 ID · 쉼표로 구분',value='Chamber A, Chamber B, Chamber C, Chamber D, Chamber E')
            actor=st.text_input('등록자 *')
            if st.form_submit_button('설비 저장'):
                try:
                    if not name.strip():raise ValueError('설비 이름을 입력해주세요.')
                    item={'id':identifier.strip(),'name':name.strip(),'customer':customer,'chambers':[{'chamberId':c.strip(),'name':c.strip(),'initialParts':{},'installedParts':{}} for c in chamber_names.split(',') if c.strip()]}
                    store.save_record(path,'equipments',item,actor)
                    st.session_state['hw_saved']=True;st.rerun()
                except Exception as exc:st.error(str(exc))
    if not equipments:
        st.info('아직 H/W 데이터가 없습니다. 「데이터 관리」에서 받은 JSON을 검토 후 가져오거나 설비부터 등록해주세요.');return
    lookup={r['id']:r for r in equipments}
    prefill=st.session_state.get('pending_hw_prefill',{})
    preferred=prefill.get('equipmentId')
    if preferred in lookup and 'hw_equipment' not in st.session_state:st.session_state['hw_equipment']=preferred
    equipment=st.selectbox('H/W 설비',list(lookup),format_func=lambda x:f'{x} · {lookup[x].get("name","")}',key='hw_equipment')
    chambers=[c['chamberId'] for c in lookup[equipment]['chambers']]
    chamber=st.selectbox('H/W 챔버',['전체']+chambers,key=f'hw_chamber_{equipment}')
    logs=store.records(path,'workLogs')
    if section=='설비 현황':
        for ch in chambers if chamber=='전체' else [chamber]:
            st.subheader(ch)
            parts=store.installed_parts(lookup[equipment],ch,logs)
            table([{'부품':p['partType'],'S/N':p.get('sn',''),'장착일':p.get('installedDate',''),'상태':p.get('status',''),'산출 근거':p.get('basis',''),'관련 작업':p.get('lastWorkLogId','')} for p in parts])
        st.caption('초기 장착 기준에 시간순 부품 교체 이력을 적용한 결과입니다. 검토 표시가 있는 작업은 자동 반영하지 않습니다. 기록 불일치는 원본과 대조해주세요.')
        monthly=pd.DataFrame([{'월':r['workDate'][:7],'작업 유형':r['workType']} for r in logs if r['equipmentId']==equipment and (chamber=='전체' or r['chamberId']==chamber)])
        if not monthly.empty:
            st.subheader('월별 작업 건수');st.bar_chart(monthly.groupby('월').size())
        with st.expander('설비 이름·고객사 수정'):
            eq=lookup[equipment]
            with st.form(f'equipment_edit_{equipment}_{eq["_version"]}'):
                new_name=st.text_input('설비 이름',value=eq.get('name',''))
                new_customer=st.text_input('고객사',value=eq.get('customer',''))
                operator=st.text_input('변경자 *')
                if st.form_submit_button('설비 정보 수정 저장'):
                    try:
                        store.save_record(path,'equipments',{**eq,'name':new_name,'customer':new_customer},operator,eq['_version'])
                        st.session_state['hw_saved']=True;st.rerun()
                    except Exception as exc:st.error(str(exc))
    elif section=='작업 이력':
        query=st.text_input('작업 이력 검색 · 부품/SN/내용/담당자',key='hw_work_search')
        with st.expander('＋ 작업 이력 등록',expanded=bool(st.session_state.get('pending_hw_prefill'))):work_form(path,equipment,chambers,context)
        rows=filter_rows(logs,equipment,chamber,query)
        if not rows:st.info('해당 조건의 작업 이력이 없습니다.');return
        df=pd.DataFrame([{'ID':r['id'],'설비':r['equipmentId'],'챔버':r['chamberId'],'작업일':r['workDate'],'작업':r['workType'],'부품':r.get('targetPart',''),'교체 전 S/N':r.get('beforeSn',''),'교체 후 S/N':r.get('afterSn',''),'내용':r.get('details',''),'작업자':r.get('worker',''),'결과':r.get('issueStatus','')} for r in rows])
        st.dataframe(df,hide_index=True,use_container_width=True);export_buttons(df,'hw_work_logs')
        indexed={r['id']:r for r in rows}
        selected=st.selectbox('작업 상세 선택',list(indexed),format_func=lambda x:f"{indexed[x]['workDate']} · {indexed[x].get('targetPart','')} · {x}")
        item=indexed[selected]
        st.write(item.get('details',''));st.caption('작업 사유: '+item.get('reason',''))
        if item.get('isAmbiguous'):st.warning(item.get('ambiguityReason') or '원본 검토 표시가 있는 기록입니다.')
        if item.get('source'):st.json(item['source'])
        show_pending_link(item.get('pendingLink'),context)
        attachments(path,item)
        with st.expander('작업 이력 수정'):work_form(path,equipment,chambers,context,item)
        with st.expander('이 작업의 변경 이력'):show_audit(path,item['id'])
    elif section=='부품 추적':
        st.caption('부품 이동 확인을 위해 전체 설비의 동일 S/N 기록을 조회합니다.')
        sn=st.text_input('조회할 부품 S/N · 정확히 일치하는 번호',key='hw_trace_sn')
        if sn:
            traced=store.trace_sn(equipments,logs,sn.strip())
            table(traced)
            if traced:export_buttons(pd.DataFrame(traced),'hw_part_trace')
        else:st.info('부품 S/N을 입력하면 설비·챔버 간 기록을 확인할 수 있습니다.')
    else:measurement_view(path,'spacingMeasurements' if section=='Spacing' else 'flatnessMeasurements',equipment,chamber,chambers,logs)
