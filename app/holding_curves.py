"""Daily stock curves clipped to holdings and rebased within the selected range."""
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from .reconstruction import ledger_rows, opening_state, share_change

DIVIDENDS = {'红利入账', '股息入账', '现金红利', '股息红利差异扣税', '红利税扣款'}


def holding_curves(conn, dates, series, daily):
    result = {s['id']: {'points': [], 'has_holdings': False, 'holding_segments': []} for s in series}
    if not dates:
        return result
    positions = {s['stock_id']: s['quantity'] for s in opening_state(conn)['positions']}
    entries = defaultdict(list)
    for entry in ledger_rows(conn):
        sid = entry['stock_id']
        if not sid or entry['date'] > dates[-1]:
            continue
        if entry['date'] < dates[0]:
            positions[sid] = positions.get(sid, 0) + share_change(entry)
        else:
            entries[entry['date']].append(entry)
    active = {}
    have_market = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='market_prices'").fetchone()

    def previous_value(sid, quantity, day):
        if not quantity:
            return 0
        if not have_market:
            return None
        row = conn.execute('''SELECT close_decimal FROM market_prices WHERE stock_id=? AND date=
                              (SELECT MAX(date) FROM market_calendar WHERE date<?)''', (sid, day)).fetchone()
        if row is None:
            return None
        return int((Decimal(row[0]) * quantity * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))

    for index, day in enumerate(dates):
        parts = defaultdict(list)

        def start_part(sid, quantity):
            if sid not in active:
                points = []
                result[sid]['holding_segments'].append(points)
                active[sid] = {'points': points, 'running': 0, 'allocation_known': True,
                               'number': len(result[sid]['holding_segments'])}
            part = {'session': active[sid], 'opening_quantity': quantity, 'cash_flow': 0, 'income': 0}
            parts[sid].append(part)
            return part

        for sid, quantity in positions.items():
            if quantity > 0:
                start_part(sid, quantity)
        for entry in entries[day]:
            sid = entry['stock_id']
            before = positions.get(sid, 0)
            delta = share_change(entry)
            positions[sid] = before + delta
            if sid not in active and delta:
                start_part(sid, before)
            part = parts[sid][-1] if parts[sid] else None
            if part:
                if entry['kind'] in ['buy', 'sell']:
                    part['cash_flow'] += entry['cash_change_cents']
                elif entry['kind'] == 'other' and entry['summary'] in DIVIDENDS:
                    part['income'] += entry['cash_change_cents']
            # A subsequent buy starts another session, including on this same date.
            if positions[sid] <= 0:
                active.pop(sid, None)
        for stock in series:
            sid = stock['id']
            source = stock['points'][index]
            day_parts = parts[sid]
            if not day_parts:
                result[sid]['points'].append({**source, 'holding': False, 'session_values': [],
                                             'value_cents': None, 'daily_cents': None})
                continue
            result[sid]['has_holdings'] = True
            amounts = []
            # Every part except the last ends at zero shares. Its realized P&L is
            # net cash flow less the previous closing value of any opening shares.
            # The final part receives the remainder of the recorded day's P&L.
            for part in day_parts[:-1]:
                opening_value = previous_value(sid, part['opening_quantity'], day)
                amounts.append(None if opening_value is None else part['cash_flow'] + part['income'] - opening_value)
            recorded = daily.get(day, {}).get(sid, 0)
            amounts.append(recorded - sum(amounts) if all(v is not None for v in amounts) else None)
            values = []
            for part, amount in zip(day_parts, amounts):
                session = part['session']
                if amount is not None:
                    session['running'] += amount
                else:
                    session['allocation_known'] = False
                known = source['daily_cents'] is not None and session['allocation_known']
                points = session['points']
                point = {**source, 'holding': True,
                         'value_cents': session['running'] if known else None,
                         'daily_cents': amount if known else None,
                         'gap_before': not points or source['gap_before'] or points[-1]['value_cents'] is None}
                points.append(point)
                values.append({'number': session['number'], 'value_cents': point['value_cents']})
            result[sid]['points'].append({**day_parts[-1]['session']['points'][-1], 'session_values': values})
    return result
