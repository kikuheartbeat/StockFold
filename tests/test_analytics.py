import unittest
from .test_records import DatabaseFixture, ROOT
from app.records import save_day, save_stock, save_sector, save_ledger
from app.analytics import build_dashboard

class AnalyticsTest(DatabaseFixture):
    def setUp(self):
        super().setUp()
        self.second=save_stock(self.conn,{'code':'000831','name':'中国稀土','market':'SZ'})
        children=[dict(r) for r in self.conn.execute('SELECT * FROM sectors WHERE level=2 ORDER BY id LIMIT 2')]
        self.sector=children[0]
        save_stock(self.conn,{'id':self.stock['id'],'sector_id':children[0]['id']})
        save_stock(self.conn,{'id':self.second['id'],'sector_id':children[1]['id']})

    def add(self,date,a,b,account=None):
        payload={'returns':[{'stock_id':self.stock['id'],'pnl_cents':a},{'stock_id':self.second['id'],'pnl_cents':b}],
                 'status':'confirmed','expected_stock_ids':[self.stock['id'],self.second['id']]}
        if account: payload['account']=account
        save_day(self.conn,date,payload)

    def test_sum_range_and_hierarchy(self):
        self.add('2026-01-05',50000,-20000)
        self.add('2026-01-06',-10000,5000)
        d=build_dashboard(self.conn,'2026-01-05','2026-01-06',2)
        self.assertEqual(d['total_series'][-1]['value_cents'],25000)
        self.assertEqual(d['total_series'][-1]['daily_cents'],-5000)
        self.assertEqual(d['total_series'][-1]['color'],'#16845B')
        self.assertEqual(sum(s['pnl_cents'] for s in d['sectors']),25000)
        coarse=build_dashboard(self.conn,'2026-01-05','2026-01-06',1)
        self.assertEqual(sum(s['pnl_cents'] for s in coarse['sectors']),25000)
        sliced=build_dashboard(self.conn,'2026-01-06','2026-01-06',2)
        self.assertEqual(sliced['summary']['recorded_cumulative_cents'],25000)
        self.assertEqual(sliced['summary']['period_pnl_cents'],-5000)

    def test_missing_day_is_null_zero_is_real(self):
        self.add('2026-01-05',0,0)
        self.add('2026-01-07',100,0)
        d=build_dashboard(self.conn,'2026-01-05','2026-01-07')
        self.assertEqual(d['total_series'][0]['value_cents'],0)
        self.assertIsNone(d['total_series'][1]['value_cents'])
        self.assertTrue(d['total_series'][2]['gap_before'])
        self.assertFalse(d['coverage']['complete'])
        self.assertEqual(d['coverage']['missing_dates'],['2026-01-06'])

    def test_skip_carries_total_and_account_incomplete_is_neutral(self):
        self.add('2026-01-05',100,0)
        save_day(self.conn,'2026-01-06',{'status':'skip','returns':[],'expected_stock_ids':[]})
        save_day(self.conn,'2026-01-07',{'status':'draft','returns':[],
            'account':{'total_assets_cents':1230000,'cash_cents':430000}})
        d=build_dashboard(self.conn,'2026-01-05','2026-01-07')
        self.assertEqual(d['total_series'][1]['value_cents'],100)
        self.assertEqual(d['assets'][-1]['color'],'#94A3B8')

    def test_assets_transfers_and_reconciliation(self):
        self.add('2026-01-05',0,0,{'total_assets_cents':1000000,'cash_cents':1000000})
        save_ledger(self.conn,{'date':'2026-01-06','kind':'deposit','amount_cents':250000})
        save_ledger(self.conn,{'date':'2026-01-06','kind':'withdraw','amount_cents':50000})
        self.add('2026-01-06',50000,-20000,{'total_assets_cents':1230000,'cash_cents':430000})
        d=build_dashboard(self.conn,'2026-01-05','2026-01-06')
        last=d['assets'][-1]
        self.assertEqual(last['holdings_cents'],800000)
        self.assertEqual(last['total_assets_cents'],1230000)
        self.assertEqual(len(last['transfers']),2)
        self.assertEqual(d['reconciliation'][-1]['difference_cents'],0)
        self.assertEqual(d['summary']['period_pnl_cents'],30000)

    def test_reclassification_preserves_total(self):
        self.add('2026-01-05',50000,-20000)
        before=build_dashboard(self.conn,'2026-01-05','2026-01-05')
        save_stock(self.conn,{'id':self.second['id'],'sector_id':self.sector['id']})
        after=build_dashboard(self.conn,'2026-01-05','2026-01-05')
        self.assertEqual(before['summary'],after['summary'])
        self.assertEqual(len(after['sectors']),1)

    def test_other_income_only_and_mixed_remain_visible(self):
        save_day(self.conn,'2026-01-05',{'returns':[],'status':'confirmed','account':{'other_pnl_cents':123}})
        d=build_dashboard(self.conn,'2026-01-05','2026-01-05')
        self.assertTrue(d['coverage']['has_returns'])
        self.assertEqual(d['total_series'][-1]['value_cents'],123)
        self.assertEqual(d['summary']['other_pnl_cents'],123)
        self.add('2026-01-06',200,-100,{'other_pnl_cents':45})
        d=build_dashboard(self.conn,'2026-01-05','2026-01-06')
        self.assertEqual(d['summary']['period_pnl_cents'],268)
        self.assertEqual(sum(g['pnl_cents'] for g in d['sectors'])+d['summary']['other_pnl_cents'],268)

if __name__=='__main__': unittest.main()
