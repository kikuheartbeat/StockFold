from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import json
from .validation import ValidationError, valid_date

PROFIT='#D14343'
LOSS='#16845B'
NEUTRAL='#94A3B8'

def local_today():
    return datetime.now(timezone(timedelta(hours=8))).date().isoformat()

def dates_between(start,end):
    a=date.fromisoformat(valid_date(start)); b=date.fromisoformat(valid_date(end))
    if b<a: raise ValidationError('结束日期不能早于开始日期')
    if (b-a).days>7305: raise ValidationError('记录跨度请控制在20年以内')
    return [(a+timedelta(days=i)).isoformat() for i in range((b-a).days+1)]

def pnl_color(pnl,confirmed=True):
    if not confirmed or pnl is None: return NEUTRAL
    return PROFIT if pnl>0 else LOSS if pnl<0 else NEUTRAL

def build_returns(conn,record_start,end,stocks):
    dates=dates_between(record_start,end)
    daily=defaultdict(dict)
    for r in conn.execute('SELECT * FROM daily_returns WHERE date>=? AND date<=?',(record_start,end)):
        daily[r['date']][r['stock_id']]=r['pnl_cents']
    accounts={r['date']:dict(r) for r in conn.execute('SELECT * FROM daily_accounts WHERE date>=? AND date<=?',(record_start,end))}
    statuses={r['date']:dict(r) for r in conn.execute('SELECT * FROM day_status WHERE date>=? AND date<=?',(record_start,end))}
    has_auto=conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='calculation_days'").fetchone()
    automatic={r[0] for r in conn.execute('SELECT date FROM calculation_days WHERE date>=? AND date<=?',(record_start,end))} if has_auto else set()
    running=defaultdict(int)
    other_total=0
    total_series=[]
    series={s['id']:{**s,'points':[]} for s in stocks}
    gap_before=False
    cumulative_complete=True
    stock_gaps=defaultdict(bool)
    for day in dates:
        status=statuses.get(day,{}).get('status')
        known=status in ['confirmed','skip']
        day_stock=daily.get(day,{})
        expected=set(json.loads(statuses.get(day,{}).get('expected_stock_ids','[]')))
        other=accounts.get(day,{}).get('other_pnl_cents',0)
        day_pnl=sum(day_stock.values())+other
        for sid,amount in day_stock.items(): running[sid]+=amount
        other_total+=other
        if not known: cumulative_complete=False
        total=sum(running.values())+other_total
        point={'date':day,'value_cents':total if known else None,
               'recorded_cumulative_cents':total,'daily_cents':day_pnl if known else None,
               'recorded_daily_cents':day_pnl,'status':status or 'missing','gap_before':gap_before,
               'cumulative_complete':cumulative_complete,'color':pnl_color(day_pnl,known)}
        total_series.append(point)
        for sid,item in series.items():
            stock_known=known or (day in automatic and (sid in day_stock or sid not in expected))
            item['points'].append({'date':day,'value_cents':running[sid] if stock_known else None,
                                   'daily_cents':day_stock.get(sid,0) if stock_known else None,
                                   'gap_before':stock_gaps[sid],'status':('confirmed' if stock_known else status or 'missing')})
            stock_gaps[sid]=not stock_known
        gap_before=not known
    return {'dates':dates,'daily':daily,'accounts':accounts,'statuses':statuses,
            'total_series':total_series,'series':list(series.values())}
