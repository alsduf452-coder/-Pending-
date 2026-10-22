"""로컬 H/W 데이터, 검증, 변경 이력. 외부 서비스에 접속하지 않습니다."""
import base64
import hashlib
import json
import math
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

KINDS={'equipments':'설비','workLogs':'작업 이력','spacingMeasurements':'Spacing','flatnessMeasurements':'Flatness','spacingStandards':'측정 위치'}
PARTS=['Diffuser','Backing Plate','Susceptor','Shadow Frame','RFG','Matcher','RPSC Reactor','MF Generator','기타 부품']
POINT_LAYOUT=[[1,6,2],[9,5,7],[4,8,3]]


def now(): return datetime.now(timezone.utc).isoformat()


def connection(path):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(path,timeout=20)
    conn.row_factory=sqlite3.Row
    conn.executescript('''CREATE TABLE IF NOT EXISTS entities (kind TEXT, id TEXT, payload TEXT NOT NULL, version INTEGER NOT NULL, PRIMARY KEY(kind,id));
    CREATE TABLE IF NOT EXISTS audit (id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, kind TEXT NOT NULL, entity_id TEXT NOT NULL, before_json TEXT, after_json TEXT);
    CREATE TABLE IF NOT EXISTS blobs (id TEXT PRIMARY KEY, name TEXT NOT NULL, mime TEXT NOT NULL, data BLOB NOT NULL);
    CREATE TABLE IF NOT EXISTS imports (digest TEXT PRIMARY KEY, imported_at TEXT NOT NULL, actor TEXT NOT NULL, mode TEXT NOT NULL);''')
    return conn


def records(path,kind,include_deleted=False):
    conn=connection(path)
    try:
        rows=[{**json.loads(r['payload']),'_version':r['version']} for r in conn.execute('SELECT payload,version FROM entities WHERE kind=? ORDER BY rowid',(kind,))]
        return rows if include_deleted else [r for r in rows if not r.get('deletedAt')]
    finally: conn.close()


def snapshot_record(r): return {k:v for k,v in r.items() if not k.startswith('_')}


def good_date(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:[ T].*)?',value): return False
    try: datetime.fromisoformat(value.replace('Z','+00:00'));return True
    except ValueError: return False


def numeric_grid(values,rows,cols=None):
    if not isinstance(values,list) or len(values)!=rows: return False
    flat=values
    if cols is not None:
        if any(not isinstance(row,list) or len(row)!=cols for row in values): return False
        flat=[v for row in values for v in row]
    return all(v is None or (isinstance(v,(float,int)) and not isinstance(v,bool) and math.isfinite(v)) for v in flat)


