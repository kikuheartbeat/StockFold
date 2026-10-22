"""Reconstruct marked-to-market P&L without treating transfers as earnings."""
from bisect import bisect_right
from collections import defaultdict
from datetime import date,timedelta
from decimal import Decimal,ROUND_HALF_UP,InvalidOperation
from hashlib import sha256
import json
import uuid
from .db import settings,audit
from .records import stock_list
from .returns import dates_between
from .validation import ValidationError,valid_date,cents

def ledger_rows(conn):
    result=[]
    for row in conn.execute('''SELECT l.*,r.raw_json,r.normalized_json FROM ledger_entries l
      LEFT JOIN import_rows r ON r.id=l.import_row_id ORDER BY l.date,l.sequence,l.id'''):
        item=dict(row)
        for key in ['raw_json','normalized_json']:
            try: item[key]=json.loads(item[key] or '{}')
            except (ValueError,TypeError): item[key]={}
        result.append(item)
    return result

def input_fingerprint(conn,include_market=True):
    tables=['stocks','ledger_entries','import_rows','daily_returns','daily_accounts','day_status',
            'app_settings','opening_positions','calculation_days']
    if include_market: tables+=['market_prices','market_calendar','calendar_sync']
    digest=sha256()
    for table in tables:
        digest.update(table.encode())
        digest.update(json.dumps([list(r) for r in conn.execute(f'SELECT * FROM {table} ORDER BY 1,2')],ensure_ascii=False,default=str).encode())
    return digest.hexdigest()

def integer(value):
    try:
        d=Decimal(str(value))
        return int(d) if d.is_finite() and d==d.to_integral_value() else None
    except (InvalidOperation,ValueError,TypeError): return None

def raw_money(value):
    try:
        d=Decimal(str(value))
        return int((d*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP)) if d.is_finite() else None
    except (InvalidOperation,ValueError,TypeError): return None

def share_change(entry):
    if entry['kind']=='buy': return abs(entry['quantity'])
    if entry['kind']=='sell': return -abs(entry['quantity'])
    if entry['summary'] in ['红股入账','股份转增','证券派发','送股入账']:
        return entry['quantity']
    return 0

def unchanged_source(entry,stocks):
    """Balances describe the original economic event, never an edited replacement."""
    original=entry['normalized_json']
    fields=['quantity','date','kind','summary','cash_change_cents','price_decimal','amount_cents','fees_cents']
    if any(k in original and original[k]!=entry[k] for k in fields): return False
    stock=stocks.get(entry['stock_id'],{})
    if original.get('code') and original['code']!=stock.get('code'): return False
    market=original.get('classification',{}).get('market')
    return not market or market==stock.get('market')

def source_breaks(entries,stocks):
    changed=[e for e in entries if e['import_row_id'] and not unchanged_source(e,stocks)]
    cash_from=min((min(e['date'],e['normalized_json'].get('date',e['date'])) for e in changed),default=None)
    positions={}
    for e in changed:
        original_code=e['normalized_json'].get('code')
        affected={e['stock_id']}|{sid for sid,s in stocks.items() if original_code and s['code']==original_code}
        for sid in affected:
            if sid:
                day=min(e['date'],e['normalized_json'].get('date',e['date']))
                positions[sid]=min(day,positions.get(sid,day))
    return cash_from,positions,changed

