"""Read source XLSX data without executing formulas or external links."""
from collections import Counter
from datetime import date,datetime,timedelta
from decimal import Decimal,InvalidOperation
from functools import lru_cache
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path,PurePosixPath
import re
import sqlite3
import xml.etree.ElementTree as ET
import zipfile
from .db import audit
from .validation import ValidationError,money_to_cents,price,valid_date

NS={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
HEADERS=['发生日期','摘要','币种','证券代码','证券名称','成交股数','成交价格','成交金额','总发生金额','净发生金额','资金余额','证券余额','佣金','其中：净佣金','印花税','过户费','利息单价','应计利息']
RESOURCE=Path(__file__).resolve().parent.parent/'resources'

@lru_cache(maxsize=1)
def classification_catalog():
    p=RESOURCE/'stock_classifications.json'
    if not p.exists(): return {}
    d=json.loads(p.read_text(encoding='utf8'))
    return {s['code']:s for s in d['stocks']}

def column_index(address):
    n=0
    for ch in re.match(r'[A-Z]+',address).group(0): n=n*26+ord(ch)-64
    return n-1

def read_xlsx(content):
    try:
        with zipfile.ZipFile(BytesIO(content)) as z:
            if sum(i.file_size for i in z.infolist())>50*1024*1024 or len(z.infolist())>3000:
                raise ValidationError('文件解压后过大，请减少数据量')
            strings=[]
            if 'xl/sharedStrings.xml' in z.namelist():
                strings=[''.join(n.itertext()) for n in ET.fromstring(z.read('xl/sharedStrings.xml'))]
            wb=ET.fromstring(z.read('xl/workbook.xml'))
            sheet=wb.find('m:sheets/m:sheet',NS)
            relid=sheet.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
            rels=ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
            target=next(r.get('Target') for r in rels if r.get('Id')==relid)
            target=target.lstrip('/') if target.startswith('/') else str(PurePosixPath('xl')/target)
            if '..' in PurePosixPath(target).parts: raise ValidationError('工作表路径无效')
            data=ET.fromstring(z.read(target))
            rows=[]
            for row in data.findall('m:sheetData/m:row',NS):
                values={}
                for c in row.findall('m:c',NS):
                    index=column_index(c.get('r'))
                    v=c.find('m:v',NS)
                    value=v.text if v is not None else ''
                    if c.get('t')=='s': value=strings[int(value)]
                    elif c.get('t')=='inlineStr': value=''.join(c.find('m:is',NS).itertext())
                    values[index]=value or ''
                rows.append((int(row.get('r')),values))
            return rows
    except ValidationError: raise
    except (zipfile.BadZipFile,KeyError,ET.ParseError,IndexError,ValueError,StopIteration,TypeError,AttributeError):
        raise ValidationError('无法读取文件，请选择有效的 Excel .xlsx 工作簿')

def parse_date(value):
    value=str(value).strip()
    if re.fullmatch(r'\d{8}',value): value=f'{value[:4]}-{value[4:6]}-{value[6:]}'
    elif re.fullmatch(r'\d+(\.\d+)?',value):
        value=(datetime(1899,12,30)+timedelta(days=float(value))).date().isoformat()
    elif 'T' in value: value=value.split('T')[0]
    return valid_date(value)

def source_decimal(value,step,field):
    try:
        value=Decimal(value or '0')
        rounded=value.quantize(Decimal(step))
        if not value.is_finite() or abs(rounded-value)>Decimal('0.00000001'):
            raise InvalidOperation()
        return format(rounded,'f')
    except (InvalidOperation,ValueError):
        raise ValidationError(f'{field}精度超出源表约定，不能直接导入')

def source_money(value,field):
    return money_to_cents(source_decimal(value,'0.01',field),field)

def normalize(values,row_number):
    raw={name:values[i] if i<len(values) else '' for i,name in enumerate(HEADERS)}
    day=parse_date(raw['发生日期'])
    summary=raw['摘要'].strip()
    currency=raw['币种'].strip()
    if currency not in ['人民币','人民币（RMB）','RMB','CNY','']:
        raise ValidationError(f'暂不支持币种：{currency}')
    code=raw['证券代码'].strip()
    if code:
        if re.fullmatch(r'\d+(\.0+)?',code): code=str(int(Decimal(code))).zfill(6)
        if not re.fullmatch(r'\d{6}',code): raise ValidationError(f'证券代码无效：{code}')
    name=raw['证券名称'].strip()
    try:
        quantity=Decimal(raw['成交股数'] or '0')
        if not quantity.is_finite() or quantity!=quantity.to_integral_value(): raise InvalidOperation()
        quantity=int(quantity)
    except (InvalidOperation,ValueError): raise ValidationError('成交股数不是整数')
    px=price(source_decimal(raw['成交价格'],'0.0001','成交价格'))
    amount=source_money(raw['成交金额'],'成交金额')
    change=source_money(raw['总发生金额'],'总发生金额')
    fees={key:source_money(raw[key],key) for key in ['佣金','其中：净佣金','印花税','过户费']}
    total_fees=fees['佣金']+fees['印花税']+fees['过户费']
    kind={'证券买入':'buy','证券卖出':'sell','银行转证券':'deposit','证券转银行':'withdraw'}.get(summary,'other')
    classification=classification_catalog().get(code,{})
    if code=='119971' and '资管' in summary:
        classification={'code':code,'name':name,'market':'OTC','asset_type':'product'}
    asset_type=classification.get('asset_type','stock')
    norm={'date':day,'summary':summary,'code':code,'name':name,'kind':kind,
          'quantity':quantity,'price_decimal':px,'amount_cents':abs(change) if kind in ['deposit','withdraw'] else amount,
          'cash_change_cents':change,'fees_cents':total_fees,'fees':fees,
          'classification':classification,'asset_type':asset_type,'row_number':row_number,'raw':raw}
    fingerprint_fields=[day,summary,code,quantity,px,amount,change,total_fees,raw['资金余额']]
    norm['fingerprint']=sha256(json.dumps(fingerprint_fields,ensure_ascii=False).encode()).hexdigest()
    return norm

def preview_xlsx(conn,content,filename):
    if len(content)>16*1024*1024: raise ValidationError('Excel 文件不能超过16MB')
    file_hash=sha256(content).hexdigest()
    rows=read_xlsx(content)
    header=None
    for number,values in rows[:50]:
        cleaned={i:str(v).replace('\n','').strip() for i,v in values.items()}
        if all(h in cleaned.values() for h in HEADERS):
            header={h:next(i for i,v in cleaned.items() if v==h) for h in HEADERS}
            header_row=number;break
    if header is None: raise ValidationError('未找到普通资金流水明细所需的18列表头')
    records=[]
    source_totals={}
    for number,values in rows:
        if number<=header_row: continue
        first=values.get(header['发生日期'],'').strip()
        if first=='合计':
            source_totals={h:values.get(header[h],'') for h in HEADERS}
            continue
        if not first: continue
        try: records.append(normalize([values.get(header[h],'') for h in HEADERS],number))
        except ValidationError as e: raise ValidationError(f'Excel 第{number}行：{e}')
    if not records: raise ValidationError('文件中没有可导入的流水')
    if len(records)>30000: raise ValidationError('单次最多导入30000条流水')
    existing={json.loads(r[0]).get('fingerprint') for r in conn.execute('SELECT normalized_json FROM import_rows')}
    overlap=sum(r['fingerprint'] in existing for r in records)
    securities={r['code']:r for r in records if r['code']}
    types=Counter(r['asset_type'] for r in securities.values())
    kinds=Counter(r['kind'] for r in records)
    warnings=[]
    if source_totals.get('总发生金额'):
        stated=source_money(source_totals['总发生金额'],'合计总发生金额')
        actual=sum(r['cash_change_cents'] for r in records)
        if stated!=actual:
            warnings.append(f'表尾总发生金额合计为{stated/100:.2f}元，实际明细合计为{actual/100:.2f}元，可能删除或修改过明细。程序仅导入实际明细，不把合计当收益。')
    unclassified=[{'code':code,'name':r['name']} for code,r in securities.items() if r['asset_type']=='stock' and not r['classification'].get('second_level')]
    return {'file_name':Path(filename).name,'file_hash':file_hash,'record_count':len(records),
            'stock_count':types['stock'],'security_count':len(securities),'asset_types':dict(types),
            'kinds':dict(kinds),'start':min(r['date'] for r in records),'end':max(r['date'] for r in records),
            'overlap_count':overlap,'already_imported':bool(conn.execute('SELECT 1 FROM import_batches WHERE file_hash=?',(file_hash,)).fetchone()),
            'unclassified':unclassified,'warnings':warnings,'records':records}

def commit_import(conn,preview,allow_overlap=False):
    if conn.execute('SELECT 1 FROM import_batches WHERE file_hash=?',(preview['file_hash'],)).fetchone():
        raise ValidationError('该文件已经导入，无需重复导入')
    existing={json.loads(r[0]).get('fingerprint') for r in conn.execute('SELECT normalized_json FROM import_rows')}
    overlap=sum(r['fingerprint'] in existing for r in preview['records'])
    if overlap and not allow_overlap: raise ValidationError(f'发现{overlap}条可能重复流水，请核对后明确选择保留两份再导入')
    try:
        with conn:
            batch=conn.execute('INSERT INTO import_batches(file_name,file_hash,record_count) VALUES (?,?,?)',
                               (preview['file_name'],preview['file_hash'],preview['record_count'])).lastrowid
            security_ids={}
            for r in preview['records']:
                sid=None
                if r['code']:
                    info=r['classification']
                    market=info.get('market') or ('SH' if r['code'].startswith(('5','6','9')) else 'SZ')
                    key=(market,r['code'])
                    sid=security_ids.get(key)
                    if sid is None:
                        sector=None
                        if info.get('second_level'):
                            row=conn.execute('SELECT c.id FROM sectors c JOIN sectors p ON p.id=c.parent_id WHERE c.level=2 AND c.name=? AND p.name=?',(info['second_level'],info['first_level'])).fetchone()
                            if row: sector=row[0]
                        old=conn.execute('SELECT * FROM stocks WHERE market=? AND code=?',key).fetchone()
                        if old:
                            sid=old['id']
                            if sector and not old['sector_id'] and old['classification_status']=='unclassified':
                                conn.execute('UPDATE stocks SET sector_id=?,classification_status=\'matched\' WHERE id=?',(sector,sid))
                        else:
                            sid=conn.execute('''INSERT INTO stocks(code,name,market,asset_type,sector_id,fund_category,fund_theme,classification_status) VALUES (?,?,?,?,?,?,?,?)''',
                                (r['code'],r['name'],market,r['asset_type'],sector,info.get('fund_category',''),info.get('fund_theme',''),'matched' if sector else 'separate' if r['asset_type']!='stock' else 'unclassified')).lastrowid
                        security_ids[key]=sid
                raw_id=conn.execute('INSERT INTO import_rows(batch_id,row_number,raw_json,normalized_json) VALUES (?,?,?,?)',
                                    (batch,r['row_number'],json.dumps(r['raw'],ensure_ascii=False),json.dumps(r,ensure_ascii=False))).lastrowid
                conn.execute('''INSERT INTO ledger_entries(date,sequence,stock_id,kind,quantity,price_decimal,amount_cents,cash_change_cents,fees_cents,fees_json,summary,import_row_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                             (r['date'],r['row_number'],sid,r['kind'],r['quantity'],r['price_decimal'],r['amount_cents'],r['cash_change_cents'],r['fees_cents'],json.dumps(r['fees'],ensure_ascii=False),r['summary'],raw_id))
            audit(conn,'import',batch,'create',None,{'file_name':preview['file_name'],'records':preview['record_count']})
        return {'imported':preview['record_count'],'batch_id':batch,'security_count':len(security_ids)}
    except sqlite3.IntegrityError as e: raise ValidationError(f'导入失败，未写入部分数据：{e}')
