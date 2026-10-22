"""Closing holdings for asset stacks and market-value-weighted chart colors."""
from bisect import bisect_right
from decimal import Decimal, ROUND_HALF_UP
from .reconstruction import opening_state, ledger_rows, share_change, source_breaks, unchanged_source, integer


def holding_values(conn, dates, stocks):
    if not dates:
        return {}
    opening = opening_state(conn)['positions']
    quantities = {s['stock_id']: s['quantity'] for s in opening}
    uncertain = {s['stock_id'] for s in opening if s['requires_confirmation']}
    all_entries = ledger_rows(conn)
    stock_map = {s['id']: s for s in stocks}
    _, position_breaks, _ = source_breaks(all_entries, stock_map)
    entries = [e for e in all_entries if e['stock_id'] and e['date'] <= dates[-1]]
    have_market = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='market_prices'").fetchone()
    calendar = [r[0] for r in conn.execute('SELECT date FROM market_calendar ORDER BY date')] if have_market else []
    coverage = conn.execute('SELECT * FROM calendar_sync WHERE id=1').fetchone() if have_market else None
    prices = {(r['stock_id'], r['date']): Decimal(r['close_decimal'])
              for r in conn.execute('SELECT * FROM market_prices WHERE date<=?', (dates[-1],))} if have_market else {}
    result = {}
    index = 0
    for day in dates:
        while index < len(entries) and entries[index]['date'] <= day:
            entry = entries[index]
            sid = entry['stock_id']
            quantities[sid] = quantities.get(sid, 0) + share_change(entry)
            if quantities[sid] < 0:
                uncertain.add(sid)
            if entry['kind'] in ['buy', 'sell']:
                anchor = integer(entry['raw_json'].get('证券余额'))
                valid_anchor = unchanged_source(entry, stock_map) and (sid not in position_breaks or entry['date'] < position_breaks[sid])
                if anchor is not None and valid_anchor and anchor != quantities[sid]:
                    uncertain.add(sid)
            index += 1
        verified = coverage and coverage['start_date'] <= day <= coverage['end_date']
        calendar_index = bisect_right(calendar, day) - 1
        closing_day = calendar[calendar_index] if verified and calendar_index >= 0 else None
        positions = []
        for stock in stocks:
            sid = stock['id']
            quantity = quantities.get(sid, 0)
            if not quantity and sid not in uncertain:
                continue
            close = prices.get((sid, closing_day))
            value = None
            if quantity > 0 and sid not in uncertain and close is not None:
                value = int((close * quantity * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
            positions.append({'stock_id': sid, 'code': stock['code'], 'name': stock['name'],
                              'color': stock['color'], 'quantity': quantity, 'market_value_cents': value})
        result[day] = positions
    return result
