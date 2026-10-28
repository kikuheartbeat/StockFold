from base64 import b64decode
from contextlib import closing
import argparse
import csv
from hashlib import sha256
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from http.client import HTTPConnection
import io
import json
import logging
import mimetypes
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time
import traceback
from urllib.parse import urlparse,parse_qs,unquote
import webbrowser
from .db import connect,initialize,settings,audit,industry_palette,SCHEMA_VERSION
from .validation import ValidationError,valid_date,cents
from .records import stock_list,sector_list,save_stock,save_sector,get_day,save_day,save_returns_batch,ledger_list,save_ledger,delete_ledger
from .analytics import build_dashboard
from .returns import dates_between,local_today
from .importer import preview_xlsx,commit_import,classification_catalog
from .backup import create_backup,validate_backup,restore_backup
from .market import last_closed_date
from .reconstruction import opening_state,apply_reconstruction,input_fingerprint
from .reconstruction_jobs import start_job,job_public

ROOT=Path(__file__).resolve().parent.parent
STATIC=Path(__file__).resolve().parent/'static'
MAX_BODY=48*1024*1024

def invalidate_calculations(server):
    for job in server.jobs.values():
        if job['state']=='ready':
            server.previews.pop(job.get('preview',{}).get('preview_token'),None)
            job['state']='stale';job['stage']='输入数据已更新，请重新获取行情并计算'

def make_server(data_dir,port=0,root=ROOT):
    data_dir=Path(data_dir).resolve();data_dir.mkdir(parents=True,exist_ok=True)
    db_path=data_dir/'stockfold.sqlite3'
    with closing(connect(db_path)) as conn:
        version=conn.execute('PRAGMA user_version').fetchone()[0]
        if 0<version<SCHEMA_VERSION:create_backup(conn,data_dir/'backups')
        initialize(conn,Path(root)/'resources')
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.daemon_threads=True
    server.data_dir=data_dir;server.db_path=db_path;server.root=Path(root).resolve()
    server.token=secrets.token_urlsafe(32);server.lock=threading.RLock();server.previews={}
    server.instance_id=sha256(str(data_dir).encode()).hexdigest()[:20]
    server.jobs={};server.active_job=None
    return server