def validate_record(kind,item,equipments,work_ids,allow_incomplete=False):
    if not isinstance(item,dict): return '항목이 객체가 아닙니다.'
    if not isinstance(item.get('id'),str) or not item['id'].strip() or len(item['id'])>200: return '고유 ID가 없거나 올바르지 않습니다.'
    if kind=='equipments':
        chambers=item.get('chambers')
        if not isinstance(chambers,list) or not chambers: return '챔버 정보가 없습니다.'
        ids=[c.get('chamberId') for c in chambers if isinstance(c,dict)]
        if len(ids)!=len(chambers) or any(not isinstance(x,str) or not x for x in ids) or len(ids)!=len(set(ids)): return '챔버 ID가 없거나 중복됩니다.'
        for c in chambers:
            if any(not isinstance(c.get(k,{}),dict) for k in ['installedParts','initialParts']): return '장착 부품 정보 형식이 잘못됐습니다.'
        return ''
    if kind=='spacingStandards':
        return '' if isinstance(item.get('pointIndex'),int) and 1<=item['pointIndex']<=9 and isinstance(item.get('label'),str) else '측정 위치 정보가 잘못됐습니다.'
    equipment=equipments.get(item.get('equipmentId'))
    if equipment is None: return '연결할 설비가 없습니다.'
    if item.get('chamberId') not in [c['chamberId'] for c in equipment['chambers']]: return '연결할 챔버가 없습니다.'
    if kind=='workLogs':
        if not good_date(item.get('workDate')): return '작업일은 YYYY-MM-DD로 입력해주세요.'
        if not allow_incomplete and (not str(item.get('details','')).strip() or not str(item.get('workType','')).strip()): return '작업 유형과 내용이 필요합니다.'
        order=item.get('workOrder',1)
        if not isinstance(order,int) or isinstance(order,bool) or order<1:return '작업 순서는 1 이상의 정수여야 합니다.'
        if item.get('attachments') is not None and not isinstance(item.get('attachments'),list): return '첨부파일 정보가 잘못됐습니다.'
    else:
        if not good_date(item.get('measuredAt')): return '측정일은 YYYY-MM-DD로 입력해주세요.'
        if item.get('relatedWorkLogId') and item['relatedWorkLogId'] not in work_ids: return '연결할 작업 이력이 없습니다.'
        if item.get('relatedWorkLogId') and isinstance(work_ids,dict):
            related=work_ids[item['relatedWorkLogId']]
            if related.get('equipmentId')!=item.get('equipmentId') or related.get('chamberId')!=item.get('chamberId'): return '관련 작업의 설비·챔버가 다릅니다.'
        if item.get('unit')!='mils': return '측정 단위는 mils여야 합니다.'
        if kind=='spacingMeasurements' and not numeric_grid(item.get('values'),9): return 'Spacing은 숫자 또는 빈값 9개가 필요합니다.'
        if kind=='flatnessMeasurements':
            if item.get('type') not in ['Diffuser','Susceptor']: return 'Flatness 부품 종류가 잘못됐습니다.'
            if not numeric_grid(item.get('grid'),5,7): return 'Flatness는 숫자 또는 빈값 5×7개가 필요합니다.'
    return ''


def parse_import(content,existing=None):
    if len(content)>30*1024*1024: raise ValueError('백업은 30MB 이하여야 합니다.')
    data=json.loads(content.decode('utf-8-sig'))
    if not isinstance(data,dict): raise ValueError('JSON 최상위 형식이 잘못됐습니다.')
    native=data.get('format')=='pending-hw-backup-v1'
    source=data.get('records') if native else data
    if not isinstance(source,dict) or not any(k in source for k in KINDS): raise ValueError('H/W 백업 데이터를 찾지 못했습니다.')
    existing=existing or {}; normalized={};errors=[];warnings=[];seen={}
    for kind in KINDS:
        values=source.get(kind,[])
        if not isinstance(values,list) or len(values)>20000: raise ValueError(f'{KINDS[kind]} 목록 형식을 확인해주세요.')
        normalized[kind]=[];seen[kind]=set()
        for raw in values:
            if not isinstance(raw,dict): errors.append({'종류':KINDS[kind],'ID':'','사유':'객체가 아닌 항목'});continue
            r=snapshot_record(raw.copy())
            if kind=='spacingStandards': r.setdefault('id',f"POINT-{r.get('pointIndex','')}")
            if kind=='flatnessMeasurements' and 'grid' not in r:
                if isinstance(r.get('gridRows'),list): r['grid']=[x.get('cells',[]) for x in r['gridRows']]
                elif isinstance(r.get('gridJson'),str):
                    try:r['grid']=json.loads(r['gridJson'])
                    except (ValueError,TypeError):pass
            identifier=r.get('id')
            if not isinstance(identifier,str) or identifier in seen[kind]:
                errors.append({'종류':KINDS[kind],'ID':str(identifier),'사유':'ID가 없거나 백업 내부에서 중복됨'});continue
            seen[kind].add(identifier);normalized[kind].append(r)
    valid={k:[] for k in KINDS}
    equipment_map={r['id']:r for r in existing.get('equipments',[])}
    for r in normalized['equipments']:
        reason=validate_record('equipments',r,{},set())
        if reason: errors.append({'종류':'설비','ID':r['id'],'사유':reason})
        else:
            valid['equipments'].append(r)
            equipment_map.setdefault(r['id'],r)
    work_ids={r['id']:r for r in existing.get('workLogs',[])}
    for kind in ['workLogs','spacingMeasurements','flatnessMeasurements','spacingStandards']:
        for r in normalized[kind]:
            reason=validate_record(kind,r,equipment_map,work_ids,allow_incomplete=True)
            if reason: errors.append({'종류':KINDS[kind],'ID':r['id'],'사유':reason});continue
            valid[kind].append(r)
            if kind=='workLogs':
                work_ids[r['id']]=r
                if not str(r.get('details','')).strip() or not str(r.get('workType','')).strip():
                    warnings.append({'종류':'작업 이력','ID':r['id'],'사유':'원본의 작업 유형/상세내용이 비어 있음: 빈값 그대로 보존'})
            if r.get('isAmbiguous'): warnings.append({'종류':KINDS[kind],'ID':r['id'],'사유':r.get('ambiguityReason') or '원본에서 검토 대상으로 표시된 기록'})
            if any(isinstance(a,dict) and a.get('url') and not a.get('blobId') for a in (r.get('attachments') or [])):
                warnings.append({'종류':KINDS[kind],'ID':r['id'],'사유':'첨부파일 경로만 포함됨: 실제 파일은 별도 필요'})
    return {'data':data,'records':valid,'errors':errors,'warnings':warnings,'mode':data.get('mode','미기재'),'digest':hashlib.sha256(content).hexdigest(),'native':native}


