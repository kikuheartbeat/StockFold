from decimal import Decimal, ROUND_HALF_UP
import json
import re
import sqlite3
from .db import audit
from .validation import ValidationError, cents, money_to_cents, price, sector_color, text, valid_date

def rows(conn,sql,args=()):
    return [dict(r) for r in conn.execute(sql,args)]

def stock_list(conn):
    return rows(conn,'''SELECT s.*,c.name AS second_level,p.name AS first_level,
                       COALESCE(p.color,'#64748B') AS color FROM stocks s
                       LEFT JOIN sectors c ON c.id=s.sector_id LEFT JOIN sectors p ON p.id=c.parent_id
                       ORDER BY s.active DESC,s.code''')

def sector_list(conn):
    return rows(conn,'SELECT * FROM sectors ORDER BY level,id')

def save_stock(conn,payload):
    ident=payload.get('id')
    old=conn.execute('SELECT * FROM stocks WHERE id=?',(ident,)).fetchone() if ident else None
    if ident and not old: raise ValidationError('股票不存在')
    d=dict(old) if old else {'market':'','asset_type':'stock','sector_id':None,'active':1,'fund_category':'','fund_theme':''}
    d.update(payload)
    d['code']=text(d.get('code'),'证券代码',20,True)
    if not re.fullmatch(r'[0-9A-Za-z._-]+',d['code']): raise ValidationError('证券代码格式无效')
    d['name']=text(d.get('name'),'证券名称',80,True)
    d['market']=text(d.get('market'),'市场',15)
    if d.get('asset_type') not in ['stock','etf','product']: raise ValidationError('证券类型无效')
    sector_id=d.get('sector_id') or None
    if sector_id:
        sector=conn.execute('SELECT * FROM sectors WHERE id=?',(sector_id,)).fetchone()
        if not sector or sector['level']!=2 or d['asset_type']!='stock': raise ValidationError('股票只能选择二级行业')
    status='manual' if 'sector_id' in payload else d.get('classification_status',('matched' if sector_id else ('separate' if d['asset_type']!='stock' else 'unclassified')))
    values=(d['code'],d['name'],d['market'],d['asset_type'],sector_id,text(d.get('fund_category'),'基金类别',80),
            text(d.get('fund_theme'),'基金主题',80),status,1 if d.get('active',1) else 0)
    try:
        with conn:
            if old:
                conn.execute('''UPDATE stocks SET code=?,name=?,market=?,asset_type=?,sector_id=?,fund_category=?,fund_theme=?,classification_status=?,active=? WHERE id=?''',values+(ident,))
                if any(old[k]!=d[k] for k in ['code','market','asset_type']):
                    conn.execute('DELETE FROM market_prices WHERE stock_id=?',(ident,))
                    conn.execute('DELETE FROM market_sync WHERE stock_id=?',(ident,))
            else:
                cur=conn.execute('''INSERT INTO stocks(code,name,market,asset_type,sector_id,fund_category,fund_theme,classification_status,active) VALUES (?,?,?,?,?,?,?,?,?)''',values)
                ident=cur.lastrowid
            result=dict(conn.execute('SELECT * FROM stocks WHERE id=?',(ident,)).fetchone())
            audit(conn,'stock',ident,'update' if old else 'create',dict(old) if old else None,result)
        return result
    except sqlite3.IntegrityError: raise ValidationError('同市场证券代码已存在')

