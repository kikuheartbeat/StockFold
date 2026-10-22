import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from app.db import connect, initialize
from app.validation import ValidationError, money_to_cents
from app.records import save_day, get_day, save_returns_batch, save_stock, save_sector, save_ledger

ROOT = Path(__file__).resolve().parents[1]

class DatabaseFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = connect(Path(self.tmp.name)/'test.sqlite3')
        initialize(self.conn, ROOT/'resources')
        self.stock = save_stock(self.conn, {'code':'000988','name':'华工科技','market':'SZ','asset_type':'stock'})

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def day(self, amount=0, status='confirmed'):
        return {'returns':[{'stock_id':self.stock['id'],'pnl_cents':amount}],
                'expected_stock_ids':[self.stock['id']], 'status':status,
                'account':{'total_assets_cents':1000000,'cash_cents':200000,'other_pnl_cents':0}}

class RecordsTest(DatabaseFixture):
    def test_precise_money_and_reject_invalid(self):
        self.assertEqual(money_to_cents('0.10')+money_to_cents('0.20'),30)
        self.assertEqual(money_to_cents('-12.34'),-1234)
        for value in ['1.001','NaN','Infinity',True,'abc']:
            with self.assertRaises(ValidationError): money_to_cents(value)

    def test_zero_and_text_identifier_survive(self):
        save_day(self.conn,'2026-01-05',self.day())
        saved=get_day(self.conn,'2026-01-05')
        self.assertEqual(saved['returns'][0]['pnl_cents'],0)
        self.assertEqual(saved['returns'][0]['code'],'000988')
        self.assertEqual(saved['status'],'confirmed')

    def test_duplicate_stock_and_incomplete_confirmation(self):
        payload=self.day()
        payload['returns'].append(payload['returns'][0])
        with self.assertRaises(ValidationError): save_day(self.conn,'2026-01-05',payload)
        payload=self.day()
        payload['returns']=[]
        with self.assertRaises(ValidationError): save_day(self.conn,'2026-01-05',payload)

    def test_batch_is_atomic(self):
        with self.assertRaises(ValidationError):
            save_returns_batch(self.conn,[{'date':'2026-01-05','stock_id':self.stock['id'],'pnl_cents':100},
                                         {'date':'2026-02-30','stock_id':self.stock['id'],'pnl_cents':200}])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM daily_returns').fetchone()[0],0)

    def test_hierarchy_and_colors_persist(self):
        sectors=[dict(r) for r in self.conn.execute('SELECT * FROM sectors')]
        self.assertEqual(sum(s['level']==1 for s in sectors),31)
        self.assertEqual(sum(s['level']==2 for s in sectors),131)
        before={s['id']:s['color'] for s in sectors}
        initialize(self.conn,ROOT/'resources')
        self.assertEqual(before,{r['id']:r['color'] for r in self.conn.execute('SELECT * FROM sectors')})
        parent=next(s for s in sectors if s['level']==1)
        with self.assertRaises(ValidationError): save_stock(self.conn,{'id':self.stock['id'],'sector_id':parent['id']})

    def test_ledger_no_automatic_profit(self):
        entry=save_ledger(self.conn,{'date':'2026-01-05','kind':'deposit','amount_cents':200000,'stock_id':None})
        self.assertEqual(entry['cash_change_cents'],200000)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM daily_returns').fetchone()[0],0)

    def test_asset_validation_and_day_rollback(self):
        payload=self.day()
        payload['account']['cash_cents']=2000000
        with self.assertRaises(ValidationError): save_day(self.conn,'2026-01-05',payload)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM daily_returns').fetchone()[0],0)

    def test_bulk_edit_resets_confirmation(self):
        save_day(self.conn,'2026-01-05',self.day(100))
        save_returns_batch(self.conn,[{'date':'2026-01-05','stock_id':self.stock['id'],'pnl_cents':200}])
        self.assertEqual(get_day(self.conn,'2026-01-05')['status'],'draft')

    def test_batch_confirm_explicit_and_missing_expected_rolls_back(self):
        save_day(self.conn,'2026-01-05',self.day(100))
        save_returns_batch(self.conn,[{'date':'2026-01-05','stock_id':self.stock['id'],'pnl_cents':200}],confirm=True)
        self.assertEqual(get_day(self.conn,'2026-01-05')['status'],'confirmed')

    def test_batch_fills_all_missing_expected_before_confirming(self):
        second=save_stock(self.conn,{'code':'600498','name':'烽火通信','market':'SH'})
        save_day(self.conn,'2026-01-05',{'returns':[],'expected_stock_ids':[self.stock['id'],second['id']],'status':'draft'})
        batch=[{'date':'2026-01-05','stock_id':sid,'pnl_cents':123} for sid in [self.stock['id'],second['id']]]
        with self.assertRaises(ValidationError): save_returns_batch(self.conn,batch[:1],confirm=True)
        self.assertEqual(get_day(self.conn,'2026-01-05')['returns'],[])
        save_returns_batch(self.conn,batch,confirm=True)
        self.assertEqual(get_day(self.conn,'2026-01-05')['status'],'confirmed')
        self.assertEqual(len(get_day(self.conn,'2026-01-05')['returns']),2)

if __name__=='__main__': unittest.main()