def import_backup(path,content,actor,allow_partial=False):
    if not str(actor).strip(): raise ValueError('가져오기 담당자를 입력해주세요.')
    conn=connection(path)
    try:
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            existing={k:[] for k in KINDS}
            for row in conn.execute('SELECT kind,payload FROM entities'):
                existing[row['kind']].append(json.loads(row['payload']))
            plan=parse_import(content,existing)
            if plan['errors'] and not allow_partial: raise ValueError('오류 항목이 있습니다. 검토 후 제외 가져오기를 선택해주세요.')
            added=0;skipped=0
            for kind,items in plan['records'].items():
                for item in items:
                    old=conn.execute('SELECT 1 FROM entities WHERE kind=? AND id=?',(kind,item['id'])).fetchone()
                    if old: skipped+=1;continue
                    conn.execute('INSERT INTO entities VALUES (?,?,?,1)',(kind,item['id'],json.dumps(item,ensure_ascii=False,allow_nan=False)))
                    conn.execute('INSERT INTO audit VALUES (?,?,?,?,?,?,?,?)',(uuid4().hex,now(),actor,'IMPORT',kind,item['id'],'',json.dumps(item,ensure_ascii=False)))
                    added+=1
            if plan['native']:
                for blob in plan['data'].get('blobs',[]):
                    raw=base64.b64decode(blob['data'],validate=True)
                    if len(raw)>10*1024*1024 or hashlib.sha256(raw).hexdigest()!=blob['id']: raise ValueError('첨부파일 백업 검증에 실패했습니다.')
                    conn.execute('INSERT OR IGNORE INTO blobs VALUES (?,?,?,?)',(blob['id'],blob['name'],blob['mime'],raw))
                for a in plan['data'].get('audit',[]):
                    conn.execute('INSERT OR IGNORE INTO audit VALUES (?,?,?,?,?,?,?,?)',tuple(a[k] for k in ['id','timestamp','actor','action','kind','entity_id','before_json','after_json']))
            conn.execute('INSERT OR IGNORE INTO imports VALUES (?,?,?,?)',(plan['digest'],now(),actor,plan['mode']))
            return {'added':added,'skipped':skipped,'errors':len(plan['errors'])}
    finally:conn.close()