def save_sector(conn,payload,preview=False):
    ident=payload.get('id')
    old=conn.execute('SELECT * FROM sectors WHERE id=?',(ident,)).fetchone() if ident else None
    if ident and not old: raise ValidationError('行业不存在')
    d=dict(old) if old else {}
    d.update(payload)
    name=text(d.get('name'),'行业名称',80,True)
    level=d.get('level')
    parent=d.get('parent_id') or None
    if level not in [1,2]: raise ValidationError('行业层级只能为1或2')
    if old and old['level']!=level: raise ValidationError('不能修改已存在行业的层级')
    if level==1 and parent: raise ValidationError('一级行业不能设置父级')
    if level==2:
        p=conn.execute('SELECT * FROM sectors WHERE id=? AND level=1',(parent,)).fetchone()
        if not p: raise ValidationError('二级行业必须属于一个一级行业')
    color=p['color'] if level==2 else d.get('color')
    if not color:
        if parent:
            color=p['color']
        else: color='#6366F1'
    color=sector_color(color)
    children=[]
    if ident and level==1 and color!=old['color']:
        for child in conn.execute('SELECT * FROM sectors WHERE parent_id=? ORDER BY id',(ident,)):
            children.append({'id':child['id'],'name':child['name'],'color':color})
    result={'id':ident,'name':name,'level':level,'parent_id':parent,'color':color,'children':children}
    if preview: return result
    try:
        with conn:
            if old: conn.execute('UPDATE sectors SET name=?,parent_id=?,color=? WHERE id=?',(name,parent,color,ident))
            else:
                ident=conn.execute('INSERT INTO sectors(name,level,parent_id,color,source) VALUES (?,?,?,?,?)',(name,level,parent,color,'手工维护')).lastrowid
            for child in children: conn.execute('UPDATE sectors SET color=? WHERE id=?',(child['color'],child['id']))
            audit(conn,'sector',ident,'update' if old else 'create',dict(old) if old else None,result)
        return dict(conn.execute('SELECT * FROM sectors WHERE id=?',(ident,)).fetchone())
    except sqlite3.IntegrityError: raise ValidationError('同一父级下行业名称已存在')

def validate_returns(conn,records):
    if not isinstance(records,list): raise ValidationError('收益记录应为列表')
    result=[]
    seen=set()
    for i,r in enumerate(records):
        if not isinstance(r,dict): raise ValidationError(f'第{i+1}条收益格式无效')
        sid=r.get('stock_id')
        if isinstance(sid,bool) or not isinstance(sid,int) or not conn.execute('SELECT id FROM stocks WHERE id=?',(sid,)).fetchone():
            raise ValidationError(f'第{i+1}条股票不存在')
        if sid in seen: raise ValidationError('同一天同一股票只能有一条收益')
        seen.add(sid)
        result.append({'stock_id':sid,'pnl_cents':cents(r.get('pnl_cents'),'日收益'),'note':text(r.get('note'),'备注')})
    return result

def get_day(conn,date):
    valid_date(date)
    status=conn.execute('SELECT * FROM day_status WHERE date=?',(date,)).fetchone()
    account=conn.execute('SELECT * FROM daily_accounts WHERE date=?',(date,)).fetchone()
    returns=rows(conn,'''SELECT r.*,s.code,s.name FROM daily_returns r JOIN stocks s ON s.id=r.stock_id WHERE r.date=? ORDER BY s.code''',(date,))
    return {'date':date,'status':status['status'] if status else 'draft',
            'expected_stock_ids':json.loads(status['expected_stock_ids']) if status else [],
            'note':status['note'] if status else '', 'returns':returns,
            'account':dict(account) if account else {'total_assets_cents':None,'cash_cents':None,'other_pnl_cents':0,'note':''},
            'ledger':ledger_list(conn,date=date)}

