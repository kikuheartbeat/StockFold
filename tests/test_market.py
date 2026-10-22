import json
from datetime import datetime,timezone,timedelta
from urllib.parse import urlparse,parse_qs
from .test_records import DatabaseFixture
from app.market import fetch_history,cache_quotes,covered,last_closed_date
from app.validation import ValidationError

class MarketTest(DatabaseFixture):
    def test_unadjusted_decimal_close_for_stock_and_etf(self):
        calls=[]
        def transport(url):
            calls.append(url);symbol=parse_qs(urlparse(url).query)['param'][0].split(',')[0]
            return json.dumps({'code':0,'data':{symbol:{'day':[['2026-01-05','1','0.776','1','0.7','10']]}}}).encode()
        rows=fetch_history({'code':'513010','market':'SH'},'2026-01-01','2026-01-06',transport)
        self.assertEqual(rows,[{'date':'2026-01-05','close_decimal':'0.776','source':'腾讯日线·不复权'}])
        self.assertTrue(parse_qs(urlparse(calls[0]).query)['param'][0].endswith(','))

    def test_adjusted_only_bad_price_and_wrong_symbol_rejected(self):
        for body in [ {'code':0,'data':{'sz000001':{'qfqday':[['2026-01-05','1','2']]}}},
                      {'code':0,'data':{'sz000001':{'day':[['2026-01-05','1','NaN']]}}},
                      {'code':0,'data':{'sh000001':{'day':[['2026-01-05','1','2']]}}}]:
            with self.assertRaises(ValidationError):
                fetch_history({'code':'000001','market':'SZ'},'2026-01-01','2026-01-06',lambda _:json.dumps(body).encode())

    def test_cache_ranges_and_calendar_explicit(self):
        data=[{'date':'2026-01-05','close_decimal':'10.123','source':'test'}]
        cache_quotes(self.conn,self.stock['id'],data,'2026-01-01','2026-01-06')
        self.assertTrue(covered(self.conn,self.stock['id'],'2026-01-02','2026-01-05'))
        self.assertFalse(covered(self.conn,self.stock['id'],'2025-12-31','2026-01-05'))
        self.assertEqual(self.conn.execute('SELECT close_decimal FROM market_prices').fetchone()[0],'10.123')

    def test_current_intraday_bar_not_used(self):
        zone=timezone(timedelta(hours=8))
        self.assertEqual(last_closed_date(datetime(2026,10,21,14,0,tzinfo=zone)),'2026-10-20')
        self.assertEqual(last_closed_date(datetime(2026,10,21,17,0,tzinfo=zone)),'2026-10-21')

    def test_multi_year_queries_and_order(self):
        calls=[]
        def transport(url):
            param=parse_qs(urlparse(url).query)['param'][0].split(',');calls.append(param)
            return json.dumps({'code':0,'data':{param[0]:{'day':[[param[2][:4]+'-01-06','1','2']]}}}).encode()
        result=fetch_history({'code':'000001','market':'SZ'},'2025-01-01','2026-12-01',transport)
        self.assertEqual(len(calls),2);self.assertEqual(len(result),2)
