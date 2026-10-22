"""Regression cases found during independent reconstruction review."""
import json
import threading
from types import SimpleNamespace
from unittest.mock import patch
from .test_records import DatabaseFixture
from app.records import save_ledger,save_stock
from app.market import cache_quotes,covered
from app.reconstruction import opening_state,reconstruct
from app.reconstruction_jobs import start_job,run_job


class AutoReviewTest(DatabaseFixture):
    def setUp(self):
        super().setUp()
        with self.conn:
            self.conn.execute("INSERT INTO app_settings VALUES ('opening_cash_cents','2000000')")
            self.conn.execute('INSERT INTO opening_positions(stock_id,quantity) VALUES (?,0)',(self.stock['id'],))
            for day,px in [('2026-01-02','10'),('2026-01-05','10.20'),('2026-01-06','10.50'),('2026-01-07','10.60')]:
                self.conn.execute("INSERT INTO market_calendar(date,source) VALUES (?,'test')",(day,))
                self.conn.execute("INSERT INTO market_prices(stock_id,date,close_decimal,source) VALUES (?,?,?,'test')",(self.stock['id'],day,px))
            self.conn.execute("INSERT INTO calendar_sync VALUES (1,'2025-12-01','2026-01-08')")

    def trade(self,day,kind,qty,px):
        return save_ledger(self.conn,{'date':day,'kind':kind,'stock_id':self.stock['id'],'quantity':qty,'price_decimal':px})

    def preview(self,end): return reconstruct(self.conn,'2026-01-05',end)
    def attach(self,entry,raw):
        with self.conn:
            batch=self.conn.execute("INSERT INTO import_batches(file_name,file_hash,record_count) VALUES ('source',?,1)",(str(entry['id']),)).lastrowid
            normalized={k:entry[k] for k in ['date','kind','summary','quantity','cash_change_cents','price_decimal','amount_cents','fees_cents']}
            normalized['code']=self.stock['code']
            row=self.conn.execute('INSERT INTO import_rows(batch_id,row_number,raw_json,normalized_json) VALUES (?,?,?,?)',(batch,1,json.dumps(raw),json.dumps(normalized))).lastrowid
            self.conn.execute('UPDATE ledger_entries SET import_row_id=? WHERE id=?',(row,entry['id']))

    def test_edited_first_import_does_not_manufacture_opening_balances(self):
        entry=self.trade('2026-01-05','buy',100,'10')
        self.attach(entry,{'证券余额':'100','资金余额':'1000'})
        with self.conn:
            self.conn.execute('DELETE FROM opening_positions')
            self.conn.execute("DELETE FROM app_settings WHERE key='opening_cash_cents'")
        save_ledger(self.conn,{'id':entry['id'],'quantity':50})
        opening=opening_state(self.conn)
        self.assertEqual(opening['positions'][0]['quantity'],0)
        self.assertIsNone(opening['cash_cents'])
        preview=self.preview('2026-01-05')
        self.assertFalse(preview['days'][0]['complete'])
        self.assertTrue(any(i['type']=='source_anchor_changed' for i in preview['issues']))

    def test_later_balances_do_not_undo_an_edited_trade(self):
        first=self.trade('2026-01-05','buy',100,'10')
        self.attach(first,{'证券余额':'100','资金余额':'19000'})
        second=self.trade('2026-01-06','buy',100,'10')
        self.attach(second,{'证券余额':'200','资金余额':'18000'})
        save_ledger(self.conn,{'id':first['id'],'quantity':50})
        preview=self.preview('2026-01-06')
        self.assertEqual(preview['days'][-1]['cash_cents'],1850000)
        self.assertEqual(preview['days'][-1]['holdings_cents'],157500)
        self.assertTrue(preview['days'][-1]['complete'])
        self.assertTrue(any(i['type']=='source_anchor_changed' for i in preview['issues']))

    def test_bonus_before_first_sale_included_in_opening_inference(self):
        save_ledger(self.conn,{'date':'2026-01-05','kind':'other','stock_id':self.stock['id'],'quantity':20,'cash_change_cents':0,'summary':'红股入账'})
        sale=self.trade('2026-01-06','sell',120,'10.5')
        self.attach(sale,{'证券余额':'0','资金余额':'21260'})
        self.conn.execute('DELETE FROM opening_positions');self.conn.commit()
        self.assertEqual(opening_state(self.conn)['positions'][0]['quantity'],100)
        preview=self.preview('2026-01-06')
        self.assertEqual(preview['days'][-1]['holdings_cents'],0)
        self.assertFalse(any(i['type']=='position_gap' for i in preview['issues']))

    def test_code_change_invalidates_prices_including_manual(self):
        cache_quotes(self.conn,self.stock['id'],[{'date':'2026-01-05','close_decimal':'99','source':'手工校准'}],'2026-01-01','2026-01-06')
        save_stock(self.conn,{'id':self.stock['id'],'code':'000001'})
        self.assertFalse(covered(self.conn,self.stock['id'],'2026-01-01','2026-01-06'))
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM market_prices').fetchone()[0],0)

    def test_anomaly_before_selected_range_is_reported(self):
        self.trade('2026-01-05','sell',100,'10')
        preview=reconstruct(self.conn,'2026-01-06','2026-01-06')
        self.assertFalse(preview['days'][0]['complete'])
        self.assertTrue(any(i['type']=='negative_position' and i['date']=='2026-01-05' and i.get('entry_id') for i in preview['issues']))

    def server(self):
        return SimpleNamespace(db_path=self.conn.execute('PRAGMA database_list').fetchone()[2],lock=threading.RLock(),previews={},jobs={},active_job=None)

    def fetch(self,stock,start,end):
        return [{'date':d,'close_decimal':'10','source':'test'} for d in ['2025-12-31','2026-01-05','2026-01-06','2026-01-07','2026-04-01','2026-04-02'] if start<=d<=end]

    def test_calendar_covers_selected_start_before_first_trade(self):
        self.trade('2026-04-01','buy',100,'10')
        server=self.server();server.market_fetcher=self.fetch
        job={'id':'test','start':'2026-01-01','end':'2026-04-02','errors':[]}
        from app.reconstruction import market_requests,input_fingerprint
        run_job(server,job,market_requests(self.conn,job['start'],job['end']),input_fingerprint(self.conn,False),False)
        self.assertEqual(job['state'],'ready',job)

    def test_cash_only_range_can_start_and_compute(self):
        self.trade('2026-01-05','buy',100,'10')
        self.trade('2026-01-06','sell',100,'10')
        save_ledger(self.conn,{'date':'2026-01-07','kind':'other','cash_change_cents':100,'summary':'利息归本'})
        server=self.server();server.market_fetcher=self.fetch
        with patch('app.reconstruction_jobs.threading.Thread'):
            job=start_job(server,{'start':'2026-01-07','end':'2026-01-07'})
        from app.reconstruction import input_fingerprint
        run_job(server,server.jobs[job['id']],[],input_fingerprint(self.conn,False),False)
        job=server.jobs[job['id']]
        self.assertEqual(job['state'],'ready',job)
        self.assertEqual(job['preview']['summary']['pnl_cents'],100)