def save_record(path,kind,item,actor,expected_version=None,uploads=None):
    if kind not in KINDS: raise ValueError('지원하지 않는 데이터 종류입니다.')
    if not str(actor).strip(): raise ValueError('작업·변경자를 입력해주세요.')
    item=snapshot_record(item.copy());conn=connection(path)
    try:
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            old=conn.execute('SELECT payload,version FROM entities WHERE kind=? AND id=?',(kind,item.get('id'))).fetchone()
            if old and expected_version!=old['version']: raise ValueError('다른 화면에서 변경됐습니다. 새로고침 후 다시 시도해주세요.')
            if not old and expected_version is not None: raise ValueError('수정할 항목이 없습니다.')
            eq={r['id']:json.loads(r['payload']) for r in conn.execute("SELECT id,payload FROM entities WHERE kind='equipments'")}
            work_ids={r['id']:json.loads(r['payload']) for r in conn.execute("SELECT id,payload FROM entities WHERE kind='workLogs'")}
            reason=validate_record(kind,item,eq,work_ids)
            if reason: raise ValueError(reason)
            if old:
                previous=json.loads(old['payload'])
                if kind!='equipments' and any(previous.get(k)!=item.get(k) for k in ['equipmentId','chamberId']):
                    raise ValueError('기존 기록의 설비·챔버는 변경할 수 없습니다. 별도 기록으로 등록해주세요.')
                if kind=='equipments' and previous.get('chambers')!=item.get('chambers'):
                    if [c['chamberId'] for c in previous['chambers']]!=[c['chamberId'] for c in item['chambers']]: raise ValueError('사용 중인 챔버 ID는 변경할 수 없습니다.')
            for upload in uploads or []:
                raw=upload['data']
                if len(raw)>10*1024*1024: raise ValueError('첨부파일은 개당 10MB 이하여야 합니다.')
                if upload['mime'] not in ['image/png','image/jpeg','application/pdf']: raise ValueError('PNG, JPG, PDF 첨부만 지원합니다.')
                blob_id=hashlib.sha256(raw).hexdigest()
                conn.execute('INSERT OR IGNORE INTO blobs VALUES (?,?,?,?)',(blob_id,upload['name'],upload['mime'],raw))
                if item.get('attachments') is None:item['attachments']=[]
                item['attachments'].append({'blobId':blob_id,'name':upload['name'],'type':upload['mime'],'size':len(raw)})
            if kind=='flatnessMeasurements':
                item['rows']=5;item['cols']=7;item['maxMinSpan']=flatness_span(item['grid'])
                if 'gridRows' in item:item['gridRows']=[{'cells':row} for row in item['grid']]
                if 'gridJson' in item:item['gridJson']=json.dumps(item['grid'],allow_nan=False)
            encoded=json.dumps(item,ensure_ascii=False,allow_nan=False)
            if old and json.loads(old['payload'])==item: return item['id']
            conn.execute('INSERT INTO entities VALUES (?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload,version=excluded.version',(kind,item['id'],encoded,old['version']+1 if old else 1))
            conn.execute('INSERT INTO audit VALUES (?,?,?,?,?,?,?,?)',(uuid4().hex,now(),actor,'UPDATE' if old else 'CREATE',kind,item['id'],old['payload'] if old else '',encoded))
            return item['id']
    finally:conn.close()


def audit_records(path,entity_id=None):
    conn=connection(path)
    try:
        query='SELECT * FROM audit';params=()
        if entity_id:query+=' WHERE entity_id=?';params=(entity_id,)
        return [dict(r) for r in conn.execute(query+' ORDER BY rowid DESC',params)]
    finally:conn.close()


def get_blob(path,identifier):
    conn=connection(path)
    try:
        row=conn.execute('SELECT name,mime,data FROM blobs WHERE id=?',(identifier,)).fetchone()
        return dict(row) if row else None
    finally:conn.close()


def backup_bytes(path):
    conn=connection(path)
    try:
        conn.execute('BEGIN')
        mode='sample' if conn.execute("SELECT 1 FROM imports WHERE mode='sample'").fetchone() else 'local'
        data={'format':'pending-hw-backup-v1','exportDate':now(),'mode':mode,'records':{k:[] for k in KINDS},'audit':[],'blobs':[]}
        for r in conn.execute('SELECT kind,payload FROM entities'): data['records'][r['kind']].append(json.loads(r['payload']))
        data['audit']=[dict(r) for r in conn.execute('SELECT * FROM audit')]
        for r in conn.execute('SELECT * FROM blobs'):
            data['blobs'].append({**dict(r),'data':base64.b64encode(r['data']).decode()})
        return json.dumps(data,ensure_ascii=False,allow_nan=False).encode('utf-8')
    finally:conn.close()


