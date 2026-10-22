"""Public unadjusted daily closes. No account data is sent to a provider."""
from datetime import datetime,timedelta,timezone
from decimal import Decimal
import json
import re
import time
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from .validation import ValidationError,valid_date,price

SOURCE='腾讯日线·不复权'
ENDPOINTS=['https://web.ifzq.gtimg.cn/appstock/app/fqkline/get',
           'https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get']

def last_closed_date(now=None):
    now=now or datetime.now(timezone(timedelta(hours=8)))
    return (now.date() if (now.hour,now.minute)>=(16,30) else now.date()-timedelta(days=1)).isoformat()

def request_bytes(url):
    req=Request(url,headers={'User-Agent':'StockFold/1.1 (local personal portfolio)','Accept':'application/json'})
    with urlopen(req,timeout=10) as response:
        body=response.read(8*1024*1024+1)
        if len(body)>8*1024*1024: raise ValidationError('行情响应过大')
        return body

def fetch_history(stock,start,end,transport=None):
    valid_date(start);valid_date(end)
    if start>end: raise ValidationError('行情开始日期晚于结束日期')
    market=stock.get('market','').lower();code=stock.get('code','')
    if market not in ['sh','sz','bj'] or not re.fullmatch(r'\d{6}',code): raise ValidationError('暂不支持该证券的历史行情')
    symbol=market+code;transport=transport or request_bytes;result={}
    for year in range(int(start[:4]),int(end[:4])+1):
        a=max(start,f'{year}-01-01');b=min(end,f'{year}-12-31')
        parameters=urlencode({'param':f'{symbol},day,{a},{b},640,'})
        error=None
        for endpoint in ENDPOINTS:
            try:
                raw=transport(endpoint+'?'+parameters)
                raw=raw.decode('utf8') if isinstance(raw,bytes) else raw
                if not raw.lstrip().startswith('{') and '={' in raw: raw=raw[raw.index('={')+1:].rstrip(';\n ')
                payload=json.loads(raw)
                data=(payload.get('data') or {}).get(symbol)
                if payload.get('code',0)!=0 or not isinstance(data,dict) or 'day' not in data:
                    raise ValidationError('未取得指定证券的不复权日线（不接受复权数据替代）')
                if not isinstance(data['day'],list): raise ValidationError('日线格式无效')
                for row in data['day']:
                    day=valid_date(row[0]);close=price(row[2])
                    if Decimal(close)<=0: raise ValidationError('收盘价必须大于零')
                    if a<=day<=b: result[day]={'date':day,'close_decimal':close,'source':SOURCE}
                error=None;break
            except (OSError,ValueError,TypeError,KeyError,IndexError) as exc:
                error=exc
        if error: raise ValidationError(f'{symbol} 行情获取失败：{str(error)[:160]}') from error
    return [result[day] for day in sorted(result)]

def covered(conn,stock_id,start,end):
    row=conn.execute('SELECT * FROM market_sync WHERE stock_id=?',(stock_id,)).fetchone()
    return bool(row and row['start_date']<=start and row['end_date']>=end)

def cache_quotes(conn,stock_id,records,start,end):
    if not records: raise ValidationError('未取得行情，未标记为已缓存')
    with conn:
        for r in records:
            day=valid_date(r['date']);close=price(r['close_decimal'])
            if not start<=day<=end or Decimal(close)<=0: raise ValidationError('行情日期或价格无效')
            conn.execute("INSERT INTO market_prices(stock_id,date,close_decimal,source) VALUES (?,?,?,?) ON CONFLICT(stock_id,date) DO UPDATE SET close_decimal=excluded.close_decimal,source=excluded.source,fetched_at=CURRENT_TIMESTAMP WHERE market_prices.source!='手工校准'",
                         (stock_id,day,close,r.get('source',SOURCE)))
        conn.execute('INSERT INTO market_sync(stock_id,start_date,end_date,source) VALUES (?,?,?,?) ON CONFLICT(stock_id) DO UPDATE SET start_date=excluded.start_date,end_date=excluded.end_date,source=excluded.source,updated_at=CURRENT_TIMESTAMP',
                     (stock_id,start,end,records[0].get('source',SOURCE)))
