import json
from pathlib import Path
from .test_records import DatabaseFixture
from app.records import save_ledger,save_day,get_day,save_stock
from app.analytics import build_dashboard
from app.reconstruction import reconstruct,apply_reconstruction,input_fingerprint,opening_state
from app.validation import ValidationError

class ReconstructionTest(DatabaseFixture):
    def setUp(self):
        super().setUp()
        with self.conn:
            self.conn.execute("UPDATE app_settings SET value_json='\"2026-01-05\"' WHERE key='record_start'")
            self.conn.execute("INSERT INTO app_settings VALUES ('opening_cash_cents','2000000')")
            self.conn.execute('INSERT INTO opening_positions(stock_id,quantity) VALUES (?,0)',(self.stock['id'],))
            for day,px in [('2026-01-02','10'),('2026-01-05','10.20'),('2026-01-06','10.50'),('2026-01-08','10.60')]:
                self.conn.execute("INSERT INTO market_calendar(date,source) VALUES (?,'test')",(day,))
                self.conn.execute("INSERT INTO market_prices(stock_id,date,close_decimal,source) VALUES (?,?,?,'test')",(self.stock['id'],day,px))
            self.conn.execute("INSERT INTO market_calendar(date,source) VALUES ('2026-01-07','test')")
            self.conn.execute("INSERT INTO calendar_sync VALUES (1,'2025-12-01','2026-01-08')")

    def trade(self,day,kind,qty,px,fees=0):
        return save_ledger(self.conn,{'date':day,'kind':kind,'stock_id':self.stock['id'],'quantity':qty,'price_decimal':px,'fees_cents':fees})

    def preview(self,end='2026-01-07'): return reconstruct(self.conn,'2026-01-05',end)

    def test_buy_hold_sell_profit_and_assets(self):
        self.trade('2026-01-05','buy',1000,'10',500)
        self.trade('2026-01-07','sell',1000,'10.4',500)
        p=self.preview()
        self.assertEqual([d['pnl_cents'] for d in p['days']],[19500,30000,-10500])
        self.assertEqual([d['total_assets_cents'] for d in p['days']],[2019500,2049500,2039000])
        self.assertEqual(p['summary']['pnl_cents'],39000)

    def test_transfer_not_profit_and_partial_sell(self):
        self.trade('2026-01-05','buy',1000,'10')
        save_ledger(self.conn,{'date':'2026-01-06','kind':'deposit','amount_cents':200000})
        self.trade('2026-01-06','sell',400,'10.6')
        p=self.preview('2026-01-06')
        self.assertEqual(p['days'][-1]['pnl_cents'],34000)
        self.assertEqual(p['days'][-1]['total_assets_cents'],2254000)
        self.assertEqual(p['days'][-1]['holdings_cents'],630000)

    def test_missing_trading_price_is_gap_and_holiday_carries(self):
        self.trade('2026-01-05','buy',100,'10')
        p=self.preview('2026-01-08')
        self.assertFalse(p['days'][2]['complete'])
        self.assertIsNone(p['days'][2]['total_assets_cents'])
        self.assertFalse(p['days'][3]['complete'],'missing prior trading close cannot be silently carried')
        self.assertTrue(any(i['type']=='missing_price' for i in p['issues']))

    def test_rest_day_carries_verified_price(self):
        self.trade('2026-01-05','buy',100,'10')
        self.conn.execute("DELETE FROM market_calendar WHERE date='2026-01-07'");self.conn.commit()
        p=self.preview()
        self.assertTrue(p['days'][2]['complete']);self.assertEqual(p['days'][2]['pnl_cents'],0)

    def test_dividend_tax_and_interest_not_unknown_profit(self):
        self.trade('2026-01-05','buy',100,'10')
        for summary,amount,sid in [('红利入账',500,self.stock['id']),('股息红利差异扣税',-100,self.stock['id']),('利息归本',20,None),('未知资金',20000,None)]:
            save_ledger(self.conn,{'date':'2026-01-06','kind':'other','stock_id':sid,'cash_change_cents':amount,'summary':summary})
        p=self.preview('2026-01-06')
        self.assertEqual(p['days'][-1]['returns'][0]['pnl_cents'],3400)
        self.assertEqual(p['days'][-1]['other_pnl_cents'],20)
        self.assertEqual(p['days'][-1]['pnl_cents'],3420)
        self.assertTrue(any(i['type']=='unknown_event' for i in p['issues']))

    def test_manual_zero_and_snapshot_protected_and_fingerprint(self):
        self.trade('2026-01-05','buy',100,'10')
        save_day(self.conn,'2026-01-05',self.day(0))
        p=self.preview('2026-01-06')
        result=apply_reconstruction(self.conn,p)
        self.assertEqual(result['protected_days'],1)
        self.assertEqual(get_day(self.conn,'2026-01-05')['returns'][0]['pnl_cents'],0)
        self.assertEqual(get_day(self.conn,'2026-01-06')['returns'][0]['source'],'market_close')
        with self.assertRaises(ValidationError): apply_reconstruction(self.conn,p)

    def test_recalculate_replaces_own_data_but_edit_turns_manual(self):
        self.trade('2026-01-05','buy',100,'10')
        apply_reconstruction(self.conn,self.preview('2026-01-06'))
        self.conn.execute("UPDATE market_prices SET close_decimal='10.6' WHERE date='2026-01-06'");self.conn.commit()
        apply_reconstruction(self.conn,self.preview('2026-01-06'))
        self.assertEqual(get_day(self.conn,'2026-01-06')['returns'][0]['pnl_cents'],4000)
        save_day(self.conn,'2026-01-06',self.day(777))
        result=apply_reconstruction(self.conn,self.preview('2026-01-06'))
        self.assertEqual(get_day(self.conn,'2026-01-06')['returns'][0]['pnl_cents'],777)
        self.assertEqual(result['protected_days'],1)

    def test_opening_balance_inferred_from_source_without_trade_price_substitution(self):
        entry=self.trade('2026-01-05','sell',100,'10.4')
        with self.conn:
            self.conn.execute('DELETE FROM opening_positions')
            batch=self.conn.execute("INSERT INTO import_batches(file_name,file_hash,record_count) VALUES ('source','hash',1)").lastrowid
            raw={'证券余额':'0','资金余额':'21040'}
            row=self.conn.execute('INSERT INTO import_rows(batch_id,row_number,raw_json,normalized_json) VALUES (?,?,?,?)',(batch,1,json.dumps(raw),json.dumps({'cash_change_cents':entry['cash_change_cents']}))).lastrowid
            self.conn.execute('UPDATE ledger_entries SET import_row_id=? WHERE id=?',(row,entry['id']))
        state=opening_state(self.conn)
        self.assertEqual(state['positions'][0]['quantity'],100)
        self.assertEqual(state['positions'][0]['source'],'首笔证券余额反推')
        self.assertEqual(self.preview('2026-01-05')['days'][0]['pnl_cents'],4000)

    def test_negative_holdings_block_complete_day(self):
        self.trade('2026-01-05','sell',100,'10')
        p=self.preview('2026-01-05')
        self.assertFalse(p['days'][0]['complete'])
        self.assertTrue(any(i['type']=='negative_position' for i in p['issues']))

    def test_source_cash_gap_is_not_profit(self):
        entry=self.trade('2026-01-05','buy',100,'10')
        with self.conn:
            batch=self.conn.execute("INSERT INTO import_batches(file_name,file_hash,record_count) VALUES ('source','hash',1)").lastrowid
            row=self.conn.execute('INSERT INTO import_rows(batch_id,row_number,raw_json,normalized_json) VALUES (?,?,?,?)',(batch,1,json.dumps({'资金余额':'20000','证券余额':'100'}),json.dumps({'cash_change_cents':entry['cash_change_cents']}))).lastrowid
            self.conn.execute('UPDATE ledger_entries SET import_row_id=? WHERE id=?',(row,entry['id']))
        p=self.preview('2026-01-05')
        self.assertEqual(p['days'][0]['pnl_cents'],2000)
        self.assertEqual(p['days'][0]['cash_cents'],2000000)
        self.assertTrue(any(i['type']=='cash_gap' for i in p['issues']))

    def test_one_missing_stock_does_not_hide_other_calculated_stock_curve(self):
        second=save_stock(self.conn,{'code':'600498','name':'烽火通信','market':'SH'})
        self.conn.execute('INSERT INTO opening_positions VALUES (?,0,\'\')',(second['id'],));self.conn.commit()
        self.trade('2026-01-05','buy',100,'10')
        save_ledger(self.conn,{'date':'2026-01-05','kind':'buy','stock_id':second['id'],'quantity':100,'price_decimal':'10'})
        apply_reconstruction(self.conn,self.preview('2026-01-05'))
        dashboard=build_dashboard(self.conn,'2026-01-05','2026-01-05')
        self.assertIsNone(dashboard['total_series'][0]['value_cents'])
        good=next(s for s in dashboard['series'] if s['id']==self.stock['id'])
        bad=next(s for s in dashboard['series'] if s['id']==second['id'])
        self.assertEqual(good['points'][0]['value_cents'],2000)
        self.assertIsNone(bad['points'][0]['value_cents'])