def save_day(conn,date,payload):
    valid_date(date)
    records=validate_returns(conn,payload.get('returns',[]))
    status=payload.get('status','draft')
    if status not in ['draft','confirmed','skip']: raise ValidationError('日记录状态无效')
    expected=payload.get('expected_stock_ids',[r['stock_id'] for r in records])
    if not isinstance(expected,list) or any(type(x) is not int for x in expected) or len(set(expected))!=len(expected): raise ValidationError('应录股票清单无效')
    for sid in expected:
        if not conn.execute('SELECT id FROM stocks WHERE id=?',(sid,)).fetchone(): raise ValidationError('应录股票不存在')
    if status=='confirmed' and not set(expected).issubset({r['stock_id'] for r in records}):
        raise ValidationError('请补齐应录股票收益，包括明确为零的记录')
    account=payload.get('account') or {}
    total=cents(account.get('total_assets_cents'),'账户总资产',True)
    cash=cents(account.get('cash_cents'),'现金余额',True)
    other=cents(account.get('other_pnl_cents',0),'其他收益')
    if (total is None)!=(cash is None): raise ValidationError('总资产和现金请同时填写或同时留空')
    if total is not None and (total<0 or cash<0 or cash>total): raise ValidationError('资产快照需满足 0 ≤ 现金 ≤ 总资产')
    if status=='skip' and (records or other): raise ValidationError('无需记录日不能同时包含收益，请改为确认日')
    note=text(payload.get('note'),'备注')
    old=get_day(conn,date)
    with conn:
        conn.execute('DELETE FROM daily_returns WHERE date=?',(date,))
        for r in records:
            conn.execute('INSERT INTO daily_returns(date,stock_id,pnl_cents,note) VALUES (?,?,?,?)',(date,r['stock_id'],r['pnl_cents'],r['note']))
        conn.execute('''INSERT INTO daily_accounts VALUES (?,?,?,?,?) ON CONFLICT(date) DO UPDATE SET total_assets_cents=excluded.total_assets_cents,cash_cents=excluded.cash_cents,other_pnl_cents=excluded.other_pnl_cents,note=excluded.note''',
                     (date,total,cash,other,text(account.get('note'),'资产备注')))
        conn.execute('INSERT INTO day_status VALUES (?,?,?,?) ON CONFLICT(date) DO UPDATE SET status=excluded.status,expected_stock_ids=excluded.expected_stock_ids,note=excluded.note',
                     (date,status,json.dumps(expected),note))
        audit(conn,'day',date,'save',old,payload)
        conn.execute('DELETE FROM calculation_days WHERE date=?',(date,))
    return get_day(conn,date)

def save_returns_batch(conn,records,confirm=False):
    if not isinstance(records,list) or not records or len(records)>10000: raise ValidationError('请填写1至10000条补录数据')
    clean=[]
    seen=set()
    for i,r in enumerate(records):
        try:
            day=valid_date(r.get('date'))
            item=validate_returns(conn,[r])[0]
            key=(day,item['stock_id'])
            if key in seen: raise ValidationError('批次中有重复日期和股票')
            seen.add(key)
            clean.append((day,item))
        except (ValidationError,AttributeError) as e: raise ValidationError(f'第{i+1}行：{e}')
    with conn:
        by_day={}
        for day,r in clean:
            conn.execute('INSERT INTO daily_returns(date,stock_id,pnl_cents,note) VALUES (?,?,?,?) ON CONFLICT(date,stock_id) DO UPDATE SET pnl_cents=excluded.pnl_cents,note=excluded.note,updated_at=CURRENT_TIMESTAMP',
                         (day,r['stock_id'],r['pnl_cents'],r['note']))
            by_day.setdefault(day,set()).add(r['stock_id'])
        for day,stock_ids in by_day.items():
            conn.execute('DELETE FROM calculation_days WHERE date=?',(day,))
            st=conn.execute('SELECT expected_stock_ids FROM day_status WHERE date=?',(day,)).fetchone()
            expected=set(json.loads(st[0])) if st else set()
            expected.update(stock_ids)
            state='confirmed' if confirm else 'draft'
            actual={v[0] for v in conn.execute('SELECT stock_id FROM daily_returns WHERE date=?',(day,))}
            if confirm and not expected.issubset(actual): raise ValidationError(f'{day}仍有应录股票缺失，不能确认')
            conn.execute('INSERT INTO day_status(date,status,expected_stock_ids) VALUES (?,?,?) ON CONFLICT(date) DO UPDATE SET status=excluded.status,expected_stock_ids=excluded.expected_stock_ids',(day,state,json.dumps(sorted(expected))))
        audit(conn,'returns_batch','batch','save',None,{'count':len(clean)})
    return {'saved':len(clean),'dates':sorted({x[0] for x in clean})}

