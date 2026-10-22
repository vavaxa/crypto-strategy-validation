import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import numpy as np, pandas as pd
from costs import CostParams, apply_costs, round_trip_cost_bps, impact_bps

T0 = pd.Timestamp("2026-01-01 00:00")
P = CostParams(min_spread_bps=0.0, participation_cap=None)

def mk(adv=1e9, funding=None, bars=None):
    rows = []
    for i in range(6):
        r = {"ts": T0 + pd.Timedelta(hours=8 * i), "symbol": "X", "adv_usd": adv}
        if funding is not None: r["funding_rate"] = funding
        if bars is not None: r["bar_volume_usd"] = bars
        rows.append(r)
    return pd.DataFrame(rows)

def tr(side, n, maker=False, ts=T0, k=1):
    return pd.DataFrame({"ts": [ts] * k, "symbol": "X", "side": side, "notional_usd": n, "is_maker": maker})

def test_impact_sqrt():
    a, b = impact_bps(1e5, 1e9, P), impact_bps(4e5, 1e9, P)
    assert abs(b / a - 2.0) < 1e-9

def test_large_order_big_impact():
    small = round_trip_cost_bps(1e4, 1e9, P); big = round_trip_cost_bps(1e8, 1e9, P)
    assert big > small * 10 and impact_bps(1e8, 1e9, P) > 100

def test_maker_cheaper():
    assert round_trip_cost_bps(1e5, 1e9, P, True, True) < round_trip_cost_bps(1e5, 1e9, P)

def test_spread_floor():
    p = P.replace(min_spread_bps=4.0)
    assert float(impact_bps(1.0, 1e9, p)) == 2.0

def test_funding_sign_flips():
    m = mk(funding=0.0001)
    lo = apply_costs(tr("buy", 1e5), m, P); sh = apply_costs(tr("sell", 1e5), m, P)
    assert lo.funding_usd.sum() > 0 and sh.funding_usd.sum() < 0
    assert abs(lo.funding_usd.sum() + sh.funding_usd.sum()) < 1e-9

def test_funding_stops_when_flat():
    m = mk(funding=0.0001)
    t = pd.concat([tr("buy", 1e5), tr("sell", 1e5, ts=T0 + pd.Timedelta(hours=9))])
    r = apply_costs(t, m, P)
    assert abs(r.funding_usd.sum() - 1e5 * 0.0001) < 1e-9  # only 08:00 event; trade closed 09:00 -> 16:00+ none; 00:00 not strictly after entry

def test_borrow_short_only():
    p = P.replace(borrow_rate_annual=0.10, end_ts=T0 + pd.Timedelta(days=365))
    assert apply_costs(tr("sell", 1e5), mk(), p).borrow_usd.sum() == np.float64(1e4) or \
        abs(apply_costs(tr("sell", 1e5), mk(), p).borrow_usd.sum() - 1e4) < 1e-6
    assert apply_costs(tr("buy", 1e5), mk(), p).borrow_usd.sum() == 0

def test_participation_cap():
    m = mk(bars=1e6)  # cap 10% -> 1e5 per bar
    p = P.replace(participation_cap=0.10)
    r = apply_costs(tr("buy", 3.5e5), m, p)
    assert r.notional_usd.max() <= 1e5 + 1e-6
    assert abs(r.notional_usd.sum() - 3.5e5) < 1e-6 and len(r) == 4  # remainder carried
    r2 = apply_costs(tr("buy", 1e7), m, p)  # cannot finish within data
    assert r2.notional_usd.sum() <= 6e5 + 1e-6 and r2.attrs["unfilled"]

def test_net_pnl_and_breakdown():
    t = tr("buy", 1e5); t["gross_pnl_usd"] = 500.0
    r = apply_costs(t, mk(funding=0.0), P.replace(min_spread_bps=2.0, impact_k=0.0))
    row = r.iloc[0]
    assert abs(row.fee_usd - 45.0) < 1e-9 and abs(row.impact_usd - 10.0) < 1e-9
    assert abs(row.net_pnl_usd - (500 - row.total_cost_usd)) < 1e-9
