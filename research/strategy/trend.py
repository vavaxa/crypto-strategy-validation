"""Trend-following research module: SIGNAL + SIZING + RISK. Research only, no orders.

generate_positions(price_df, oi_df, funding_df, params) -> DataFrame[symbol, ts_utc, target_weight]

Timing convention (no lookahead):
  * indicators at bar i use only bars <= i (closed bars; rolling windows are trailing);
  * the decision made at the close of bar i is the weight HELD during bar i+1 (entry at
    the next bar). So row ts_utc = T carries target_weight computed from bars < T only;
  * portfolio equity / drawdown used for the kill switch is built from weights already
    applied and returns already realised (close-to-close) up to the decision bar;
  * OI / funding are aligned with as-of (last value with ts <= bar ts, forward-fill only).
Pure function: no network, no disk.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULTS = dict(
    style="breakout",        # 'breakout' | 'tsmom'
    exchange=None,           # None -> first exchange (alphabetical) per symbol
    bars_per_year=365.0,     # annualisation of vol (365 for 1d bars)
    # signal
    donchian_n=20,           # breakout lookback (prior bars, excl. current)
    exit_n=10,               # breakout exit: close < min low of prior exit_n bars
    mom_lookback=30,         # tsmom lookback L
    mom_threshold=0.0,
    allow_short=False,
    # mechanism filters
    confirm_volume=False, vol_median_n=20,
    confirm_oi=False, oi_n=5,
    regime_filter=False, regime_ma_n=100,
    funding_filter=False, funding_max=0.0005, funding_min=-0.0005,
    missing_data="skip",     # oi/funding absent: 'skip' (filter ignored) | 'block' (no entries)
    # sizing
    vol_targeting=True, target_vol=0.20, vol_span=20, fixed_weight=0.2,
    max_weight=0.5, max_gross=1.0,
    kelly_f=None, kelly_n=90,
    # risk
    atr_n=14, atr_stop_k=3.0,        # atr_stop_k=None disables
    max_drawdown=0.25, dd_cooldown=20,  # max_drawdown=None disables
)


def _wide(df, col, ex):
    d = df
    if "exchange" in d.columns:
        if ex is not None:
            d = d[d["exchange"] == ex]
        else:
            first = d.groupby("symbol")["exchange"].min()
            d = d[d["exchange"] == d["symbol"].map(first)]
    d = d.drop_duplicates(["symbol", "ts_utc"], keep="last")
    return d.pivot(index="ts_utc", columns="symbol", values=col).sort_index()


def _asof(df, col, ex, index, columns):
    """Causal as-of alignment onto price index (ffill only)."""
    if df is None or len(df) == 0:
        return None
    w = _wide(df, col, ex)
    w = w.reindex(w.index.union(index)).sort_index().ffill().reindex(index)
    return w.reindex(columns=columns)


def generate_positions(price_df, oi_df=None, funding_df=None, params=None, member_mask=None) -> pd.DataFrame:
    p = {**DEFAULTS, **(params or {})}
    if p["style"] not in ("breakout", "tsmom"):
        raise ValueError("style must be 'breakout' or 'tsmom'")
    empty = pd.DataFrame(columns=["symbol", "ts_utc", "target_weight"])
    if price_df is None or len(price_df) == 0:
        return empty
    ex = p["exchange"]
    close = _wide(price_df, "close", ex)
    high = _wide(price_df, "high", ex).reindex(close.index)
    low = _wide(price_df, "low", ex).reindex(close.index)
    volu = _wide(price_df, "volume", ex).reindex(close.index)
    idx, cols = close.index, close.columns
    T, S = close.shape
    C = close.values.astype(float)

    ret = close.pct_change(fill_method=None)
    # --- indicators (trailing windows, value at i uses bars <= i) ---
    up = high.rolling(p["donchian_n"]).max().shift(1)   # prior N bars
    dn = low.rolling(p["donchian_n"]).min().shift(1)
    ex_lo = low.rolling(p["exit_n"]).min().shift(1)
    ex_hi = high.rolling(p["exit_n"]).max().shift(1)
    mom = close / close.shift(p["mom_lookback"]) - 1.0
    ma = close.rolling(p["regime_ma_n"]).mean()
    pc = close.shift(1)
    tr = pd.DataFrame(np.fmax(np.fmax((high - low).values, (high - pc).abs().values),
                              (low - pc).abs().values), index=idx, columns=cols)
    tr = tr.where(pc.notna() & high.notna() & low.notna())
    atr = tr.ewm(alpha=1.0 / p["atr_n"], adjust=False, min_periods=p["atr_n"]).mean()
    vol = ret.pow(2).ewm(span=p["vol_span"], adjust=False, min_periods=p["vol_span"]).mean().pow(0.5)

    ones = pd.DataFrame(True, index=idx, columns=cols)
    # --- raw signal ---
    if p["style"] == "breakout":
        sig_l, sig_s = close > up, close < dn
        hold_l, hold_s = close > ex_lo, close < ex_hi
    else:
        sig_l, sig_s = mom > p["mom_threshold"], mom < -p["mom_threshold"]
        hold_l, hold_s = mom > 0, mom < 0
    # --- regime (gates entry and holding) ---
    if p["regime_filter"]:
        reg_l, reg_s = close > ma, close < ma
    else:
        reg_l = reg_s = ones
    # --- entry filters ---
    f_all = ones.copy()
    block = p["missing_data"] == "block"
    if p["confirm_volume"]:
        f_all &= volu > volu.rolling(p["vol_median_n"]).median().shift(1)
    if p["confirm_oi"]:
        oi = _asof(oi_df, "oi", ex, idx, cols)
        if oi is None:
            if block:
                f_all &= False
        else:
            f_all &= oi > oi.shift(p["oi_n"])
    f_l, f_s = f_all.copy(), f_all.copy()
    if p["funding_filter"]:
        fr = _asof(funding_df, "funding_rate", ex, idx, cols)
        if fr is None:
            if block:
                f_l &= False
                f_s &= False
        else:
            f_l &= fr <= p["funding_max"]      # don't buy crowded longs
            f_s &= fr >= p["funding_min"]
    entry_l = (sig_l & f_l & reg_l).fillna(False).values
    entry_s = (sig_s & f_s & reg_s).fillna(False).values & bool(p["allow_short"])
    raw_l, raw_s = sig_l.fillna(False).values, sig_s.fillna(False).values
    keep_l = (hold_l & reg_l).fillna(False).values
    keep_s = (hold_s & reg_s).fillna(False).values & bool(p["allow_short"])
    if member_mask is not None:
        # point-in-time universe: mask[i] must be known at the close of bar i (trailing data only).
        # Non-members cannot be entered and are exited (decision at close i, held from i+1).
        M = member_mask.reindex(index=idx, columns=cols).fillna(False).values.astype(bool)
        entry_l = entry_l & M; entry_s = entry_s & M; keep_l = keep_l & M; keep_s = keep_s & M

    # --- sizing inputs ---
    if p["vol_targeting"]:
        size = (p["target_vol"] / (vol * np.sqrt(p["bars_per_year"]))).clip(upper=p["max_weight"])
    else:
        size = pd.DataFrame(min(p["fixed_weight"], p["max_weight"]), index=idx, columns=cols)
    size = size.where(vol.notna() & (vol > 0), 0.0) if p["vol_targeting"] else size
    SZ = size.fillna(0.0).values
    if p["kelly_f"]:
        mu = ret.rolling(p["kelly_n"]).mean()
        var = ret.rolling(p["kelly_n"]).var()
        kel = (mu / var).replace([np.inf, -np.inf], np.nan)
        KL, KS = (p["kelly_f"] * kel.clip(lower=0)).fillna(0).values, (p["kelly_f"] * (-kel).clip(lower=0)).fillna(0).values
    else:
        KL = KS = None
    ATR = atr.values
    R = np.nan_to_num(ret.values, nan=0.0)

    pos = np.zeros(S)
    trail = np.full(S, np.nan)
    blocked = np.zeros(S, bool)          # stopped out; wait for raw signal to turn off
    dec = np.zeros((T, S))               # decision at close of bar i (held during i+1)
    eq, peak, halted_until = 1.0, 1.0, -1
    k, mdd = p["atr_stop_k"], p["max_drawdown"]
    for i in range(T):
        w_applied = dec[i - 1] if i > 0 else np.zeros(S)
        eq *= 1.0 + float(np.dot(w_applied, R[i]))
        peak = max(peak, eq)
        if halted_until >= 0:
            if i < halted_until:
                pos[:] = 0; dec[i] = 0; continue
            halted_until = -1; peak = eq
        if mdd is not None and 1.0 - eq / peak > mdd:
            halted_until = i + int(p["dd_cooldown"]) + 1
            pos[:] = 0; dec[i] = 0; blocked[:] = True; continue
        c = C[i]
        # stops
        if k is not None:
            with np.errstate(invalid="ignore"):
                hit = ((pos > 0) & (c < trail)) | ((pos < 0) & (c > trail))
            blocked |= hit
            pos[hit] = 0
        # exits on signal decay
        pos[(pos > 0) & ~keep_l[i]] = 0
        pos[(pos < 0) & ~keep_s[i]] = 0
        blocked &= (raw_l[i] | raw_s[i])
        flat = pos == 0
        go_l = flat & entry_l[i] & ~blocked & ~np.isnan(c)
        go_s = flat & entry_s[i] & ~blocked & ~np.isnan(c) & ~go_l
        pos[go_l] = 1; pos[go_s] = -1
        # trail update
        if k is not None:
            a = ATR[i]
            nl = go_l | go_s
            with np.errstate(invalid="ignore"):
                cand_l = c - k * a
                cand_s = c + k * a
                trail = np.where(nl & (pos > 0), cand_l, trail)
                trail = np.where(nl & (pos < 0), cand_s, trail)
                old = ~nl
                trail = np.where(old & (pos > 0), np.fmax(trail, cand_l), trail)
                trail = np.where(old & (pos < 0), np.fmin(trail, cand_s), trail)
            # no ATR -> cannot stop: fmax/fmin with nan keeps trail value
            trail[pos == 0] = np.nan
        w = pos * SZ[i]
        if KL is not None:
            cap = np.where(pos > 0, KL[i], KS[i])
            w = np.sign(w) * np.minimum(np.abs(w), cap)
        g = np.abs(w).sum()
        if g > p["max_gross"]:
            w = w * (p["max_gross"] / g)
        dec[i] = w

    # shift: weight decided at close of i is held in bar i+1 (row ts of bar i+1)
    wdf = pd.DataFrame(dec, index=idx, columns=cols).shift(1).fillna(0.0)
    out = pd.DataFrame({"ts_utc": np.repeat(idx.values, S), "symbol": np.tile(np.asarray(cols), T),
                        "target_weight": wdf.values.ravel()})
    return out[["symbol", "ts_utc", "target_weight"]].sort_values(["symbol", "ts_utc"]).reset_index(drop=True)


PARAM_GRID = dict(
    style=["breakout", "tsmom"],
    donchian_n=[10, 20, 55], exit_n=[5, 10, 20],
    mom_lookback=[14, 30, 60],
    confirm_volume=[False, True], confirm_oi=[False, True],
    regime_filter=[False, True], funding_filter=[False, True],
    vol_targeting=[False, True], target_vol=[0.10, 0.20],
    kelly_f=[None, 0.25, 0.5], atr_stop_k=[None, 2.0, 3.0],
    max_drawdown=[None, 0.15, 0.25], allow_short=[False, True],
)