def opening_state(conn):
    entries=ledger_rows(conn);stocks=stock_list(conn)
    has_opening=conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='opening_positions'").fetchone()
    overrides={r['stock_id']:r['quantity'] for r in conn.execute('SELECT * FROM opening_positions')} if has_opening else {}
    stock_map={s['id']:s for s in stocks}
    cash_break,position_breaks,_=source_breaks(entries,stock_map)
    first={};cumulative=defaultdict(int);inferred={}
    for entry in entries:
        sid=entry['stock_id']
        if not sid: continue
        if share_change(entry) or entry['kind'] in ['buy','sell']: first.setdefault(sid,entry)
        cumulative[sid]+=share_change(entry)
        after=integer(entry['raw_json'].get('证券余额'))
        if sid not in inferred and after is not None and unchanged_source(entry,stock_map) and (sid not in position_breaks or entry['date']<position_breaks[sid]):
            inferred[sid]=after-cumulative[sid]
    positions=[]
    for stock in stocks:
        sid=stock['id'];entry=first.get(sid)
        if not entry and sid not in overrides: continue
        if sid in overrides: quantity=overrides[sid];source='手工指定'
        else:
            value=inferred.get(sid)
            if value is not None and value>=0: quantity=value;source='首笔证券余额反推'
            else: quantity=0;source='暂按0（请核对）'
        positions.append({**{k:stock[k] for k in ['id','code','name','market','asset_type']},
                          'stock_id':sid,'quantity':quantity,'source':source,
                          'requires_confirmation':sid not in overrides and sid in position_breaks and sid not in inferred})
    config=settings(conn);cash=config.get('opening_cash_cents');cash_source='手工指定' if cash is not None else '待填写'
    if cash is None:
        cumulative=0
        for entry in entries:
            cumulative+=entry['cash_change_cents']
            balance=raw_money(entry['raw_json'].get('资金余额'))
            if balance is not None and unchanged_source(entry,stock_map) and (cash_break is None or entry['date']<cash_break):
                cash=balance-cumulative;cash_source='首笔资金余额反推';break
    return {'positions':positions,'cash_cents':cash,'cash_source':cash_source,
            'ledger_start':entries[0]['date'] if entries else None,
            'ledger_end':entries[-1]['date'] if entries else None}

def market_requests(conn,start,end):
    state=opening_state(conn);entries=ledger_rows(conn);by_stock=defaultdict(list)
    for entry in entries:
        if entry['stock_id'] and entry['date']<=end: by_stock[entry['stock_id']].append(entry)
    result=[]
    for stock in state['positions']:
        sid=stock['stock_id'];events=by_stock[sid]
        if not events and not stock['quantity']: continue
        first=events[0]['date'] if events else start
        if first>end and not stock['quantity']: continue
        quantity=stock['quantity']+sum(share_change(e) for e in events)
        a=start if stock['quantity'] or first<=start else first
        b=end if quantity!=0 else max((e['date'] for e in events),default=end)
        if b<start: continue
        a=(date.fromisoformat(a)-timedelta(days=40)).isoformat()
        result.append({**stock,'start':a,'end':min(b,end)})
    return result

def protected_dates(conn):
    own={r[0] for r in conn.execute('SELECT date FROM calculation_days')}
    touched={r[0] for table in ['day_status','daily_accounts','daily_returns'] for r in conn.execute(f'SELECT DISTINCT date FROM {table}')}
    manual={r[0] for r in conn.execute("SELECT DISTINCT date FROM daily_returns WHERE source!='market_close'")}
    return (touched-own)|manual

