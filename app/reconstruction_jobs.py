from contextlib import closing
from datetime import date,timedelta
import json
import secrets
import threading
import time
from .db import connect,settings
from .market import fetch_history,covered,cache_quotes,last_closed_date,SOURCE
from .reconstruction import market_requests,reconstruct,input_fingerprint,opening_state
from .validation import ValidationError,valid_date
from .returns import dates_between

def job_public(job):
    return {k:v for k,v in job.items() if k!='thread'}

def start_job(server,payload):
    if server.active_job and server.jobs[server.active_job]['state']=='running':
        raise ValidationError('已有行情任务正在进行，请等待完成')
    with closing(connect(server.db_path)) as conn:
        config=settings(conn);opening=opening_state(conn)
        start=valid_date(payload.get('start') or config['record_start'])
        end=valid_date(payload.get('end') or min(opening['ledger_end'] or last_closed_date(),last_closed_date()))
        dates_between(start,end)
        if end>last_closed_date(): raise ValidationError('所选结束日期尚无已确认收盘价，请在16:30后更新或选择更早日期')
        requests=market_requests(conn,start,end)
        if not requests and not opening['ledger_start'] and opening['cash_cents'] is None:
            raise ValidationError('请先导入交易流水或填写期初现金')
        fingerprint=input_fingerprint(conn,False)
    ident=secrets.token_urlsafe(16)
    if len(server.jobs)>=5:
        for key in list(server.jobs):
            if server.jobs[key]['state']!='running':server.jobs.pop(key);break
    job={'id':ident,'state':'running','stage':'正在准备交易日历','completed':0,'total':len(requests)+1,'errors':[],
         'start':start,'end':end,'started_at':time.time()}
    server.jobs[ident]=job;server.active_job=ident
    thread=threading.Thread(target=run_job,args=(server,job,requests,fingerprint,payload.get('force') is True),daemon=True)
    job['thread']=thread;thread.start()
    return job_public(job)

def run_job(server,job,requests,fingerprint,force):
    def update(**values):
        with server.lock: job.update(values)
    try:
        fetcher=getattr(server,'market_fetcher',fetch_history)
        calendar_start=min([r['start'] for r in requests]+[(date.fromisoformat(job['start'])-timedelta(days=40)).isoformat()]);end=job['end']
        with server.lock,closing(connect(server.db_path)) as conn:
            span=conn.execute('SELECT * FROM calendar_sync WHERE id=1').fetchone()
            have_calendar=span and span['start_date']<=calendar_start and span['end_date']>=end and not force
        if not have_calendar:
            # Fetch beyond a historical end to distinguish a holiday from a missing final bar.
            fetch_end=last_closed_date()
            calendar=fetcher({'code':'000001','market':'SH'},calendar_start,fetch_end)
            if not calendar: raise ValidationError('无法取得交易日历，未猜测休市日')
            verified_end=max(r['date'] for r in calendar)
            while verified_end<fetch_end:
                next_day=date.fromisoformat(verified_end)+timedelta(days=1)
                if next_day.weekday()<5: break
                verified_end=next_day.isoformat()
            if end>verified_end: raise ValidationError(f'交易日历尚未确认到{end}，行情最近可核对至{verified_end}，请缩短结束日期后重试')
            with server.lock,closing(connect(server.db_path)) as conn,conn:
                for r in calendar:
                    conn.execute('INSERT INTO market_calendar(date,source) VALUES (?,?) ON CONFLICT(date) DO UPDATE SET source=excluded.source,updated_at=CURRENT_TIMESTAMP',(valid_date(r['date']),r.get('source',SOURCE)))
                conn.execute('INSERT INTO calendar_sync VALUES (1,?,?) ON CONFLICT(id) DO UPDATE SET start_date=excluded.start_date,end_date=excluded.end_date',(calendar_start,verified_end))
        update(completed=1)
        for index,stock in enumerate(requests):
            update(stage=f"正在获取 {stock['code']} · {stock['name']}")
            try:
                with server.lock,closing(connect(server.db_path)) as conn:
                    have=covered(conn,stock['stock_id'],stock['start'],stock['end']) and not force
                if not have:
                    data=fetcher(stock,stock['start'],stock['end'])
                    with server.lock,closing(connect(server.db_path)) as conn:
                        identity=conn.execute('SELECT code,market FROM stocks WHERE id=?',(stock['stock_id'],)).fetchone()
                        if not identity or identity['code']!=stock['code'] or identity['market']!=stock['market']:
                            raise ValidationError('获取期间证券代码或市场已变化，请重新计算')
                        cache_quotes(conn,stock['stock_id'],data,stock['start'],stock['end'])
            except (OSError,ValueError) as exc:
                with server.lock: job['errors'].append({'code':stock['code'],'name':stock['name'],'message':str(exc)[:250]})
            update(completed=index+2)
        update(stage='正在按流水还原持仓与资金')
        with server.lock,closing(connect(server.db_path)) as conn:
            if input_fingerprint(conn,False)!=fingerprint: raise ValidationError('行情获取期间流水或手工数据发生变化，请重新计算')
            preview=reconstruct(conn,job['start'],end)
            token=secrets.token_urlsafe(18)
            server.previews[token]={'kind':'reconstruction','created':time.time(),'value':preview}
            preview_public={'summary':preview['summary'],'opening':preview['opening'],
                            'issues':preview['issues'][:1000],
                            'days':[{k:v for k,v in d.items() if k not in ['returns','expected_stock_ids']} for d in preview['days']],
                            'preview_token':token,'start':job['start'],'end':end}
        update(state='ready',stage='计算预览已生成，请核对后保存',preview=preview_public)
    except Exception as exc:
        update(state='error',stage='本次未生成可保存的结果',error=str(exc)[:400])
