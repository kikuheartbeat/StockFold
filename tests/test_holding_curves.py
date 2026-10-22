from .test_records import DatabaseFixture
from app.analytics import build_dashboard
from app.records import save_day, save_ledger


class HoldingCurvesTest(DatabaseFixture):
    def trade(self, day, kind, quantity=100, price='10'):
        save_ledger(self.conn, {'date': day, 'kind': kind, 'stock_id': self.stock['id'],
                                'quantity': quantity, 'price_decimal': price})

    def returns(self, day, amount):
        save_day(self.conn, day, self.day(amount))

    def flat(self, day):
        save_day(self.conn, day, {'status': 'skip', 'returns': [], 'expected_stock_ids': []})

    def curve(self, start='2026-01-05', end='2026-01-09'):
        dashboard = build_dashboard(self.conn, start, end)
        return dashboard, next(s for s in dashboard['series'] if s['id'] == self.stock['id'])

    def test_curve_starts_on_buy_and_ends_on_liquidation_including_sell_pnl(self):
        self.trade('2026-01-06', 'buy')
        self.trade('2026-01-08', 'sell')
        for day, pnl in [('2026-01-06', 100), ('2026-01-07', 200), ('2026-01-08', -50)]:
            self.returns(day, pnl)
        self.flat('2026-01-05')
        self.flat('2026-01-09')
        dashboard, series = self.curve()
        self.assertEqual([p['value_cents'] for p in series['points']], [None, 100, 300, 250, None])
        self.assertTrue(series['has_holdings'])
        self.assertEqual(dashboard['summary']['period_pnl_cents'], 250)

    def test_stock_closed_before_selected_range_is_not_a_chart_candidate(self):
        self.trade('2026-01-02', 'buy')
        self.trade('2026-01-03', 'sell')
        self.returns('2026-01-03', 50000)
        self.flat('2026-01-05')
        _, series = self.curve()
        self.assertFalse(series['has_holdings'])
        self.assertTrue(all(p['value_cents'] is None for p in series['points']))

    def test_reentry_resets_even_when_buy_follows_sell_on_next_day(self):
        for day, kind in [('2026-01-05', 'buy'), ('2026-01-06', 'sell'),
                          ('2026-01-07', 'buy'), ('2026-01-09', 'sell')]:
            self.trade(day, kind)
        for day, pnl in [('2026-01-05', 100), ('2026-01-06', 200),
                         ('2026-01-07', -50), ('2026-01-08', 80), ('2026-01-09', 20)]:
            self.returns(day, pnl)
        dashboard, series = self.curve()
        self.assertEqual([p['value_cents'] for p in series['points']], [100, 300, -50, 30, 50])
        self.assertTrue(series['points'][2]['gap_before'])
        self.assertEqual(dashboard['summary']['period_pnl_cents'], 350)
        self.assertEqual(series['period_pnl_cents'], 350)
        self.assertEqual(dashboard['total_series'][-1]['value_cents'], 350)

    def test_flat_interval_is_null_and_second_holding_starts_fresh(self):
        self.trade('2026-01-05', 'buy')
        self.trade('2026-01-06', 'sell')
        self.trade('2026-01-09', 'buy')
        self.returns('2026-01-05', 100)
        self.returns('2026-01-06', 200)
        self.returns('2026-01-09', -50)
        self.flat('2026-01-07')
        self.flat('2026-01-08')
        _, series = self.curve()
        self.assertEqual([p['value_cents'] for p in series['points']], [100, 300, None, None, -50])
        self.assertFalse(series['points'][2]['holding'])

    def test_range_start_rebases_an_existing_position_without_prior_pnl(self):
        self.trade('2026-01-02', 'buy')
        self.returns('2026-01-02', 50000)
        self.returns('2026-01-05', 100)
        self.returns('2026-01-06', -30)
        dashboard, series = self.curve(end='2026-01-06')
        self.assertEqual([p['value_cents'] for p in series['points']], [100, 70])
        self.assertEqual(dashboard['total_series'][-1]['value_cents'], 50070)

    def test_partial_sales_and_additional_buys_do_not_reset_the_curve(self):
        self.trade('2026-01-05', 'buy', 200)
        self.trade('2026-01-06', 'sell', 100)
        self.trade('2026-01-07', 'buy', 100)
        for day in ['2026-01-05', '2026-01-06', '2026-01-07']:
            self.returns(day, 100)
        _, series = self.curve(end='2026-01-07')
        self.assertEqual([p['value_cents'] for p in series['points']], [100, 200, 300])
        self.assertFalse(series['points'][1]['gap_before'])

    def test_opening_position_and_zero_pnl_are_visible_without_a_buy_in_range(self):
        with self.conn:
            self.conn.execute('INSERT INTO opening_positions(stock_id,quantity) VALUES (?,100)', (self.stock['id'],))
        self.returns('2026-01-05', 0)
        _, series = self.curve(end='2026-01-05')
        self.assertTrue(series['has_holdings'])
        self.assertEqual(series['points'][0]['value_cents'], 0)
        self.assertTrue(series['points'][0]['holding'])

    def test_same_day_round_trip_remains_a_visible_single_point(self):
        self.trade('2026-01-05', 'buy')
        self.trade('2026-01-05', 'sell')
        self.returns('2026-01-05', -1000)
        _, series = self.curve(end='2026-01-06')
        self.assertEqual([p['value_cents'] for p in series['points']], [-1000, None])
        self.assertTrue(series['has_holdings'])

    def test_missing_day_stays_a_gap_inside_a_holding(self):
        self.trade('2026-01-05', 'buy')
        self.returns('2026-01-05', 100)
        self.returns('2026-01-07', 200)
        _, series = self.curve(end='2026-01-07')
        self.assertEqual([p['value_cents'] for p in series['points']], [100, None, 300])
        self.assertTrue(series['points'][1]['holding'])
        self.assertTrue(series['points'][2]['gap_before'])

    def test_draft_amount_is_retained_behind_the_gap_in_cumulative_pnl(self):
        self.trade('2026-01-05', 'buy')
        self.returns('2026-01-05', 100)
        save_day(self.conn, '2026-01-06', self.day(200, status='draft'))
        self.returns('2026-01-07', 300)
        dashboard, series = self.curve(end='2026-01-07')
        self.assertEqual([p['value_cents'] for p in series['points']], [100, None, 600])
        self.assertEqual(dashboard['summary']['period_pnl_cents'], 600)

    def test_same_day_liquidation_and_reentry_split_old_and_new_pnl(self):
        self.trade('2026-01-05', 'buy')
        self.trade('2026-01-06', 'sell', price='10.50')
        self.trade('2026-01-06', 'buy')
        with self.conn:
            self.conn.execute("INSERT INTO market_calendar(date,source) VALUES ('2026-01-05','test')")
            self.conn.execute("INSERT INTO market_prices(stock_id,date,close_decimal,source) VALUES (?,'2026-01-05','10.20','test')", (self.stock['id'],))
        self.returns('2026-01-05', 2000)
        self.returns('2026-01-06', 7000)
        self.returns('2026-01-07', 1000)
        dashboard, series = self.curve(end='2026-01-07')
        self.assertEqual([p['value_cents'] for p in series['points']], [2000, 4000, 5000])
        self.assertEqual([[p['value_cents'] for p in segment] for segment in series['holding_segments']],
                         [[2000, 5000], [4000, 5000]])
        self.assertTrue(series['points'][1]['gap_before'])
        self.assertEqual(dashboard['summary']['period_pnl_cents'], 10000)

    def test_multiple_round_trips_on_first_day_need_no_previous_close(self):
        self.trade('2026-01-05', 'buy')
        self.trade('2026-01-05', 'sell', price='10.50')
        self.trade('2026-01-05', 'buy')
        self.returns('2026-01-05', 9000)
        _, series = self.curve(end='2026-01-05')
        self.assertEqual([[p['value_cents'] for p in segment] for segment in series['holding_segments']],
                         [[5000], [4000]])

    def test_same_day_split_with_missing_previous_price_keeps_a_gap(self):
        self.trade('2026-01-05', 'buy')
        self.trade('2026-01-06', 'sell')
        self.trade('2026-01-06', 'buy')
        self.returns('2026-01-05', 100)
        self.returns('2026-01-06', 200)
        self.returns('2026-01-07', 300)
        self.trade('2026-01-08', 'sell')
        self.returns('2026-01-08', 100)
        self.trade('2026-01-09', 'buy')
        self.returns('2026-01-09', 50)
        _, series = self.curve()
        self.assertIsNone(series['points'][1]['value_cents'])
        self.assertIsNone(series['points'][2]['value_cents'])
        self.assertIsNone(series['points'][3]['value_cents'])
        self.assertEqual(series['points'][4]['value_cents'], 50)
