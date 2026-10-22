import json
from .test_records import DatabaseFixture
from app.records import save_stock, save_ledger, save_day
from app.analytics import build_dashboard


class HoldingValuesTest(DatabaseFixture):
    def setUp(self):
        super().setUp()
        self.second = save_stock(self.conn, {'code': '600498', 'name': '烽火通信', 'market': 'SH'})
        for stock, qty in [(self.stock, 100), (self.second, 200)]:
            save_ledger(self.conn, {'date': '2026-01-05', 'kind': 'buy', 'stock_id': stock['id'],
                                    'quantity': qty, 'price_decimal': '10'})
        with self.conn:
            self.conn.execute("INSERT INTO calendar_sync VALUES (1,'2026-01-01','2026-01-07')")
            for day in ['2026-01-05', '2026-01-06']:
                self.conn.execute("INSERT INTO market_calendar(date,source) VALUES (?,'test')", (day,))
            for sid, day, px in [(self.stock['id'], '2026-01-05', '10'), (self.second['id'], '2026-01-05', '20'),
                                 (self.stock['id'], '2026-01-06', '11'), (self.second['id'], '2026-01-06', '21')]:
                self.conn.execute("INSERT INTO market_prices(stock_id,date,close_decimal,source) VALUES (?,?,?,'test')", (sid, day, px))
        save_day(self.conn, '2026-01-05', {'returns': [], 'status': 'confirmed',
                 'account': {'total_assets_cents': 1500000, 'cash_cents': 1000000}})

    def asset(self, day):
        return build_dashboard(self.conn, day, day)['assets'][0]

    def test_positions_supply_actual_closing_values_for_proportional_colors(self):
        asset = self.asset('2026-01-05')
        self.assertEqual([(s['stock_id'], s['quantity'], s['market_value_cents']) for s in asset['positions']],
                         [(self.stock['id'], 100, 100000), (self.second['id'], 200, 400000)])
        self.assertEqual(sum(p['market_value_cents'] for p in asset['positions']), asset['holdings_cents'])
        self.assertTrue(all(p['color'].startswith('#') for p in asset['positions']))

    def test_partial_sale_and_liquidation_update_closing_weights(self):
        save_ledger(self.conn, {'date': '2026-01-06', 'kind': 'sell', 'stock_id': self.stock['id'],
                                'quantity': 50, 'price_decimal': '11'})
        save_ledger(self.conn, {'date': '2026-01-06', 'kind': 'sell', 'stock_id': self.second['id'],
                                'quantity': 200, 'price_decimal': '21'})
        positions = self.asset('2026-01-06')['positions']
        self.assertEqual([(p['stock_id'], p['quantity'], p['market_value_cents']) for p in positions],
                         [(self.stock['id'], 50, 55000)])

    def test_missing_trading_close_is_unknown_instead_of_previous_price(self):
        with self.conn:
            self.conn.execute('DELETE FROM market_prices WHERE stock_id=? AND date=?', (self.second['id'], '2026-01-06'))
        positions = self.asset('2026-01-06')['positions']
        self.assertEqual(positions[0]['market_value_cents'], 110000)
        self.assertIsNone(positions[1]['market_value_cents'])

    def test_verified_non_trading_day_uses_previous_close(self):
        positions = self.asset('2026-01-07')['positions']
        self.assertEqual([p['market_value_cents'] for p in positions], [110000, 420000])

    def test_unverified_calendar_date_does_not_guess_a_closing_value(self):
        positions = self.asset('2026-01-08')['positions']
        self.assertTrue(all(p['market_value_cents'] is None for p in positions))

    def test_negative_position_history_keeps_later_value_unconfirmed(self):
        save_ledger(self.conn, {'date': '2026-01-06', 'kind': 'sell', 'stock_id': self.stock['id'],
                                'quantity': 200, 'price_decimal': '11'})
        save_ledger(self.conn, {'date': '2026-01-07', 'kind': 'buy', 'stock_id': self.stock['id'],
                                'quantity': 200, 'price_decimal': '11'})
        positions = self.asset('2026-01-07')['positions']
        self.assertIsNone(positions[0]['market_value_cents'])
        self.assertEqual(positions[1]['market_value_cents'], 420000)

    def test_imported_security_balance_mismatch_remains_unknown_after_range_start(self):
        second = save_ledger(self.conn, {'date': '2026-01-06', 'kind': 'buy', 'stock_id': self.stock['id'],
                                         'quantity': 100, 'price_decimal': '11'})
        first = dict(self.conn.execute('SELECT * FROM ledger_entries WHERE stock_id=? ORDER BY date,id LIMIT 1',
                                      (self.stock['id'],)).fetchone())
        with self.conn:
            for entry, balance in [(first, 100), (second, 250)]:
                batch = self.conn.execute('INSERT INTO import_batches(file_name,file_hash,record_count) VALUES (?,?,1)',
                                          ('test', str(entry['id']))).lastrowid
                original = {**entry, 'code': self.stock['code']}
                row = self.conn.execute('INSERT INTO import_rows(batch_id,row_number,raw_json,normalized_json) VALUES (?,1,?,?)',
                    (batch, json.dumps({'证券余额': balance}), json.dumps(original))).lastrowid
                self.conn.execute('UPDATE ledger_entries SET import_row_id=? WHERE id=?', (row, entry['id']))
        self.assertIsNone(self.asset('2026-01-06')['positions'][0]['market_value_cents'])
        self.assertIsNone(self.asset('2026-01-07')['positions'][0]['market_value_cents'])