class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'

    def log_message(self,format,*args):
        logging.info('%s %s',self.address_string(),format%args)

    def headers_common(self):
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")

    def respond(self,data,status=200,content_type='application/json; charset=utf-8',filename=None):
        if not isinstance(data,bytes): data=json.dumps(data,ensure_ascii=False,default=str).encode('utf8')
        self.send_response(status);self.headers_common()
        self.send_header('Content-Type',content_type);self.send_header('Content-Length',str(len(data)))
        if filename: self.send_header('Content-Disposition',f'attachment; filename="{filename}"')
        self.end_headers();self.wfile.write(data)

    def body(self):
        try: length=int(self.headers.get('Content-Length','0'))
        except ValueError: raise ValidationError('请求长度无效')
        if length<0 or length>MAX_BODY: raise ValidationError('请求体积过大')
        try:
            data=json.loads(self.rfile.read(length) or b'{}')
            if not isinstance(data,dict): raise ValueError()
            return data
        except (json.JSONDecodeError,UnicodeDecodeError,ValueError): raise ValidationError('请求应为 JSON 对象')

    def check_access(self,write=False):
        host=self.headers.get('Host','')
        allowed={f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
        if host not in allowed: return False
        if write:
            origin=self.headers.get('Origin')
            if origin and origin not in {f'http://{h}' for h in allowed}: return False
            if not secrets.compare_digest(self.headers.get('X-StockFold-Token',''),self.server.token): return False
        return True

    def do_GET(self): self.handle_request(False)
    def do_POST(self): self.handle_request(True)
    def do_PUT(self): self.handle_request(True)
    def do_DELETE(self): self.handle_request(True)

    def handle_request(self,write):
        if not self.check_access(write):
            self.respond({'error':'本机来源或会话校验未通过，请从程序页面重新操作'},403);return
        parsed=urlparse(self.path);path=unquote(parsed.path)
        args={k:v[0] for k,v in parse_qs(parsed.query).items()}
        try:
            if not path.startswith('/api/'):
                if write: self.respond({'error':'操作不支持'},405);return
                self.static_file(path);return
            payload=self.body() if write else {}
            if path=='/api/stock-history/sync' and self.command=='POST':
                from .stock_history import sync_stock_history
                self.respond(sync_stock_history(self.server,payload));return
            with self.server.lock:
                self.route(path,args,payload)
        except ValidationError as e: self.respond({'error':str(e)},400)
        except (ValueError,TypeError,KeyError) as e: self.respond({'error':f'参数无效：{e}'},400)
        except Exception:
            logging.error('Request failed\n%s',traceback.format_exc())
            self.respond({'error':'操作未完成，原数据已保留。请检查输入，或查看 data/server.log。'},500)

    def static_file(self,path):
        if path in ['/','/index.html']: path='/index.html'
        target=(STATIC/path.lstrip('/')).resolve()
        if not target.is_relative_to(STATIC.resolve()) or not target.is_file():
            self.respond({'error':'页面不存在'},404);return
        typ=mimetypes.guess_type(str(target))[0] or 'application/octet-stream'
        if target.suffix=='.js': typ='text/javascript'
        self.respond(target.read_bytes(),content_type=typ+'; charset=utf-8')

    def cache_preview(self,kind,value):
        now=time.time()
        self.server.previews={k:v for k,v in self.server.previews.items() if now-v['created']<1800}
        if len(self.server.previews)>=8:
            self.server.previews.pop(next(iter(self.server.previews)))
        token=secrets.token_urlsafe(18)
        self.server.previews[token]={'kind':kind,'value':value,'created':now}
        return token

    def get_preview(self,token,kind):
        item=self.server.previews.get(token)
        if not item or item['kind']!=kind or time.time()-item['created']>1800:
            raise ValidationError('预览已过期，请重新预览')
        return item['value']

    def route(self,path,args,p):
        method=self.command
        if path=='/api/reconstruction/start' and method=='POST':
            self.respond(start_job(self.server,p));return
        if path.startswith('/api/reconstruction/jobs/') and method=='GET':
            job=self.server.jobs.get(path.rsplit('/',1)[1])
            if not job: raise ValidationError('任务已结束或服务已重启，请重新计算')
            self.respond(job_public(job));return
        if path=='/api/health':
            self.respond({'app':'StockFold','instance_id':self.server.instance_id,'version':'1.1'});return
        if path=='/api/shutdown' and method=='POST':
            self.respond({'stopped':True});threading.Thread(target=self.server.shutdown,daemon=True).start();return
        if path=='/api/restore/preview' and method=='POST':
            content=decode_upload(p)
            info=validate_backup(content)
            info['preview_token']=self.cache_preview('restore',content)
            self.respond(info);return
        if path=='/api/restore/commit' and method=='POST':
            if any(job['state']=='running' for job in self.server.jobs.values()):raise ValidationError('请等待行情任务完成后再恢复备份')
            if p.get('confirmed') is not True: raise ValidationError('请明确确认恢复，此操作会替换当前数据')
            content=self.get_preview(p.get('token'),'restore')
            result=restore_backup(self.server.db_path,content,self.server.data_dir/'backups')
            self.server.previews.clear();self.server.jobs.clear();self.server.active_job=None;self.respond(result);return
        if path=='/api/backup/download':
            name=Path(args.get('name','')).name
            target=self.server.data_dir/'backups'/name
            if not name.startswith('stockfold-') or target.suffix!='.sqlite3' or not target.is_file(): raise ValidationError('备份不存在')
            self.respond(target.read_bytes(),content_type='application/octet-stream',filename=name);return
        with closing(connect(self.server.db_path)) as conn:
            if path=='/api/stock-history' and method=='GET':
                from .stock_history import stock_history
                self.respond(stock_history(conn,int(args.get('stock_id',0)),args.get('start'),args.get('end')));return
            if path=='/api/reconstruction/meta' and method=='GET':
                opening=opening_state(conn);config=settings(conn)
                self.respond({'opening':opening,'record_start':config['record_start'],'last_closed_date':last_closed_date(),
                              'default_end':min(opening['ledger_end'] or last_closed_date(),last_closed_date()),
                              'cached_prices':conn.execute('SELECT COUNT(*) FROM market_prices').fetchone()[0],
                              'last_job':job_public(self.server.jobs[self.server.active_job]) if self.server.active_job in self.server.jobs else None});return
            if path=='/api/reconstruction/apply' and method=='POST':
                if p.get('confirmed') is not True:raise ValidationError('请核对预览并明确确认保存')
                preview=self.get_preview(p.get('token'),'reconstruction')
                if input_fingerprint(conn)!=preview['fingerprint']:raise ValidationError('预览后数据已变化，请重新计算')
                backup=create_backup(conn,self.server.data_dir/'backups')
                result=apply_reconstruction(conn,preview);self.server.previews.pop(p.get('token'),None)
                for job in self.server.jobs.values():
                    if job.get('preview',{}).get('preview_token')==p.get('token'):
                        job['state']='applied';job['stage']='还原结果已保存，可在投资总览查看图表'
                self.respond({**result,'backup':backup.name});return
            if path=='/api/reconstruction/opening' and method=='PUT':
                positions=p.get('positions',[])
                if not isinstance(positions,list) or len(positions)>1000:raise ValidationError('期初持仓格式无效')
                with conn:
                    for item in positions:
                        sid=item.get('stock_id');quantity=item.get('quantity')
                        if type(quantity) is not int or quantity<0 or quantity>10**10:raise ValidationError('期初数量必须为非负整数')
                        if not conn.execute('SELECT 1 FROM stocks WHERE id=?',(sid,)).fetchone():raise ValidationError('股票不存在')
                        conn.execute('INSERT INTO opening_positions(stock_id,quantity) VALUES (?,?) ON CONFLICT(stock_id) DO UPDATE SET quantity=excluded.quantity',(sid,quantity))
                    cash=cents(p.get('cash_cents'),'期初现金',True)
                    if cash is not None and cash<0:raise ValidationError('期初现金不能为负')
                    if cash is None:conn.execute("DELETE FROM app_settings WHERE key='opening_cash_cents'")
                    else:conn.execute("INSERT INTO app_settings VALUES ('opening_cash_cents',?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",(json.dumps(cash),))
                    audit(conn,'opening','reconstruction','save',None,p)
                invalidate_calculations(self.server)
                self.respond(opening_state(conn));return
            if path=='/api/reconstruction/price' and method=='PUT':
                from .validation import price
                from decimal import Decimal
                day=valid_date(p.get('date'));px=price(p.get('close_decimal'));sid=p.get('stock_id')
                if day>last_closed_date() or Decimal(px)<=0:raise ValidationError('日期需已收盘，收盘价必须大于零')
                if not conn.execute('SELECT 1 FROM stocks WHERE id=?',(sid,)).fetchone():raise ValidationError('股票不存在')
                with conn:
                    conn.execute("INSERT INTO market_prices(stock_id,date,close_decimal,source) VALUES (?,?,?,'手工校准') ON CONFLICT(stock_id,date) DO UPDATE SET close_decimal=excluded.close_decimal,source=excluded.source,fetched_at=CURRENT_TIMESTAMP",(sid,day,px))
                    audit(conn,'market_price',f'{sid}:{day}','save',None,p)
                invalidate_calculations(self.server)
                self.respond({'saved':True});return
            if path=='/api/bootstrap':
                self.respond({'token':self.server.token,'stocks':stock_list(conn),'sectors':sector_list(conn),'settings':settings(conn),
                              'palette_groups':industry_palette()['groups'],
                              'data_dir':str(self.server.data_dir),'version':'1.1','today':__import__('app.returns',fromlist=['local_today']).local_today()});return
            if path=='/api/dashboard':
                self.respond(build_dashboard(conn,args.get('start'),args.get('end'),int(args.get('industry_level','2'))));return
            if path=='/api/stocks' and method=='GET': self.respond(stock_list(conn));return
            if path=='/api/stocks' and method=='POST': self.respond(save_stock(conn,p));return
            if path.startswith('/api/stocks/') and method=='PUT':
                self.respond(save_stock(conn,{**p,'id':int(path.rsplit('/',1)[1])}));return
            if path=='/api/sectors' and method=='GET': self.respond(sector_list(conn));return
            if path=='/api/sectors' and method=='POST': self.respond(save_sector(conn,p));return
            if path.startswith('/api/sectors/') and method=='PUT':
                self.respond(save_sector(conn,{**p,'id':int(path.rsplit('/',1)[1])},preview=p.get('preview') is True));return
            if path.startswith('/api/days/'):
                day=path.rsplit('/',1)[1]
                if method=='GET': self.respond(get_day(conn,day));return
                if method=='PUT': self.respond(save_day(conn,day,p));return
            if path=='/api/returns/batch' and method=='POST':
                self.respond(save_returns_batch(conn,p.get('rows'),confirm=p.get('confirm') is True));return
            if path=='/api/ledger':
                if method=='GET': self.respond(ledger_list(conn,start=args.get('start'),end=args.get('end')));return
                if method=='POST': self.respond(save_ledger(conn,p));return
            if path.startswith('/api/ledger/'):
                ident=int(path.rsplit('/',1)[1])
                if method=='PUT': self.respond(save_ledger(conn,{**p,'id':ident}));return
                if method=='DELETE': self.respond(delete_ledger(conn,ident));return
            if path=='/api/catalog':
                q=args.get('q','').strip().lower()
                self.respond([v for k,v in classification_catalog().items() if q and (q in k or q in v['name'].lower())][:25]);return
            if path=='/api/import/available':
                self.respond([{'name':f.name,'size':f.stat().st_size} for f in self.server.root.glob('*.xlsx') if f.is_file() and not f.name.startswith('~$')]);return
            if path=='/api/import/preview' and method=='POST':
                if p.get('existing_name'):
                    name=p['existing_name']
                    if not isinstance(name,str) or name!=Path(name).name: raise ValidationError('文件名称无效')
                    target=self.server.root/name
                    if target.suffix.lower()!='.xlsx' or not target.is_file(): raise ValidationError('找不到该Excel文件')
                    content=target.read_bytes()
                else: name=p.get('file_name','上传.xlsx');content=decode_upload(p)
                preview=preview_xlsx(conn,content,name)
                token=self.cache_preview('import',preview)
                self.respond({**{k:v for k,v in preview.items() if k!='records'},'preview_token':token,
                              'sample':[{'date':r['date'],'code':r['code'],'name':r['name'],'summary':r['summary'],'cash_change_cents':r['cash_change_cents']} for r in preview['records'][:8]]});return
            if path=='/api/import/commit' and method=='POST':
                value=self.get_preview(p.get('token'),'import')
                self.respond(commit_import(conn,value,p.get('allow_overlap') is True));
                self.server.previews.pop(p.get('token'),None);return
            if path=='/api/backup' and method=='POST':
                file=create_backup(conn,self.server.data_dir/'backups')
                self.respond({'name':file.name,'download_url':f'/api/backup/download?name={file.name}','bytes':file.stat().st_size});return
            if path=='/api/backups':
                folder=self.server.data_dir/'backups'
                files=sorted(folder.glob('stockfold-*.sqlite3'),reverse=True) if folder.exists() else []
                self.respond([{'name':f.name,'bytes':f.stat().st_size,'download_url':f'/api/backup/download?name={f.name}'} for f in files[:30]]);return
            if path=='/api/settings' and method=='PUT':
                record_start=valid_date(p.get('record_start'))
                if record_start>local_today(): raise ValidationError('收益记录起点不能晚于今天')
                dates_between(record_start,local_today())
                with conn:
                    conn.execute('INSERT INTO app_settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json',('record_start',json.dumps(record_start)))
                    audit(conn,'settings','record_start','update',None,record_start)
                self.respond(settings(conn));return
            if path=='/api/export':
                if args.get('format')=='csv':
                    self.export_csv(conn);return
                result={table:[dict(r) for r in conn.execute(f'SELECT * FROM {table}')] for table in ['stocks','sectors','daily_returns','daily_accounts','day_status','ledger_entries','import_batches','import_rows','app_settings','change_log','market_prices','market_sync','market_calendar','calendar_sync','opening_positions','calculation_days']}
                self.respond(json.dumps({'app':'StockFold','schema_version':SCHEMA_VERSION,'data':result},ensure_ascii=False).encode(),filename='stockfold-export.json');return
            self.respond({'error':'接口不存在或操作不支持'},404)

    def export_csv(self,conn):
        stream=io.StringIO(newline='');writer=csv.writer(stream)
        writer.writerow(['日期','证券代码','证券名称','一级行业','二级行业','当日收益（元）','确认状态','备注'])
        sql='''SELECT r.*,s.code,s.name,c.name second_level,p.name first_level,d.status FROM daily_returns r JOIN stocks s ON s.id=r.stock_id LEFT JOIN sectors c ON c.id=s.sector_id LEFT JOIN sectors p ON p.id=c.parent_id LEFT JOIN day_status d ON d.date=r.date ORDER BY r.date,s.code'''
        safe=lambda v:("'"+str(v)) if str(v).lstrip().startswith(('=','+','-','@','\t','\r')) else v
        for row in conn.execute(sql):
            writer.writerow([row['date'],safe(row['code']),safe(row['name']),safe(row['first_level'] or ''),safe(row['second_level'] or ''),f"{row['pnl_cents']/100:.2f}",row['status'],safe(row['note'])])
        self.respond(b'\xef\xbb\xbf'+stream.getvalue().encode('utf8'),content_type='text/csv; charset=utf-8',filename='stockfold-daily-returns.csv')

def decode_upload(p):
    try:
        content=b64decode(p.get('content_base64',''),validate=True)
        if not content: raise ValueError()
        return content
    except (ValueError,TypeError): raise ValidationError('上传内容无效，请重新选择文件')

def find_running_instance(info,instance):
    try:
        port=int(info['port'])
        connection=HTTPConnection('127.0.0.1',port,timeout=2)
        try:
            connection.request('GET','/api/health')
            response=connection.getresponse()
            health=json.loads(response.read())
            if response.status==200 and health.get('app')=='StockFold' and health.get('instance_id')==instance:
                return f'http://127.0.0.1:{port}'
        finally: connection.close()
    except (OSError,ValueError,KeyError,TypeError): return None
    return None

class InstanceLock:
    """An OS-owned lifetime lock; automatically released if a process crashes."""
    def __init__(self,data_dir):
        self.path=Path(data_dir)/'.instance.lock';self.handle=None

    def acquire(self):
        if self.handle: return True
        handle=open(self.path,'a+b')
        try:
            if handle.seek(0,2)==0: handle.write(b'0');handle.flush()
            handle.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.handle=handle;return True
        except OSError:
            handle.close();return False

    def release(self):
        if not self.handle: return
        try:
            self.handle.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.handle.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(),fcntl.LOCK_UN)
        finally: self.handle.close();self.handle=None

