"""Read-only price/holding comparison; quote sync never writes account returns."""
from contextlib import closing
from datetime import date, timedelta
from .db import connect, settings
from .records import stock_list
from .reconstruction import opening_state, ledger_rows, share_change
from .returns import dates_between, build_returns
from .holding_curves import holding_curves
from .market import fetch_history, cache_quotes, last_closed_date, covered
from .validation import ValidationError


def history_candidates(conn):
    bought = {r[0] for r in conn.execute("SELECT DISTINCT stock_id FROM ledger_entries WHERE kind='buy' AND quantity!=0")}
    bought.update(p['stock_id'] for p in opening_state(conn)['positions'] if p['quantity'] > 0)
    return [s for s in stock_list(conn) if s['id'] in bought and s['asset_type'] in ('stock', 'etf')]


def holding_profits(conn, stock_id, intervals, end, uncertain):
    """Reuse confirmed per-holding P&L, including same-day exit/reentry splits."""
    if uncertain or not intervals:
        return [None] * len(intervals)
    boundaries = [day for s in intervals for day in (s['start'], s['end']) if day]
    start = min([settings(conn).get('record_start', end)] + boundaries)
    stocks = stock_list(conn)
    data = build_returns(conn, start, end, stocks)
    curves = holding_curves(conn, data['dates'], data['series'], data['daily'])
    segments = curves[stock_id]['holding_segments']
    profits = []
    for index, interval in enumerate(intervals):
        segment = segments[index] if index < len(segments) else []
        known = (interval['start'] is not None and segment and
                 segment[0]['date'] == interval['start'] and
                 segment[-1]['date'] == (interval['end'] or end) and
                 all(p['value_cents'] is not None for p in segment))
        profits.append(segment[-1]['value_cents'] if known else None)
    return profits


def stock_history(conn, stock_id, start, end):
    dates = dates_between(start, end)
    stock = next((s for s in stock_list(conn) if s['id'] == stock_id), None)
    if not stock:
        raise ValidationError('证券不存在')
    opening = next((p for p in opening_state(conn)['positions'] if p['stock_id'] == stock_id), {})
    quantity = opening.get('quantity', 0)
    uncertain = opening.get('requires_confirmation', False) or opening.get('source') == '暂按0（请核对）'
    intervals = []
    active = {'start': None, 'end': None} if quantity > 0 else None
    for entry in ledger_rows(conn):
        if entry['stock_id'] != stock_id or entry['date'] > end:
            continue
        before = quantity
        quantity += share_change(entry)
        if quantity < 0:
            uncertain = True
        if before <= 0 < quantity:
            active = {'start': entry['date'], 'end': None}
        if before > 0 and quantity <= 0 and active is not None:
            active['end'] = entry['date']
            intervals.append(active)
            active = None
    if active is not None:
        intervals.append(active)
    profits = holding_profits(conn, stock_id, intervals, end, uncertain)
    visible = [(p, pnl) for p, pnl in zip(intervals, profits) if p['end'] is None or p['end'] >= start]
    intervals = [p for p, _ in visible]
    profits = [pnl for _, pnl in visible]
    quotes = {r['date']: float(r['close_decimal']) for r in conn.execute(
        'SELECT date,close_decimal FROM market_prices WHERE stock_id=? AND date>=? AND date<=?',
        (stock_id, start, end))}
    calendar = {r[0] for r in conn.execute('SELECT date FROM market_calendar WHERE date>=? AND date<=?', (start, end))}
    span = conn.execute('SELECT * FROM calendar_sync WHERE id=1').fetchone()
    points = [{'date': day, 'close': quotes.get(day),
               'closed': bool(span and span['start_date'] <= day <= span['end_date'] and day not in calendar)}
              for day in dates]
    available_end = min(end, last_closed_date())
    needs_sync = start <= available_end and not covered(conn, stock_id, start, available_end)
    return {'stock': stock, 'start': start, 'end': end, 'points': points, 'intervals': intervals,
            'interval_pnl_cents': profits, 'uncertain': bool(uncertain), 'source': '不复权日收盘价',
            'needs_sync': needs_sync}


def sync_stock_history(server, payload):
    """Keep slow provider calls outside the server lock, check identity before saving."""
    sid = int(payload.get('stock_id', 0))
    start, end = payload.get('start'), payload.get('end')
    dates_between(start, end)
    end = min(end, last_closed_date())
    if end < start:
        raise ValidationError('所选区间尚无已确认收盘价，请在16:30后更新或选择更早日期')
    with server.lock, closing(connect(server.db_path)) as conn:
        stock = stock_history(conn, sid, start, end)['stock']
        previous_span = conn.execute('SELECT * FROM calendar_sync WHERE id=1').fetchone()
        calendar_start = min(start, previous_span['start_date']) if previous_span else start
    fetcher = getattr(server, 'market_fetcher', fetch_history)
    try:
        records = fetcher(stock, start, end)
        # The index establishes holidays independently of this stock's missing bars.
        calendar_end = min((date.fromisoformat(end)+timedelta(days=14)).isoformat(), last_closed_date())
        if previous_span:
            calendar_end = min(max(calendar_end, previous_span['end_date']), last_closed_date())
        calendar = fetcher({'code': '000001', 'market': 'SH'}, calendar_start, calendar_end)
    except OSError as exc:
        raise ValidationError('行情获取失败，请稍后重试') from exc
    with server.lock, closing(connect(server.db_path)) as conn:
        identity = conn.execute('SELECT code,market FROM stocks WHERE id=?', (sid,)).fetchone()
        if not identity or (identity['code'], identity['market']) != (stock['code'], stock['market']):
            raise ValidationError('获取期间证券已变化，请重试')
        cache_quotes(conn, sid, records, start, end)
        if calendar:
            verified_end = max(r['date'] for r in calendar)
            with conn:
                for record in calendar:
                    conn.execute('INSERT OR IGNORE INTO market_calendar(date,source) VALUES (?,?)',
                                 (record['date'], record.get('source', '腾讯日线')))
                span = conn.execute('SELECT * FROM calendar_sync WHERE id=1').fetchone()
                # Join only overlapping verified spans; never claim a gap was checked.
                a, b = calendar_start, verified_end
                if span and a <= span['end_date'] and span['start_date'] <= b:
                    a, b = min(a, span['start_date']), max(b, span['end_date'])
                elif span:
                    # Another sync may have completed during the fetch. Keep its
                    # coverage if the two verified intervals remain disjoint.
                    a, b = span['start_date'], span['end_date']
                conn.execute('INSERT INTO calendar_sync VALUES (1,?,?) ON CONFLICT(id) DO UPDATE SET start_date=excluded.start_date,end_date=excluded.end_date', (a, b))
        # Cached closes can affect pending reconstruction previews, never saved returns.
        from .server import invalidate_calculations
        invalidate_calculations(server)
        return stock_history(conn, sid, start, payload['end'])