def spacing_deltas(values):
    pairs=[(5,1),(5,2),(5,3),(5,4),(2,4),(1,3)]
    return {f'{a}−{b}':round(values[a-1]-values[b-1],2) if values[a-1] is not None and values[b-1] is not None else None for a,b in pairs}


def flatness_span(grid):
    vals=[v for row in grid for v in row if v is not None]
    return round(max(vals)-min(vals),6) if vals else None


def installed_parts(equipment,chamber_id,work_logs):
    chamber=next(c for c in equipment['chambers'] if c['chamberId']==chamber_id)
    # 초기 기준과 작업 순서로 계산하며 초기 기준이 없으면 저장된 구성임을 명시합니다.
    baseline=chamber.get('initialParts') or chamber.get('installedParts',{})
    parts={key:{**value,'partType':key,'basis':'초기 기준＋작업 이력' if chamber.get('initialParts') else '백업 저장값'} for key,value in baseline.items()}
    logs=sorted([r for r in work_logs if r.get('equipmentId')==equipment['id'] and r.get('chamberId')==chamber_id],key=lambda r:(r.get('workTimestamp') or r.get('workDate',''),r.get('workOrder',0),r['id']))
    for log in logs:
        if log.get('isAmbiguous') or not log.get('afterSn') or log.get('workType') not in ['초기 셋업','부품 교체','교체/PM']:continue
        part=log.get('targetPart')
        if not part:continue
        previous=parts.get(part,{})
        if not chamber.get('initialParts') and previous.get('lastWorkDate') and log['workDate']<=previous['lastWorkDate']:continue
        mismatch=bool(log.get('beforeSn') and previous.get('sn') and log['beforeSn']!=previous['sn'])
        parts[part]={'partType':part,'sn':log['afterSn'],'installedDate':log['workDate'],'lastWorkDate':log['workDate'],'lastWorkLogId':log['id'],'status':'기록 불일치' if mismatch else log.get('issueStatus','미기재'),'basis':'작업 이력 계산'}
    return list(parts.values())


def trace_sn(equipments,logs,sn):
    result=[]
    for equipment in equipments:
        for chamber in equipment['chambers']:
            for part,value in (chamber.get('initialParts') or chamber.get('installedParts',{})).items():
                if value.get('sn')==sn:result.append({'설비':equipment['id'],'챔버':chamber['chamberId'],'날짜':value.get('installedDate',''),'부품':part,'구분':'초기/저장 장착','작업 ID':value.get('lastWorkLogId','')})
    for log in logs:
        for key,label in [('beforeSn','탈거 전 기록'),('afterSn','장착 후 기록')]:
            if log.get(key)==sn:result.append({'설비':log['equipmentId'],'챔버':log['chamberId'],'날짜':log['workDate'],'부품':log.get('targetPart',''),'구분':label,'작업 ID':log['id']})
    return sorted(result,key=lambda r:(r['날짜'],r['작업 ID'],r['구분']))


DATE_COLOR_EXCLUDED={'MF Generator','RPSC Reactor','Matcher','RFG'}


def installation_age(date_value,part_type,today_date):
    from datetime import date
    neutral={'days':None,'label':'색상 제외' if part_type in DATE_COLOR_EXCLUDED else '일자 미기재','style':'background:#e2e8f0;color:#334155;border:1px solid #94a3b8'}
    if part_type in DATE_COLOR_EXCLUDED:return neutral
    try:target=date.fromisoformat(str(date_value)[:10])
    except (ValueError,TypeError):return neutral
    days=(today_date-target).days
    if days<0:return {**neutral,'label':'미래 일자 · 원문 검토'}
    hue=round(135*(1-min(days/365,1)))
    return {'days':days,'label':'1년 이상 경과' if days>=365 else f'{days}일 경과','style':'background:#fee2e2;color:#991b1b;border:1px solid #ef4444' if days>=365 else f'background:hsl({hue},65%,89%);color:hsl({hue},80%,20%);border:1px solid hsl({hue},50%,48%)'}


