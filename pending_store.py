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
    if values.get('상태') not in ['완료','미완료','확인 필요']: raise ValueError('상태를 선택해주세요.')
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
    if changes.get('상태',current['상태']) not in ['완료','미완료','확인 필요']: raise ValueError('상태를 확인해주세요.')
    conn=edit_connection(path)
    try:
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            row=conn.execute('SELECT payload FROM overrides WHERE source=? AND id=?',(source,current['ID'])).fetchone()
            previous=json.loads(row[0]) if row else {}
            for field,value in previous.items():
                if clean(current[field])!=value:
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
        df['변경 시각']=pd.to_datetime(df['변경 시각'],utc=True).dt.tz_convert('Asia/Seoul').dt.strftime('%Y-%m-%d %H:%M:%S KST')
    return df