def run(host='127.0.0.1',port=0,open_browser=True,data_dir=None):
    if host!='127.0.0.1': raise ValueError('StockFold 仅允许本机监听')
    data_dir=Path(data_dir or ROOT/'data').resolve();data_dir.mkdir(parents=True,exist_ok=True)
    info_file=data_dir/'runtime.json'
    instance=sha256(str(data_dir).encode()).hexdigest()[:20]
    lock=InstanceLock(data_dir);deadline=time.monotonic()+15
    while not lock.acquire():
        try: url=find_running_instance(json.loads(info_file.read_text(encoding='utf8')),instance)
        except (OSError,ValueError): url=None
        if url:
            if open_browser: webbrowser.open(url)
            print(url,flush=True);return
        if time.monotonic()>=deadline: raise RuntimeError('已有实例正在启动或退出，请稍后再试')
        time.sleep(.1)
    server=None
    try:
        logging.basicConfig(filename=data_dir/'server.log',encoding='utf8',level=logging.INFO,format='%(asctime)s %(message)s')
        server=make_server(data_dir,port,ROOT)
        info_file.write_text(json.dumps({'port':server.server_port,'pid':os.getpid(),'instance_id':instance}),encoding='utf8')
        url=f'http://127.0.0.1:{server.server_port}'
        print(url,flush=True)
        if open_browser: webbrowser.open(url)
        try: server.serve_forever()
        except KeyboardInterrupt: pass
    finally:
        if server: server.server_close()
        try:
            if json.loads(info_file.read_text(encoding='utf8')).get('pid')==os.getpid(): info_file.unlink()
        except (FileNotFoundError,ValueError): pass
        lock.release()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description='StockFold 本地复盘程序')
    parser.add_argument('--port',type=int,default=0);parser.add_argument('--data-dir')
    parser.add_argument('--no-browser',action='store_true')
    args=parser.parse_args()
    run(port=args.port,data_dir=args.data_dir,open_browser=not args.no_browser)
