from .test_records import DatabaseFixture
from app.records import save_ledger, save_day, save_stock
from app.analytics import build_dashboard
from app import stock_history as history
from app.validation import ValidationError
from types import SimpleNamespace
from threading import RLock
from unittest.mock import patch


class StockHistoryTest(DatabaseFixture):
    def trade(self, day, kind, quantity=100):
        save_ledger(self.conn, dict(date=day, kind=kind, stock_id=self.stock['id'],
                                   quantity=quantity, price_decimal='10'))

    def read(self, start='2026-01-05', end='2026-01-12'):
        return history.stock_history(self.conn, self.stock['id'], start, end)

    def test_full_price_range_and_sessions_independent_of_returns(self):
        self.trade('2026-01-06', 'buy', 200)
        self.trade('2026-01-07', 'sell', 100)
        self.trade('2026-01-08', 'sell')
        self.trade('2026-01-12', 'buy')
        for day in ['2026-01-05', '2026-01-06', '2026-01-09', '2026-01-12']:
            self.conn.execute('INSERT INTO market_prices(stock_id,date,close_decimal,source) VALUES (?,?,?,?)',
                              (self.stock['id'], day, '10.23', 'test'))
        self.conn.commit()
        data = self.read()
        self.assertEqual(data['intervals'], [dict(start='2026-01-06', end='2026-01-08'),
                                              dict(start='2026-01-12', end=None)])
        self.assertEqual(data['points'][0]['close'], 10.23)
        self.assertEqual(data['points'][-1]['close'], 10.23)
        self.assertIsNone(data['points'][2]['close'])

    def test_closed_stock_remains_selectable_outside_holding_range(self):
        self.trade('2026-01-02', 'buy')
        self.trade('2026-01-03', 'sell')
        save_stock(self.conn, dict(code='600000', name='未买过', market='SH'))
        candidates = build_dashboard(self.conn, '2026-01-05', '2026-01-12')['history_candidates']
        self.assertEqual([s['id'] for s in candidates], [self.stock['id']])
        self.assertEqual(self.read()['intervals'], [])

    def test_closed_stock_requests_full_range_when_cached_quotes_stop_at_exit(self):
        self.trade('2026-01-06','buy')
        self.trade('2026-01-08','sell')
        with self.conn:
            self.conn.execute('INSERT INTO market_sync(stock_id,start_date,end_date,source) VALUES (?,?,?,?)',
                              (self.stock['id'],'2026-01-05','2026-01-08','test'))
        self.assertTrue(self.read()['needs_sync'])
        self.assertFalse(self.read(end='2026-01-08')['needs_sync'])
        requests=[]
        def fetch(stock,start,end):
            requests.append((stock['code'],start,end))
            return [dict(date=day,close_decimal='10.5',source='test') for day in
                    ['2026-01-05','2026-01-06','2026-01-08','2026-01-09','2026-01-12'] if start<=day<=end]
        server=SimpleNamespace(db_path=self.conn.execute('PRAGMA database_list').fetchone()[2],lock=RLock(),jobs={},market_fetcher=fetch)
        data=history.sync_stock_history(server,dict(stock_id=self.stock['id'],start='2026-01-05',end='2026-01-12'))
        self.assertEqual(requests[0],(self.stock['code'],'2026-01-05','2026-01-12'))
        self.assertFalse(data['needs_sync'])
        self.assertEqual(data['points'][-1]['close'],10.5)
        self.assertEqual(data['intervals'],[dict(start='2026-01-06',end='2026-01-08')])

    def test_auto_sync_never_requests_prices_beyond_the_last_available_close(self):
        with self.conn:
            self.conn.execute('INSERT INTO market_sync(stock_id,start_date,end_date,source) VALUES (?,?,?,?)',
                              (self.stock['id'],'2026-01-05','2026-01-09','test'))
        with patch('app.stock_history.last_closed_date',return_value='2026-01-09'):
            self.assertFalse(self.read(end='2026-01-12')['needs_sync'])
            self.assertFalse(self.read(start='2026-01-12',end='2026-01-13')['needs_sync'])

    def test_opening_position_has_no_invented_buy_date(self):
        self.conn.execute('INSERT INTO opening_positions(stock_id,quantity) VALUES (?,100)', (self.stock['id'],))
        self.conn.commit()
        self.trade('2026-01-08', 'sell')
        self.assertEqual(self.read()['intervals'], [dict(start=None, end='2026-01-08')])

    def test_same_day_exit_reentry_and_range_clipping_keep_real_endpoints(self):
        self.trade('2026-01-02', 'buy')
        self.trade('2026-01-06', 'sell')
        self.trade('2026-01-06', 'buy')
        self.assertEqual(self.read()['intervals'], [dict(start='2026-01-02', end='2026-01-06'),
                                                  dict(start='2026-01-06', end=None)])
        self.assertEqual(self.read('2026-01-07')['intervals'], [dict(start='2026-01-06', end=None)])

    def test_calendar_marks_only_verified_closed_dates(self):
        self.conn.execute("INSERT INTO calendar_sync VALUES (1,'2026-01-05','2026-01-12')")
        for day in ['2026-01-05', '2026-01-06', '2026-01-07', '2026-01-08', '2026-01-09', '2026-01-12']:
            self.conn.execute('INSERT INTO market_calendar(date,source) VALUES (?,?)', (day, 'test'))
        data = self.read()
        self.assertFalse(data['points'][2]['closed'])
        self.assertTrue(data['points'][5]['closed'])
        self.assertFalse(self.read(end='2026-01-13')['points'][-1]['closed'])

    def test_history_never_changes_account_returns_and_validates_identity(self):
        save_day(self.conn, '2026-01-05', self.day(123))
        before = build_dashboard(self.conn, '2026-01-05', '2026-01-12')['total_series']
        self.read()
        self.assertEqual(build_dashboard(self.conn, '2026-01-05', '2026-01-12')['total_series'], before)
        with self.assertRaises(ValidationError):
            history.stock_history(self.conn, 999999, '2026-01-05', '2026-01-12')
        with self.assertRaises(ValidationError):
            self.read(start='2026-01-13')

    def test_missing_opening_evidence_is_explicitly_uncertain(self):
        self.trade('2026-01-06', 'buy')
        self.assertTrue(self.read()['uncertain'])
        with self.conn:
            self.conn.execute('INSERT INTO opening_positions(stock_id,quantity) VALUES (?,0)', (self.stock['id'],))
        self.assertFalse(self.read()['uncertain'])

    def test_interval_profit_uses_selected_stock_full_session_not_account_or_visible_slice(self):
        with self.conn:
            self.conn.execute('INSERT INTO opening_positions(stock_id,quantity) VALUES (?,0)', (self.stock['id'],))
        self.trade('2026-01-05', 'buy')
        self.trade('2026-01-07', 'sell')
        self.trade('2026-01-08', 'buy')
        for day, amount in [('2026-01-05',100),('2026-01-06',-300),('2026-01-07',50),('2026-01-08',500),('2026-01-09',-100)]:
            payload=self.day(amount)
            payload['account']['other_pnl_cents']=100000
            save_day(self.conn, day, payload)
        data=self.read(start='2026-01-06',end='2026-01-09')
        self.assertEqual(data['interval_pnl_cents'],[-150,400])

    def test_missing_daily_profit_or_opening_basis_does_not_guess_session_color(self):
        self.trade('2026-01-05','buy')
        save_day(self.conn,'2026-01-05',self.day(100))
        self.assertEqual(self.read(end='2026-01-06')['interval_pnl_cents'],[None])
        with self.conn:
            self.conn.execute('INSERT INTO opening_positions(stock_id,quantity) VALUES (?,0)', (self.stock['id'],))
        self.assertEqual(self.read(end='2026-01-06')['interval_pnl_cents'],[None])

    def test_same_day_exit_and_reentry_have_independent_profit_colors(self):
        with self.conn:
            self.conn.execute('INSERT INTO opening_positions(stock_id,quantity) VALUES (?,0)', (self.stock['id'],))
            self.conn.execute("INSERT INTO market_calendar(date,source) VALUES ('2026-01-05','test')")
            self.conn.execute("INSERT INTO market_prices(stock_id,date,close_decimal,source) VALUES (?,'2026-01-05','10','test')",(self.stock['id'],))
        self.trade('2026-01-05','buy')
        save_ledger(self.conn, dict(date='2026-01-06',kind='sell',stock_id=self.stock['id'],quantity=100,price_decimal='11'))
        self.trade('2026-01-06','buy')
        save_day(self.conn,'2026-01-05',self.day(0))
        save_day(self.conn,'2026-01-06',self.day(5000))
        self.assertEqual(self.read(end='2026-01-06')['interval_pnl_cents'],[10000,-5000])

    def test_disjoint_price_sync_preserves_existing_calendar_and_fetches_the_gap(self):
        with self.conn:
            self.conn.execute("INSERT INTO calendar_sync VALUES (1,'2025-12-01','2025-12-31')")
            self.conn.execute("INSERT INTO market_calendar(date,source) VALUES ('2025-12-31','test')")
        requests=[]
        def fetch(stock, start, end):
            requests.append((stock['code'], start, end))
            return [dict(date=day, close_decimal='10', source='test') for day in
                    ['2025-12-31','2026-01-05','2026-01-06','2026-01-12'] if start<=day<=end]
        server=SimpleNamespace(db_path=self.conn.execute('PRAGMA database_list').fetchone()[2],
                               lock=RLock(), jobs={}, market_fetcher=fetch)
        history.sync_stock_history(server, dict(stock_id=self.stock['id'], start='2026-01-05', end='2026-01-12'))
        span=self.conn.execute('SELECT * FROM calendar_sync').fetchone()
        self.assertEqual(span['start_date'],'2025-12-01')
        self.assertEqual(span['end_date'],'2026-01-12')
        self.assertEqual(requests[1][1],'2025-12-01')