def reconstruct(conn,start,end):
    days=dates_between(start,end)
    coverage=conn.execute('SELECT * FROM calendar_sync WHERE id=1').fetchone()
    if not coverage or coverage['start_date']>start or coverage['end_date']<end:
        raise ValidationError('交易日历尚未覆盖所选日期，请先获取行情')
    calendar=sorted(r[0] for r in conn.execute('SELECT date FROM market_calendar WHERE date<=? ORDER BY date',(end,)))
    if not calendar: raise ValidationError('没有有效的交易日历')
    opening=opening_state(conn);positions={s['stock_id']:s['quantity'] for s in opening['positions']}
    stocks={s['id']:s for s in stock_list(conn)}
    prices={(r['stock_id'],r['date']):Decimal(r['close_decimal']) for r in conn.execute('SELECT * FROM market_prices WHERE date<=?',(end,))}
    entries=ledger_rows(conn);by_date=defaultdict(list)
    for entry in entries: by_date[entry['date']].append(entry)
    cash=opening['cash_cents'];issues=[];seen=set()
    bad_positions={s['stock_id'] for s in opening['positions'] if s['requires_confirmation']}
    cash_break,position_breaks,changed=source_breaks(entries,stocks)
    def issue(kind,day,message,sid=None,**details):
        key=(kind,day,sid,message)
        if key not in seen:
            seen.add(key);issues.append({'type':kind,'date':day,'stock_id':sid,'stock_name':stocks.get(sid,{}).get('name',''),'message':message,**details})
    if cash is None: issue('opening_cash',start,'缺少流水起点现金，可计算股票收益，但暂不能还原总资产')
    for e in changed:
        if min(e['date'],e['normalized_json'].get('date',e['date']))<=end:
            issue('source_anchor_changed',e['date'],'导入交易已修改：该日起原始现金余额及相关证券余额停用，按现有交易结转；请核对期初信息',e['stock_id'],entry_id=e['id'])
    for stock in opening['positions']:
        if stock['source'].startswith('暂按'): issue('opening_position',start,'期初持仓暂按0，请核对首笔交易前是否已有持仓',stock['stock_id'])
    def apply_entry(entry,day,collect):
        nonlocal cash
        sid=entry['stock_id'];change=entry['cash_change_cents']
        if cash is not None: cash+=change
        balance=raw_money(entry['raw_json'].get('资金余额'))
        unchanged=unchanged_source(entry,stocks)
        if balance is not None and unchanged and (cash_break is None or day<cash_break):
            if cash is not None and balance!=cash and collect:
                issue('cash_gap',day,'原始资金余额与逐笔结转不符，使用余额锚点并保留差额，不计入收益',difference_cents=balance-cash,entry_id=entry['id'])
            cash=balance
        delta=share_change(entry)
        if sid and delta:
            positions[sid]=positions.get(sid,0)+delta
            if positions[sid]<0:
                bad_positions.add(sid)
                issue('negative_position',day,'持仓数量不足，影响本次还原；请检查期初数量或缺失交易',sid,entry_id=entry['id'])
        if sid and entry['kind'] in ['buy','sell']:
            source_after=integer(entry['raw_json'].get('证券余额'))
            # Only compare unchanged imported economic fields; edits invalidate this historical anchor.
            if source_after is not None and unchanged and (sid not in position_breaks or day<position_breaks[sid]) and source_after!=positions.get(sid,0):
                bad_positions.add(sid)
                issue('position_gap',day,'证券余额与重建持仓不一致，影响本次还原；请检查送转股或缺失交易',sid,entry_id=entry['id'])
    for entry in entries:
        if entry['date']<start: apply_entry(entry,entry['date'],False)
    def value(sid,quantity,day,report_day):
        if quantity==0: return 0
        if quantity<0 or sid in bad_positions: return None
        index=bisect_right(calendar,day)-1
        expected=calendar[index] if index>=0 else None
        px=prices.get((sid,expected))
        if px is None:
            issue('missing_price',report_day,f'缺少{expected or day}的不复权收盘价，保留缺口',sid,price_date=expected or day)
            return None
        return int((px*quantity*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
    protected=protected_dates(conn);result=[]
    for day in days:
        before=dict(positions);previous=(date.fromisoformat(day)-timedelta(days=1)).isoformat()
        flows=defaultdict(int);income=defaultdict(int);other=0;expected=set(bad_positions)
        for sid,q in before.items():
            if q: expected.add(sid)
        for entry in by_date[day]:
            sid=entry['stock_id'];kind=entry['kind'];summary=entry['summary'];change=entry['cash_change_cents']
            apply_entry(entry,day,True)
            if sid and kind in ['buy','sell']: expected.add(sid);flows[sid]+=change
            elif kind=='other':
                if summary in ['红利入账','股息入账','现金红利','股息红利差异扣税','红利税扣款']:
                    if sid: expected.add(sid);income[sid]+=change
                    else: other+=change
                elif summary in ['利息归本','结息','资金利息']: other+=change
                elif summary in ['红股入账','股份转增','证券派发','送股入账']:
                    if sid: expected.add(sid)
                else: issue('unknown_event',day,'该资金事项尚未归类为收益，已保留现金变动，请核对资产范围',sid,summary=summary,entry_id=entry['id'])
        for sid,q in positions.items():
            if q: expected.add(sid)
        returns=[];complete=True;holdings=0;assets_complete=True
        for sid in sorted(expected):
            old=value(sid,before.get(sid,0),previous,day)
            current=value(sid,positions.get(sid,0),day,day)
            if current is None: assets_complete=False
            else: holdings+=current
            if old is None or current is None:
                complete=False;continue
            returns.append({'stock_id':sid,'pnl_cents':current-old+flows[sid]+income[sid]})
        if any(sid in bad_positions for sid in expected): complete=False;assets_complete=False
        total_assets=cash+holdings if cash is not None and assets_complete else None
        if total_assets is not None and (cash<0 or total_assets<cash):
            issue('asset_balance',day,'现金或持仓超出普通账户允许范围，资产快照暂不写入');total_assets=None
        result.append({'date':day,'returns':returns,'expected_stock_ids':sorted(expected),
                       'pnl_cents':sum(r['pnl_cents'] for r in returns)+other,'complete':complete,
                       'other_pnl_cents':other,'cash_cents':cash if total_assets is not None else None,
                       'holdings_cents':holdings if assets_complete else None,'total_assets_cents':total_assets,
                       'protected':day in protected,'position_count':sum(q>0 for q in positions.values())})
    return {'start':start,'end':end,'fingerprint':input_fingerprint(conn),'days':result,'issues':issues,'opening':opening,
            'summary':{'days':len(result),'complete_days':sum(d['complete'] for d in result),
                       'protected_days':sum(d['protected'] for d in result),'asset_days':sum(d['total_assets_cents'] is not None for d in result),
                       'return_rows':sum(len(d['returns']) for d in result),'pnl_cents':sum(d['pnl_cents'] for d in result),
                       'missing_prices':sum(i['type']=='missing_price' for i in issues),'issue_count':len(issues)}}

def apply_reconstruction(conn,preview):
    if input_fingerprint(conn)!=preview['fingerprint']: raise ValidationError('预览后数据已变化，请重新计算后再保存')
    protected=protected_dates(conn);saved=0;rows=0;run_id=uuid.uuid4().hex
    with conn:
        for day in preview['days']:
            d=day['date']
            if d in protected: continue
            conn.execute("DELETE FROM daily_returns WHERE date=? AND source='market_close'",(d,))
            for record in day['returns']:
                conn.execute("INSERT INTO daily_returns(date,stock_id,pnl_cents,source,note) VALUES (?,?,?,'market_close','交易流水与不复权收盘价还原')",(d,record['stock_id'],record['pnl_cents']));rows+=1
            status='confirmed' if day['complete'] else 'draft'
            if not day['returns'] and not day['other_pnl_cents'] and day['complete']: status='skip'
            conn.execute('INSERT INTO day_status(date,status,expected_stock_ids,note) VALUES (?,?,?,?) ON CONFLICT(date) DO UPDATE SET status=excluded.status,expected_stock_ids=excluded.expected_stock_ids,note=excluded.note',
                         (d,status,json.dumps(day['expected_stock_ids']),'行情自动还原；缺失数据保留缺口'))
            conn.execute('INSERT INTO daily_accounts(date,total_assets_cents,cash_cents,other_pnl_cents,note) VALUES (?,?,?,?,?) ON CONFLICT(date) DO UPDATE SET total_assets_cents=excluded.total_assets_cents,cash_cents=excluded.cash_cents,other_pnl_cents=excluded.other_pnl_cents,note=excluded.note',
                         (d,day['total_assets_cents'],day['cash_cents'],day['other_pnl_cents'],'依据已录流水结转现金、收盘价计算市值'))
            conn.execute('INSERT INTO calculation_days(date,run_id) VALUES (?,?) ON CONFLICT(date) DO UPDATE SET run_id=excluded.run_id,updated_at=CURRENT_TIMESTAMP',(d,run_id));saved+=1
        audit(conn,'reconstruction',run_id,'apply',None,{'start':preview['start'],'end':preview['end'],'days':saved,'rows':rows,'protected_days':len(protected)})
    return {'saved_days':saved,'saved_rows':rows,'protected_days':sum(d['date'] in protected for d in preview['days'])}
