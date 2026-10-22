#!/usr/bin/env python
"""Phase A market-making mark-out (PREREG_MM_PHASEA.md). MEASUREMENT ONLY, no orders.

Fill rule (OPTIMISTIC UPPER BOUND, front of queue, zero latency):
  resting bid at best bid B (last bookTicker event strictly BEFORE the trade) is filled by an
  aggTrade with is_buyer_maker=True and price <= B; resting ask at A filled by is_buyer_maker=False, price >= A.
  Fill price = our limit price (B or A). One fill per side per fixed 30s UTC bucket (first qualifying trade),
  so mark-out windows (max 30s) never overlap -> no double counting.
Mark-out (bps of fill-time mid): buy (mid_h - B)/mid0*1e4 ; sell (A - mid_h)/mid0*1e4.
  mid_h = mid of last bookTicker event_time <= t+h. Future mid used ONLY as measurement.
Usage: mm_markout.py collect SYM [SYM...] | analyze
"""
import sys, os, io, json, zipfile, urllib.request, datetime as dt
import numpy as np, pandas as pd
import pyarrow.csv as pacsv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = f'{ROOT}/data/mm/raw'
OUT = f'{ROOT}/data/mm/fills'
BASE = 'https://data.binance.vision/data/futures/um/daily'
DAYS = [(dt.date(2023, 8, 1) + dt.timedelta(d)).isoformat() for d in range(31)]
CRASH = '2023-08-17'
HZ = [1000, 5000, 30000]  # ms
BUCKET = 30000


def fetch(kind, sym, day):
    os.makedirs(TMP, exist_ok=True)
    p = f'{TMP}/{sym}-{kind}-{day}.zip'
    urllib.request.urlretrieve(f'{BASE}/{kind}/{sym}/{sym}-{kind}-{day}.zip', p)
    return p


def read_zip(p, cols, types):
    with zipfile.ZipFile(p) as z:
        with z.open(z.namelist()[0]) as f:
            t = pacsv.read_csv(f, convert_options=pacsv.ConvertOptions(include_columns=cols, column_types=types))
    return t


def process_day(sym, day):
    pb = fetch('bookTicker', sym, day)
    pt = fetch('aggTrades', sym, day)
    try:
        b = read_zip(pb, ['best_bid_price', 'best_ask_price', 'event_time'],
                     {'best_bid_price': 'float64', 'best_ask_price': 'float64', 'event_time': 'int64'})
        et = b['event_time'].to_numpy(); bid = b['best_bid_price'].to_numpy(); ask = b['best_ask_price'].to_numpy()
        del b
        o = np.argsort(et, kind='stable'); et, bid, ask = et[o], bid[o], ask[o]
        ok = (bid > 0) & (ask > 0) & (ask >= bid)
        et, bid, ask = et[ok], bid[ok], ask[ok]
        chg = np.ones(len(et), bool); chg[1:] = (bid[1:] != bid[:-1]) | (ask[1:] != ask[:-1])
        et, bid, ask = et[chg], bid[chg], ask[chg]
        mid = (bid + ask) / 2
        sp = (ask - bid) / mid * 1e4
        dtw = np.diff(et, append=et[-1]); tw_spread = float((sp * dtw).sum() / max(dtw.sum(), 1))
        tr = read_zip(pt, ['price', 'transact_time', 'is_buyer_maker'],
                      {'price': 'float64', 'transact_time': 'int64', 'is_buyer_maker': 'bool'})
        tp = tr['price'].to_numpy(); tt = tr['transact_time'].to_numpy(); tm = tr['is_buyer_maker'].to_numpy(zero_copy_only=False).astype(bool)
        del tr
        i0 = np.searchsorted(et, tt, 'left') - 1
        valid = (i0 >= 0) & (tt + max(HZ) <= et[-1])
        rows = []; ncand = {}
        for side, flag in (('bid', True), ('ask', False)):
            cond = valid & (tm == flag)
            ii = np.where(cond, i0, 0)
            lvl = bid[ii] if side == 'bid' else ask[ii]
            cand = cond & ((tp <= lvl) if side == 'bid' else (tp >= lvl))
            ncand[side] = int(cand.sum())
            ci = np.where(cand)[0]
            if len(ci) == 0: continue
            bk = tt[ci] // BUCKET
            _, first = np.unique(bk, return_index=True)  # first (earliest; trades time-sorted) per bucket
            ci = ci[first]
            t0 = tt[ci]; k = i0[ci]
            px = lvl[ci]; m0 = mid[k]
            d = {'ts': t0, 'side': side, 'px': px, 'mid0': m0, 'spread_bps': sp[k]}
            for h in HZ:
                kh = np.searchsorted(et, t0 + h, 'right') - 1
                mh = mid[kh]
                d[f'mo{h//1000}'] = ((mh - px) if side == 'bid' else (px - mh)) / m0 * 1e4
            rows.append(pd.DataFrame(d))
        df = pd.concat(rows) if rows else pd.DataFrame()
        df.insert(0, 'sym', sym); df.insert(1, 'day', day)
        return df, {'sym': sym, 'day': day, 'book_states': int(len(et)), 'trades': int(len(tt)),
                    'tw_spread_bps': tw_spread, 'cand_bid': ncand['bid'], 'cand_ask': ncand['ask'], 'fills': int(len(df))}
    finally:
        for p in (pb, pt):
            try: os.remove(p)
            except OSError: pass


