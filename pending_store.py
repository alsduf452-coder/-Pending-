"""로컬 기본 Excel 및 추가 항목 저장. 원본 Excel에는 쓰지 않습니다."""
from pathlib import Path
import hashlib
import json
import os
import sqlite3
import tempfile
from uuid import uuid4
import pandas as pd
from pending_data import COLUMNS, MAIN, clean, load_pending


def set_default(content, path):
    load_pending(content)  # 지원하는 파일인지 확인한 뒤에만 보관합니다.
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
        temp = Path(f.name)
        f.write(content)
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def source_key(content):
    return hashlib.sha256(content).hexdigest()


def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15)
    conn.execute('CREATE TABLE IF NOT EXISTS items (id TEXT PRIMARY KEY, source TEXT NOT NULL, payload TEXT NOT NULL)')
    return conn


def add_item(path, source, values):
    values = {k: clean(v) for k,v in values.items()}
    if not values.get('내용'): raise ValueError('내용을 입력해주세요.')
    if values.get('분야') not in MAIN: raise ValueError('분야를 선택해주세요.')
    if values.get('설비') not in ['CVD15I','CVD45I']: raise ValueError('설비를 선택해주세요.')
    if values.get('상태') not in ['완료','미완료']: raise ValueError('상태를 선택해주세요.')
    r = dict.fromkeys(COLUMNS, '')
    r.update({k:v for k,v in values.items() if k in COLUMNS})
    identifier = 'ADD-' + uuid4().hex
    r.update({'ID':identifier,'번호':identifier[:12], '범위':'주요 분야','시트':'화면 등록','원본 행':'','원문 상태':values['상태']})
    r['원문 전체'] = '\n'.join(f'{k}: {v}' for k,v in r.items() if v)
    conn = connect(path)
    try:
        with conn:
            conn.execute('INSERT INTO items VALUES (?, ?, ?)',(identifier,source,json.dumps(r,ensure_ascii=False)))
    finally:
        conn.close()
    return identifier


def read_items(path, source):
    conn = connect(path)
    try:
        rows = conn.execute('SELECT payload FROM items WHERE source=? ORDER BY rowid',(source,)).fetchall()
    finally:
        conn.close()
    return pd.DataFrame([json.loads(row[0]) for row in rows],columns=COLUMNS)

EDITABLE = ['내용','담당자','Unit','발생일','원인','진행 사항','목표일','조치내용','완료일','조치자','45호기 적용 여부','상태']


def edit_connection(path):
    conn=connect(path)
    conn.execute('CREATE TABLE IF NOT EXISTS overrides (source TEXT, id TEXT, payload TEXT NOT NULL, PRIMARY KEY(source,id))')
    conn.execute('CREATE TABLE IF NOT EXISTS history (seq INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, id TEXT NOT NULL, timestamp TEXT NOT NULL, actor TEXT NOT NULL, field TEXT NOT NULL, before_value TEXT NOT NULL, after_value TEXT NOT NULL)')
    conn.commit()
    return conn


def apply_edits(path, source, df):
    conn=edit_connection(path)
    try:
        changes={r[0]:json.loads(r[1]) for r in conn.execute('SELECT id,payload FROM overrides WHERE source=?',(source,))}
    finally: conn.close()
    result=df.copy()
    for index,row in result.iterrows():
        for field,value in changes.get(row['ID'],{}).items():
            result.at[index,field]=value
    return result


def update_item(path, source, current, values, actor):
    from datetime import datetime, timezone
    actor=clean(actor)
    if not actor: raise ValueError('변경자를 입력해주세요.')
    changes={k:clean(v) for k,v in values.items() if k in EDITABLE}
    if '내용' in changes and not changes['내용']: raise ValueError('내용은 비울 수 없습니다.')
    if changes.get('상태',current['상태']) not in ['완료','미완료']: raise ValueError('상태를 확인해주세요.')
    conn=edit_connection(path)
    try:
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            row=conn.execute('SELECT payload FROM overrides WHERE source=? AND id=?',(source,current['ID'])).fetchone()
            previous=json.loads(row[0]) if row else {}
            for field,value in previous.items():
                stored_value=('완료' if value=='완료' else '미완료') if field=='상태' else value
                if clean(current[field])!=stored_value:
                    raise ValueError('다른 화면에서 항목이 변경됐습니다. 새로고침 후 다시 수정해주세요.')
            changed={k:v for k,v in changes.items() if v!=clean(current[k])}
            if not changed: return 0
            now=datetime.now(timezone.utc).isoformat()
            for field,value in changed.items():
                conn.execute('INSERT INTO history (source,id,timestamp,actor,field,before_value,after_value) VALUES (?,?,?,?,?,?,?)',(source,current['ID'],now,actor,field,clean(current[field]),value))
            previous.update(changed)
            conn.execute('INSERT INTO overrides VALUES (?,?,?) ON CONFLICT(source,id) DO UPDATE SET payload=excluded.payload',(source,current['ID'],json.dumps(previous,ensure_ascii=False)))
            return len(changed)
    finally: conn.close()


def read_history(path, source, identifier=None):
    conn=edit_connection(path)
    try:
        sql='SELECT timestamp,actor,id,field,before_value,after_value FROM history WHERE source=?'
        params=[source]
        if identifier is not None: sql+=' AND id=?';params.append(identifier)
        rows=conn.execute(sql+' ORDER BY seq DESC',params).fetchall()
    finally: conn.close()
    df=pd.DataFrame(rows,columns=['변경 시각','변경자','항목 ID','변경 필드','변경 전','변경 후'])
    if not df.empty:
        for idx,row in df.iterrows():
            if row['변경 필드']=='상태':
                for value_field in ['변경 전','변경 후']:
                    if row[value_field]: df.at[idx,value_field]='완료' if row[value_field]=='완료' else '미완료'
        df['변경 시각']=pd.to_datetime(df['변경 시각'],utc=True).dt.tz_convert('Asia/Seoul').dt.strftime('%Y-%m-%d %H:%M:%S KST')
    return df

