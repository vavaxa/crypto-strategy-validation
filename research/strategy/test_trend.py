import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd
from trend import generate_positions

DAY = 86400

def make(n=400, syms=("AAA", "BBB"), seed=0, vols=None, drift=0.002):
    rng = np.random.default_rng(seed)
    rows, oi, fu = [], [], []
    ts = 1_600_000_000 + np.arange(n) * DAY
    for j, s in enumerate(syms):
        sg = (vols or {}).get(s, 0.02)
        # regime-switching drift so trends exist
        d = np.where((np.arange(n) // 60) % 2 == 0, drift, -drift)
        r = d + rng.normal(0, sg, n)
        c = 100 * np.exp(np.cumsum(r))
        o = np.r_[c[0], c[:-1]]
        h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, sg / 3, n)))
        l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, sg / 3, n)))
        v = rng.lognormal(10, 0.5, n)
        rows.append(pd.DataFrame(dict(exchange="X", symbol=s, ts_utc=ts, open=o, high=h, low=l,
                                      close=c, volume=v, quote_volume=v * c, trades=100)))
        oi.append(pd.DataFrame(dict(exchange="X", symbol=s, ts_utc=ts, oi=np.cumsum(rng.normal(0, 1, n)) + 1000)))
        fu.append(pd.DataFrame(dict(exchange="X", symbol=s, ts_utc=ts, funding_rate=rng.normal(0.0002, 0.0004, n))))
    return pd.concat(rows), pd.concat(oi), pd.concat(fu)

BASE = dict(max_drawdown=None, atr_stop_k=3.0)

def W(pos):
    return pos.pivot(index="ts_utc", columns="symbol", values="target_weight")

def ntrades(w):
    return int(((w.abs() > 0) & (w.shift(1).fillna(0).abs() == 0)).sum().sum())

def test_no_lookahead_truncation():
    P, O, F = make()
    for style in ("breakout", "tsmom"):
        for extra in (dict(), dict(confirm_volume=True, confirm_oi=True, regime_filter=True,
                                   funding_filter=True, kelly_f=0.5, allow_short=True, max_drawdown=0.1)):
            prm = dict(style=style, **extra)
            full = W(generate_positions(P, O, F, prm))
            for cut in (150, 250, 333):
                tmax = P.ts_utc.unique()[cut]
                tr = lambda d: d[d.ts_utc <= tmax]
                part = W(generate_positions(tr(P), tr(O), tr(F), prm))
                pd.testing.assert_frame_equal(full.loc[part.index], part, check_exact=False, atol=1e-12)

def test_future_bar_change_does_not_affect_t():
    P, O, F = make()
    prm = dict(style="breakout", confirm_volume=True)
    base = W(generate_positions(P, O, F, prm))
    tt = P.ts_utc.unique()[200]
    P2 = P.copy()
    m = P2.ts_utc >= tt          # perturb bar t itself and everything after
    for c in ("open", "high", "low", "close", "volume"):
        P2.loc[m, c] = P2.loc[m, c] * 3.0
    new = W(generate_positions(P2, O, F, prm))
    # weight at t depends on bars < t only
    pd.testing.assert_frame_equal(base[base.index <= tt], new[new.index <= tt])

def test_entry_is_next_bar():
    P, O, F = make()
    w = W(generate_positions(P, O, F, dict(BASE)))
    assert (w.iloc[0] == 0).all()

def test_filters_cut_trades():
    P, O, F = make(n=600, syms=("AAA", "BBB", "CCC"), seed=3)
    for style in ("breakout", "tsmom"):
        base = ntrades(W(generate_positions(P, O, F, dict(BASE, style=style))))
        assert base > 0
        for flag in ("confirm_volume", "confirm_oi", "regime_filter", "funding_filter"):
            n = ntrades(W(generate_positions(P, O, F, dict(BASE, style=style, **{flag: True}))))
            if flag == "regime_filter" and style == "breakout":   # gates holding too -> compare time in market
                e0 = (W(generate_positions(P, O, F, dict(BASE, style=style))).abs() > 0).sum().sum()
                e1 = (W(generate_positions(P, O, F, dict(BASE, style=style, regime_filter=True))).abs() > 0).sum().sum()
                assert e1 < e0, (style, e1, e0)
            else:
                if style == "breakout" and flag != "regime_filter":
                    assert n < base, (style, flag, n, base)
                else:   # tsmom: path-dependent -> filters can only delay the first entry
                    w0 = W(generate_positions(P, O, F, dict(BASE, style=style)))
                    w1 = W(generate_positions(P, O, F, dict(BASE, style=style, **{flag: True})))
                    first = lambda w: (w.abs() > 0).values.argmax(axis=0)
                    assert (first(w1) >= first(w0)).all(), flag

def test_missing_oi_funding():
    P, _, _ = make()
    a = generate_positions(P, None, None, dict(confirm_oi=True, funding_filter=True))
    b = generate_positions(P, None, None, dict())
    assert np.allclose(a.target_weight, b.target_weight)
    c = generate_positions(P, None, None, dict(confirm_oi=True, missing_data="block"))
    assert (c.target_weight == 0).all()

def test_vol_targeting_smaller_weight_high_vol():
    P, O, F = make(n=500, syms=("LOW", "HIGH"), seed=5, vols={"LOW": 0.01, "HIGH": 0.05}, drift=0.004)
    w = W(generate_positions(P, O, F, dict(BASE, style="tsmom", vol_targeting=True, target_vol=0.2, max_weight=5, max_gross=100)))
    both = (w["LOW"] > 0) & (w["HIGH"] > 0)
    assert both.sum() > 20
    assert (w.loc[both, "HIGH"] < w.loc[both, "LOW"]).mean() > 0.95
    assert w.loc[both, "HIGH"].mean() < 0.5 * w.loc[both, "LOW"].mean()

def test_long_only_default_and_caps():
    P, O, F = make()
    w = W(generate_positions(P, O, F, dict(style="tsmom")))
    assert (w.values >= 0).all() and (w.abs().sum(axis=1) <= 1.0 + 1e-9).all()
    ws = W(generate_positions(P, O, F, dict(style="tsmom", allow_short=True)))
    assert (ws.values < 0).any()

def test_drawdown_kill_switch():
    P, O, F = make(n=500, seed=7, drift=0.003)
    a = W(generate_positions(P, O, F, dict(style="tsmom", max_drawdown=None)))
    b = W(generate_positions(P, O, F, dict(style="tsmom", max_drawdown=0.02, dd_cooldown=30)))
    assert b.abs().sum().sum() < a.abs().sum().sum()
    # flat during cooldown right after the trip
    tot = b.abs().sum(axis=1).values
    assert (tot == 0).sum() > (a.abs().sum(axis=1).values == 0).sum() + 20

def test_atr_stop_exits_on_crash():
    n = 200
    ts = 1_600_000_000 + np.arange(n) * DAY
    c = np.r_[np.linspace(100, 200, 120), np.linspace(200, 100, 80)]
    P = pd.DataFrame(dict(exchange="X", symbol="Z", ts_utc=ts, open=c, high=c * 1.005, low=c * 0.995,
                          close=c, volume=1.0, quote_volume=1.0, trades=1))
    tight = W(generate_positions(P, None, None, dict(style="tsmom", mom_lookback=30, atr_stop_k=2.0, max_drawdown=None)))
    assert (tight["Z"].iloc[100:120] > 0).any()
    assert tight["Z"].iloc[135] == 0