def ledger_list(conn,date=None,start=None,end=None):
    sql='SELECT l.*,s.code,s.name FROM ledger_entries l LEFT JOIN stocks s ON s.id=l.stock_id WHERE 1=1'
    args=[]
    for key,value,operator in [('date',date,'='),('date',start,'>='),('date',end,'<=')]:
        if value: sql+=f' AND l.{key}{operator}?'; args.append(valid_date(value))
    return rows(conn,sql+' ORDER BY l.date DESC,l.sequence DESC,l.id DESC',args)

def save_ledger(conn,payload):
    ident=payload.get('id')
    old=conn.execute('SELECT * FROM ledger_entries WHERE id=?',(ident,)).fetchone() if ident else None
    if ident and not old: raise ValidationError('流水不存在')
    d=dict(old) if old else {}
    d.update(payload)
    day=valid_date(d.get('date'))
    kind=d.get('kind')
    if kind not in ['buy','sell','deposit','withdraw','other']: raise ValidationError('流水类型无效')
    sid=d.get('stock_id') or None
    if sid and not conn.execute('SELECT id FROM stocks WHERE id=?',(sid,)).fetchone(): raise ValidationError('股票不存在')
    quantity=d.get('quantity',0)
    if type(quantity) is not int or abs(quantity)>10**10: raise ValidationError('成交数量应为整数')
    px=price(d.get('price_decimal','0'))
    fees=cents(d.get('fees_cents',0),'手续费')
    if fees<0: raise ValidationError('手续费不能为负')
    if kind in ['buy','sell']:
        if old: quantity=abs(quantity)
        if not sid or quantity<=0: raise ValidationError('买卖请选择股票，并填写大于零的数量')
        same_trade=old and kind==old['kind'] and sid==old['stock_id'] and quantity==abs(old['quantity']) and Decimal(px)==Decimal(old['price_decimal'])
        if same_trade:
            # Broker average prices may be rounded. Preserve the actual settled amount.
            amount=old['amount_cents'];change=old['cash_change_cents']+old['fees_cents']-fees
            quantity=old['quantity']
        else:
            amount=int((Decimal(px)*quantity*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
            change=amount-fees if kind=='sell' else -amount-fees
    elif kind in ['deposit','withdraw']:
        amount=cents(d.get('amount_cents'),'转账金额')
        if amount<=0: raise ValidationError('转账金额应大于零')
        change=amount if kind=='deposit' else -amount
        sid=None; quantity=0; px='0'
    else:
        change=cents(d.get('cash_change_cents',0),'资金发生额')
        amount=abs(change)
    summary=text(d.get('summary'),'摘要',80) or {'buy':'证券买入','sell':'证券卖出','deposit':'银行转证券','withdraw':'证券转银行','other':'其他流水'}[kind]
    values=(day,sid,kind,quantity,px,amount,change,fees,summary,text(d.get('note'),'备注'))
    with conn:
        if old: conn.execute('UPDATE ledger_entries SET date=?,stock_id=?,kind=?,quantity=?,price_decimal=?,amount_cents=?,cash_change_cents=?,fees_cents=?,summary=?,note=? WHERE id=?',values+(ident,))
        else: ident=conn.execute('INSERT INTO ledger_entries(date,stock_id,kind,quantity,price_decimal,amount_cents,cash_change_cents,fees_cents,summary,note) VALUES (?,?,?,?,?,?,?,?,?,?)',values).lastrowid
        result=dict(conn.execute('SELECT * FROM ledger_entries WHERE id=?',(ident,)).fetchone())
        audit(conn,'ledger',ident,'update' if old else 'create',dict(old) if old else None,result)
    return result

def delete_ledger(conn,ident):
    old=conn.execute('SELECT * FROM ledger_entries WHERE id=?',(ident,)).fetchone()
    if not old: raise ValidationError('流水不存在')
    with conn:
        conn.execute('DELETE FROM ledger_entries WHERE id=?',(ident,))
        audit(conn,'ledger',ident,'delete',dict(old),None)
    return {'deleted':ident}
