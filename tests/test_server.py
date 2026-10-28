import base64
import http.client
import json
from pathlib import Path
import threading
import time
import unittest
from .test_records import DatabaseFixture,ROOT
from app.server import make_server,find_running_instance

class ServerTest(DatabaseFixture):
    def setUp(self):
        super().setUp()
        self.server=make_server(Path(self.tmp.name)/'http',port=0,root=ROOT)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.port=self.server.server_address[1]
        self.token=self.call('GET','/api/bootstrap')[1]['token']

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join(3)
        super().tearDown()

    def call(self,method,path,data=None,headers=None):
        h={'Content-Type':'application/json',**(headers or {})}
        if hasattr(self,'token') and method!='GET': h.setdefault('X-StockFold-Token',self.token)
        c=http.client.HTTPConnection('127.0.0.1',self.port,timeout=10)
        c.request(method,path,json.dumps(data).encode() if data is not None else None,h)
        r=c.getresponse();body=r.read();status=r.status;typ=r.getheader('Content-Type','');c.close()
        return status,json.loads(body) if 'application/json' in typ else body

    def test_stock_history_sync_only_changes_prices_and_provides_calendar(self):
        _,stock=self.call('POST','/api/stocks',{'code':'600118','name':'中国卫星','market':'SH'})
        self.call('POST','/api/ledger',{'date':'2026-01-06','kind':'buy','stock_id':stock['id'],'quantity':100,'price_decimal':'10'})
        self.call('PUT','/api/days/2026-01-06',{'returns':[{'stock_id':stock['id'],'pnl_cents':123}], 'status':'confirmed'})
        calls=[]
        def fetch(stock,start,end):
            calls.append(stock['code'])
            return [{'date':day,'close_decimal':'10.25','source':'test'} for day in ['2026-01-05','2026-01-06','2026-01-09','2026-01-12'] if start<=day<=end]
        self.server.market_fetcher=fetch
        query=f'/api/stock-history?stock_id={stock["id"]}&start=2026-01-05&end=2026-01-12'
        self.assertEqual(self.call('GET',query)[0],200)
        self.assertEqual(calls,[])
        status,data=self.call('POST','/api/stock-history/sync',{'stock_id':stock['id'],'start':'2026-01-05','end':'2026-01-12'})
        self.assertEqual(status,200,data)
        self.assertEqual(data['points'][0]['close'],10.25)
        self.assertTrue(data['points'][5]['closed'])
        self.assertEqual(data['intervals'],[{'start':'2026-01-06','end':None}])
        self.assertEqual(self.call('GET','/api/days/2026-01-06')[1]['returns'][0]['pnl_cents'],123)
        self.assertEqual(self.call('GET',query)[1]['points'],data['points'])
        self.assertEqual(self.call('GET','/api/stock-history?stock_id=999&start=2026-01-05&end=2026-01-12')[0],400)

    def test_foreign_origin_and_missing_token_rejected(self):
        status,_=self.call('POST','/api/backup',{}, {'Origin':'https://evil.example'})
        self.assertEqual(status,403)
        token=self.token;del self.token
        self.assertEqual(self.call('POST','/api/backup',{})[0],403)
        self.token=token

    def test_save_read_day_and_invalid_static_path(self):
        status,s=self.call('POST','/api/stocks',{'code':'600118','name':'中国卫星','market':'SH'})
        self.assertEqual(status,200)
        p={'returns':[{'stock_id':s['id'],'pnl_cents':123}], 'status':'confirmed'}
        self.assertEqual(self.call('PUT','/api/days/2026-10-21',p)[0],200)
        self.assertEqual(self.call('GET','/api/days/2026-10-21')[1]['returns'][0]['pnl_cents'],123)
        self.assertNotEqual(self.call('GET','/../app/server.py')[0],200)


    def test_existing_instance_uses_direct_local_connection(self):
        info={'port':self.port,'instance_id':self.server.instance_id}
        self.assertEqual(find_running_instance(info,self.server.instance_id),f'http://127.0.0.1:{self.port}')

    def test_available_files_ignore_office_lockfiles(self):
        folder=Path(self.tmp.name)/'files';folder.mkdir()
        (folder/'real.xlsx').write_bytes(b'test');(folder/'~$real.xlsx').write_bytes(b'lock')
        self.server.root=folder
        self.assertEqual([f['name'] for f in self.call('GET','/api/import/available')[1]],['real.xlsx'])

    def test_downloaded_backup_preview_and_restore_round_trip(self):
        _,stock=self.call('POST','/api/stocks',{'code':'600118','name':'中国卫星','market':'SH'})
        payload={'status':'confirmed','returns':[{'stock_id':stock['id'],'pnl_cents':123}]}
        self.assertEqual(self.call('PUT','/api/days/2026-10-21',payload)[0],200)
        status,backup=self.call('POST','/api/backup',{})
        self.assertEqual(status,200)
        status,content=self.call('GET',backup['download_url'])
        self.assertEqual(status,200);self.assertTrue(content.startswith(b'SQLite format 3'))
        payload['returns'][0]['pnl_cents']=999
        self.call('PUT','/api/days/2026-10-21',payload)
        status,preview=self.call('POST','/api/restore/preview',{'content_base64':base64.b64encode(content).decode()})
        self.assertEqual(status,200);self.assertEqual(preview['record_count'],1)
        token=preview['preview_token']
        self.assertEqual(self.call('POST','/api/restore/commit',{'token':token})[0],400)
        status,result=self.call('POST','/api/restore/commit',{'token':token,'confirmed':True})
        self.assertEqual(status,200);self.assertTrue(result['safety_backup'])
        self.assertEqual(self.call('GET','/api/days/2026-10-21')[1]['returns'][0]['pnl_cents'],123)

    def test_invalid_record_start_does_not_break_dashboard(self):
        previous=self.call('GET','/api/bootstrap')[1]['settings']['record_start']
        for invalid in ['9999-12-31','1900-01-01']:
            self.assertEqual(self.call('PUT','/api/settings',{'record_start':invalid})[0],400)
            self.assertEqual(self.call('GET','/api/bootstrap')[1]['settings']['record_start'],previous)
            self.assertEqual(self.call('GET','/api/dashboard')[0],200)

    def test_auto_reconstruction_job_preview_apply_and_backup(self):
        _,stock=self.call('POST','/api/stocks',{'code':'600118','name':'中国卫星','market':'SH'})
        status,_=self.call('PUT','/api/reconstruction/opening',{'positions':[{'stock_id':stock['id'],'quantity':0}],'cash_cents':2000000})
        self.assertEqual(status,200)
        for day,kind,px in [('2026-01-05','buy','10'),('2026-01-07','sell','10.4')]:
            self.assertEqual(self.call('POST','/api/ledger',{'date':day,'kind':kind,'stock_id':stock['id'],'quantity':1000,'price_decimal':px,'fees_cents':500})[0],200)
        def fetch(stock,start,end):
            return [{'date':day,'close_decimal':px,'source':'HTTP test'} for day,px in [('2026-01-02','10'),('2026-01-05','10.2'),('2026-01-06','10.5'),('2026-01-07','10.4')] if start<=day<=end]
        self.server.market_fetcher=fetch
        status,job=self.call('POST','/api/reconstruction/start',{'start':'2026-01-05','end':'2026-01-07'})
        self.assertEqual(status,200);deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            status,job=self.call('GET','/api/reconstruction/jobs/'+job['id'])
            if job['state']!='running':break
            time.sleep(.02)
        self.assertEqual(job['state'],'ready',job)
        self.assertEqual(job['preview']['summary']['pnl_cents'],39000)
        token=job['preview']['preview_token']
        self.assertEqual(self.call('POST','/api/reconstruction/apply',{'token':token})[0],400)
        status,result=self.call('POST','/api/reconstruction/apply',{'token':token,'confirmed':True})
        self.assertEqual(status,200);self.assertEqual(result['saved_days'],3);self.assertTrue(result['backup'])
        self.assertEqual(self.call('GET','/api/dashboard?start=2026-01-05&end=2026-01-07')[1]['summary']['period_pnl_cents'],39000)

    def test_background_market_request_does_not_hold_server_lock(self):
        _,stock=self.call('POST','/api/stocks',{'code':'600118','name':'中国卫星','market':'SH'})
        self.call('POST','/api/ledger',{'date':'2026-01-05','kind':'buy','stock_id':stock['id'],'quantity':100,'price_decimal':'10'})
        entered=threading.Event();release=threading.Event()
        def slow(stock,start,end):
            entered.set();release.wait(3);return []
        self.server.market_fetcher=slow
        self.call('POST','/api/reconstruction/start',{'start':'2026-01-05','end':'2026-01-06'})
        try:
            self.assertTrue(entered.wait(1))
            t=time.monotonic();self.assertEqual(self.call('GET','/api/bootstrap')[0],200)
            self.assertLess(time.monotonic()-t,1)
        finally:release.set()

if __name__=='__main__': unittest.main()