def normalized_part(value):
    raw=str(value or '').strip();value=raw.casefold()
    matches=[('Diffuser',['diffuser','디퓨저','dif']),('Backing Plate',['backing','배킹','백킹','bp']),('Susceptor',['susceptor','서셉터','susc']),('Shadow Frame',['shadow','샤도우','섀도우','sf']),('RPSC Reactor',['rpsc','reactor']),('MF Generator',['mf generator','mfg']),('Matcher',['matcher','매처']),('RFG',['rfg'])]
    for name,aliases in matches:
        if any(token in value for token in aliases):return name
    return raw if raw in PARTS else '기타 부품'


def is_replacement(log):
    work_type=str(log.get('workType') or '').strip()
    if work_type in ['초기 셋업','셋업','Setup','점검','청소','CSD 조정','재측정']:return False
    if any(k in work_type.casefold() for k in ['교체','pm','replace']):return True
    before=log.get('beforeSn');after=log.get('afterSn')
    if log.get('targetPart') and before and after and before!='-' and after!='-' and before!=after:return True
    return bool(log.get('targetPart') and '교체' in (str(log.get('reason') or '')+str(log.get('details') or '')))


def monthly_work(logs,equipment_id,year,chamber='전체 Chamber',part='전체 부품',mode='부품 교체',status='전체'):
    rows=[]
    for r in logs:
        if r.get('deletedAt') or r.get('equipmentId')!=equipment_id:continue
        if not good_date(r.get('workDate')) or int(r['workDate'][:4])!=year:continue
        if chamber!='전체 Chamber' and r.get('chamberId')!=chamber:continue
        if part!='전체 부품' and normalized_part(r.get('targetPart'))!=part:continue
        if mode=='부품 교체' and (not is_replacement(r) or not r.get('targetPart')):continue
        if status!='전체' and r.get('issueStatus')!=status:continue
        rows.append(r)
    counts=[{'월':f'{year}-{month:02d}',**{p:0 for p in PARTS}} for month in range(1,13)]
    for r in rows:counts[int(r['workDate'][5:7])-1][normalized_part(r.get('targetPart'))]+=1
    return counts,rows


def archive_work(path,identifier,actor,reason,expected_version,restore=False):
    if not str(actor).strip() or not str(reason).strip():raise ValueError('담당자와 사유를 입력해주세요.')
    conn=connection(path)
    try:
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            old=conn.execute("SELECT payload,version FROM entities WHERE kind='workLogs' AND id=?",(identifier,)).fetchone()
            if not old or old['version']!=expected_version:raise ValueError('다른 화면에서 변경됐습니다. 새로고침 후 다시 시도해주세요.')
            item=json.loads(old['payload'])
            if restore:
                if not item.get('deletedAt'):raise ValueError('보관된 작업만 복원할 수 있습니다.')
                for key in ['deletedAt','deletedBy','deletionReason']:item.pop(key,None)
                item.update(restoredAt=now(),restoredBy=actor,restorationReason=reason)
            else:
                if item.get('deletedAt'):raise ValueError('이미 삭제 보관된 작업입니다.')
                item.update(deletedAt=now(),deletedBy=actor,deletionReason=reason)
            value=json.dumps(item,ensure_ascii=False,allow_nan=False)
            conn.execute("UPDATE entities SET payload=?,version=version+1 WHERE kind='workLogs' AND id=?",(value,identifier))
            conn.execute('INSERT INTO audit VALUES (?,?,?,?,?,?,?,?)',(uuid4().hex,now(),actor,'RESTORE' if restore else 'ARCHIVE','workLogs',identifier,old['payload'],value))
    finally:conn.close()