def collect(syms):
    os.makedirs(OUT, exist_ok=True)
    for s in syms:
        for d in DAYS:
            f = f'{OUT}/{s}_{d}.parquet'
            if os.path.exists(f): continue
            try:
                df, st = process_day(s, d)
            except Exception as e:
                print('FAIL', s, d, repr(e)[:200], flush=True)
                with open(f'{OUT}/{s}_{d}.fail', 'w') as fh: fh.write(repr(e)[:500])
                continue
            df.to_parquet(f, index=False)
            with open(f'{OUT}/{s}_{d}.json', 'w') as fh: json.dump(st, fh)
            print('ok', st, flush=True)


def nw_t(x, lag):
    x = np.asarray(x, float); n = len(x)
    if n < 5: return float('nan')
    mu = x.mean(); e = x - mu
    v = e @ e / n
    for l in range(1, min(lag, n - 1) + 1):
        v += 2 * (1 - l / (lag + 1)) * (e[l:] @ e[:-l]) / n
    return float(mu / np.sqrt(v / n)) if v > 0 else float('nan')


def stats(x):
    x = np.asarray(x, float)
    if len(x) == 0: return {}
    sd = x.std()
    sk = float(((x - x.mean()) ** 3).mean() / sd ** 3) if sd > 0 else 0.0
    return {'n': int(len(x)), 'mean': float(x.mean()), 'median': float(np.median(x)), 'p5': float(np.percentile(x, 5)),
            'p1': float(np.percentile(x, 1)), 'skew': sk}


def analyze(syms):
    res = {}
    for s in syms:
        fs = sorted(f for f in os.listdir(OUT) if f.startswith(s + '_') and f.endswith('.parquet'))
        if not fs: continue
        df = pd.concat([pd.read_parquet(f'{OUT}/{f}') for f in fs], ignore_index=True)
        meta = [json.load(open(f'{OUT}/{f[:-8]}.json')) for f in fs]
        r = {'days_ok': len(fs), 'tw_spread_bps_mean': float(np.mean([m['tw_spread_bps'] for m in meta])),
             'fill_spread_bps_mean': float(df.spread_bps.mean()), 'cand': {'bid': sum(m['cand_bid'] for m in meta), 'ask': sum(m['cand_ask'] for m in meta)}}
        df['hour'] = pd.to_datetime(df.ts, unit='ms').dt.floor('h')
        for h in (1, 5, 30):
            c = f'mo{h}'
            rh = {}
            for part, sub in (('all', df), ('crash', df[df.day == CRASH]), ('calm', df[df.day != CRASH])):
                if len(sub) == 0: continue
                bi = sub[sub.side == 'bid'][c]; ai = sub[sub.side == 'ask'][c]
                mb, ma = bi.mean(), ai.mean()
                e = {'bid': stats(bi), 'ask': stats(ai), 'both': stats(sub[c]),
                     'rt_gross_bps': float(mb + ma)}
                for fee in (0, 1, 2):
                    e[f'rt_net_fee{fee}'] = float(mb + ma - 2 * fee)
                    e[f'side_net_fee{fee}'] = float(sub[c].mean() - fee)
                # hourly paired round-trip series (bid-mean + ask-mean) for NW
                g = sub.groupby(['hour', 'side'])[c].mean().unstack()
                g = g.dropna()
                if len(g) > 10:
                    rt = (g['bid'] + g['ask']).values
                    e['hours_paired'] = int(len(rt))
                    e['nw_t_rt_gross'] = nw_t(rt, 24)
                    for fee in (1, 2):
                        e[f'nw_t_rt_net_fee{fee}'] = nw_t(rt - 2 * fee, 24)
                    # daily series as robustness
                    gd = sub.groupby(['day', 'side'])[c].mean().unstack().dropna()
                    rtd = (gd['bid'] + gd['ask']).values
                    e['days_paired'] = int(len(rtd)); e['daily_rt_gross_mean'] = float(rtd.mean())
                    e['daily_rt_gross_t_iid'] = float(rtd.mean() / (rtd.std(ddof=1) / np.sqrt(len(rtd)))) if len(rtd) > 2 and rtd.std() > 0 else float('nan')
                rh[part] = e
            r[f'h{h}s'] = rh
        # per-day RT gross at 30s
        gd = df.groupby(['day', 'side']).mo30.mean().unstack()
        r['daily_rt_gross_30s'] = {d: float(v) for d, v in (gd['bid'] + gd['ask']).items()}
        res[s] = r
    return res


if __name__ == '__main__':
    if sys.argv[1] == 'collect': collect(sys.argv[2:])
    elif sys.argv[1] == 'analyze':
        out = analyze(sys.argv[2:]); json.dump(out, open(f'{ROOT}/reports/mm_markout_raw.json', 'w'), indent=1)
        print('written')