# REV 등록·수정은 원본 Excel 및 Pending 변경 이력과 분리해 보관합니다.
REV_FIELDS = ['Rev No.','구분','주요 변경내용','변경일자','작성자','변경점 Key Word / 비고']
REV_COLUMNS = REV_FIELDS + ['원본 행','출처','ID','버전']


def revision_connection(path):
    conn=connect(path)
    conn.execute('CREATE TABLE IF NOT EXISTS revisions (source TEXT NOT NULL, id TEXT NOT NULL, number TEXT NOT NULL, payload TEXT NOT NULL, version INTEGER NOT NULL, PRIMARY KEY(source,id), UNIQUE(source,number))')
    conn.execute('CREATE TABLE IF NOT EXISTS revision_history (seq INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, id TEXT NOT NULL, timestamp TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, field TEXT NOT NULL, before_value TEXT NOT NULL, after_value TEXT NOT NULL)')
    conn.commit()
    return conn


def _revision_rows(conn, source, original):
    rows={}
    for _,r in original.iterrows():
        item={field:clean(r[field]) for field in REV_FIELDS}
        identifier=f"REV-XLSX:{r['원본 행']}"
        item.update({'원본 행':clean(r['원본 행']),'출처':'Excel 원본','ID':identifier,'버전':0})
        rows[identifier]=item
    for identifier,payload,version in conn.execute('SELECT id,payload,version FROM revisions WHERE source=? ORDER BY rowid',(source,)):
        rows[identifier]={**json.loads(payload),'ID':identifier,'버전':version}
    return pd.DataFrame(list(rows.values()),columns=REV_COLUMNS)


def read_revisions(path, source, original):
    conn=revision_connection(path)
    try: return _revision_rows(conn,source,original)
    finally: conn.close()


def _rev_number(value):
    import re
    text=clean(value)
    if not re.fullmatch(r'[0-9]{1,6}',text):
        raise ValueError('REV 번호는 0~999999 사이의 숫자로 입력해주세요. 예: 018')
    return str(int(text))


def suggest_revision(revisions):
    numbers=[]
    for value in revisions['Rev No.']:
        try: numbers.append(int(value))
        except (ValueError,TypeError): pass
    return f'{max(numbers,default=-1)+1:03d}'


def save_revision(path, source, original, values, actor, current=None):
    from datetime import datetime, timezone
    actor=clean(actor)
    if not actor: raise ValueError('등록·변경자를 입력해주세요.')
    values={field:clean(values.get(field)) for field in REV_FIELDS}
    number=_rev_number(values['Rev No.'])
    for field in ['주요 변경내용','변경일자','작성자']:
        if not values[field]: raise ValueError(f'{field}을(를) 입력해주세요.')
    conn=revision_connection(path)
    try:
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            live=_revision_rows(conn,source,original)
            identifier=current['ID'] if current is not None else 'REV-ADD:'+uuid4().hex
            previous=None
            if current is not None:
                found=live[live['ID']==identifier]
                if found.empty: raise ValueError('REV를 찾지 못했습니다. 새로고침 후 다시 시도해주세요.')
                previous=found.iloc[0].to_dict()
                if int(previous['버전'])!=int(current['버전']):
                    raise ValueError('다른 화면에서 REV가 변경됐습니다. 새로고침 후 다시 수정해주세요.')
            for _,other in live.iterrows():
                if other['ID']!=identifier and _rev_number(other['Rev No.'])==number:
                    raise ValueError('이미 존재하는 REV 번호입니다. 다른 번호를 입력해주세요.')
            changed={field:value for field,value in values.items() if previous is None or value!=clean(previous[field])}
            if not changed: return 0
            row={**values,'원본 행':previous['원본 행'] if previous else '',
                 '출처':'Excel 원본 · 앱 수정' if previous and previous['원본 행'] else '화면 등록'}
            version=int(previous['버전'])+1 if previous else 1
            conn.execute('INSERT INTO revisions VALUES (?,?,?,?,?) ON CONFLICT(source,id) DO UPDATE SET number=excluded.number,payload=excluded.payload,version=excluded.version',(source,identifier,number,json.dumps(row,ensure_ascii=False),version))
            now=datetime.now(timezone.utc).isoformat()
            for field,value in changed.items():
                conn.execute('INSERT INTO revision_history (source,id,timestamp,actor,action,field,before_value,after_value) VALUES (?,?,?,?,?,?,?,?)',(source,identifier,now,actor,'수정' if previous else '등록',field,clean(previous[field]) if previous else '',value))
            return len(changed)
    finally: conn.close()


def read_revision_history(path, source, identifier=None):
    conn=revision_connection(path)
    try:
        sql='SELECT timestamp,actor,action,id,field,before_value,after_value FROM revision_history WHERE source=?'
        params=[source]
        if identifier is not None: sql+=' AND id=?';params.append(identifier)
        rows=conn.execute(sql+' ORDER BY seq DESC',params).fetchall()
    finally: conn.close()
    result=pd.DataFrame(rows,columns=['변경 시각','등록·변경자','작업','REV ID','변경 필드','변경 전','변경 후'])
    if not result.empty:
        result['변경 시각']=pd.to_datetime(result['변경 시각'],utc=True).dt.tz_convert('Asia/Seoul').dt.strftime('%Y-%m-%d %H:%M:%S KST')
    return result
