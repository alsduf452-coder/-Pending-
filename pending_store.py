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
