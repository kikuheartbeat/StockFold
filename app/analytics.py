from collections import defaultdict
from datetime import date,timedelta
from .db import settings
from .records import stock_list,ledger_list
from .returns import build_returns,dates_between,local_today,pnl_color
from .holding_curves import holding_curves
from .holding_values import holding_values
from .stock_history import history_candidates
from .validation import ValidationError,valid_date

def build_dashboard(conn,start=None,end=None,industry_level=2):
    if industry_level not in [1,2]: raise ValidationError('行业层级应为1或2')
    config=settings(conn)
    record_start=config.get('record_start','2026-01-01')
    end=valid_date(end or local_today())
    if end<record_start: raise ValidationError('结束日期不能早于收益记录起点')
    start=valid_date(start or max(record_start,(date.fromisoformat(end)-timedelta(days=89)).isoformat()))
    if start<record_start: start=record_start
    dates_between(start,end)
    stocks=stock_list(conn)
    full=build_returns(conn,record_start,end,stocks)
    total=[p for p in full['total_series'] if p['date']>=start]
    dates=[p['date'] for p in total]
    series=[]
    for s in full['series']:
        points=[p for p in s['points'] if p['date']>=start]
        period=sum(full['daily'].get(day,{}).get(s['id'],0) for day in dates)
        cumulative=sum(r['pnl_cents'] for r in conn.execute('SELECT pnl_cents FROM daily_returns WHERE stock_id=? AND date>=? AND date<=?',(s['id'],record_start,end)))
        has_data=bool(conn.execute('SELECT 1 FROM daily_returns WHERE stock_id=? AND date>=? AND date<=? LIMIT 1',(s['id'],record_start,end)).fetchone())
        series.append({**s,'points':points,'period_pnl_cents':period,'cumulative_pnl_cents':cumulative,'has_data':has_data})
    curves=holding_curves(conn,dates,series,full['daily'])
    for s in series:
        s.update(curves[s['id']])
    groups={}
    sector_rows={r['id']:dict(r) for r in conn.execute('SELECT * FROM sectors')}
    for s in series:
        if not s['has_data']: continue
        if s['asset_type']=='stock' and s['sector_id']:
            child=sector_rows[s['sector_id']]
            chosen=child if industry_level==2 else sector_rows[child['parent_id']]
            key=f"industry:{chosen['id']}"; name=chosen['name']; color=chosen['color']
            parent=sector_rows.get(child['parent_id'],{})
            parent_name=parent.get('name','')
        elif s['asset_type']=='etf':
            category=s.get('fund_category') or '未分类'
            theme=s.get('fund_theme') or '未分类'
            name=f"ETF · {theme if industry_level==2 else category}"
            key=name; color='#6473B4'; parent_name=f'ETF / {category}'
        elif s['asset_type']=='product':
            key='product';name='资管产品';color='#A67C37';parent_name='独立资产类别'
        else:
            key='unclassified';name='未分类';color='#64748B';parent_name='未分类'
        group=groups.setdefault(key,{'id':key,'name':name,'color':color,'parent_name':parent_name,'pnl_cents':0,'stock_ids':[],'stock_names':[]})
        group['pnl_cents']+=s['period_pnl_cents'];group['stock_ids'].append(s['id']);group['stock_names'].append(s['name'])
    ledger=ledger_list(conn,start=record_start,end=end)
    transfers=defaultdict(list)
    other_entries=defaultdict(int)
    for entry in ledger:
        if entry['kind'] in ['deposit','withdraw']: transfers[entry['date']].append(entry)
        elif entry['kind']=='other': other_entries[entry['date']]+=1
    points={p['date']:p for p in full['total_series']}
    assets=[]
    positions=holding_values(conn,dates,stocks)
    for day in dates:
        a=full['accounts'].get(day,{})
        p=points[day]
        net=sum(e['cash_change_cents'] for e in transfers.get(day,[]))
        total_assets=a.get('total_assets_cents');cash=a.get('cash_cents')
        assets.append({'date':day,'total_assets_cents':total_assets,'cash_cents':cash,
                       'holdings_cents':total_assets-cash if total_assets is not None and cash is not None else None,
                       'daily_cents':p['daily_cents'],'color':p['color'],'positions':positions[day],
                       'transfers':transfers.get(day,[]),'net_transfer_cents':net})
    reconciliations=[]
    snapshots=sorted((d,a) for d,a in full['accounts'].items() if a.get('total_assets_cents') is not None)
    for (a_day,a),(b_day,b) in zip(snapshots,snapshots[1:]):
        if b_day<start: continue
        period=[d for d in full['dates'] if a_day<d<=b_day]
        complete=all(points[d]['status'] in ['confirmed','skip'] for d in period)
        unknown=sum(other_entries[d] for d in period)
        net=sum(e['cash_change_cents'] for d in period for e in transfers.get(d,[]))
        profit=sum(points[d]['recorded_daily_cents'] for d in period)
        difference=b['total_assets_cents']-a['total_assets_cents']-net-profit
        status='incomplete' if not complete else 'review' if unknown else 'ok' if abs(difference)<=1 else 'difference'
        reconciliations.append({'start':a_day,'end':b_day,'status':status,
                                'difference_cents':difference if complete else None,
                                'net_transfer_cents':net,'pnl_cents':profit,'other_entries':unknown})
    known_count=conn.execute('SELECT COUNT(*) FROM daily_returns WHERE date>=? AND date<=?',(record_start,end)).fetchone()[0]
    latest_asset=next((a for a in reversed(assets) if a['total_assets_cents'] is not None),None)
    missing=[p['date'] for p in total if p['status'] not in ['confirmed','skip']]
    all_missing=[p['date'] for p in full['total_series'] if p['status'] not in ['confirmed','skip']]
    import_count=conn.execute('SELECT COUNT(*) FROM ledger_entries WHERE import_row_id IS NOT NULL').fetchone()[0]
    unclassified_count=sum(s['asset_type']=='stock' and not s['sector_id'] for s in stocks)
    other_pnl=sum(full['accounts'].get(day,{}).get('other_pnl_cents',0) for day in dates)
    has_other=any(a.get('other_pnl_cents',0)!=0 for a in full['accounts'].values())
    return {
        'metadata':{'record_start':record_start,'start':start,'end':end,'industry_level':industry_level,'currency':'CNY','today':local_today()},
        'summary':{'recorded_cumulative_cents':full['total_series'][-1]['recorded_cumulative_cents'] if full['total_series'] else 0,
                   'period_pnl_cents':sum(p['recorded_daily_cents'] for p in total),'latest_daily_cents':next((p['daily_cents'] for p in reversed(total) if p['daily_cents'] is not None),None),
                   'other_pnl_cents':other_pnl,'latest_assets_cents':latest_asset['total_assets_cents'] if latest_asset else None,
                   'latest_cash_cents':latest_asset['cash_cents'] if latest_asset else None,
                   'latest_asset_date':latest_asset['date'] if latest_asset else None,
                   'stock_count':len(stocks),'record_count':known_count,'ledger_count':len(ledger),'import_count':import_count},
        'dates':dates,'total_series':total,'series':series,'assets':assets,
        'history_candidates':history_candidates(conn),
        'sectors':sorted(groups.values(),key=lambda g:g['pnl_cents'],reverse=True),
        'coverage':{'complete':not all_missing,'missing_dates':missing,'missing_count':len(all_missing),
                    'confirmed_count':sum(p['status']=='confirmed' for p in total),
                    'unclassified_count':unclassified_count,'has_returns':known_count>0 or has_other},
        'reconciliation':reconciliations[-20:],
    }
