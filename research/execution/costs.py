"""Execution cost model for crypto perps (fees, impact, funding, borrow, partial fills).

ASSUMPTIONS / STUBS (explicit):
  * borrow_rate_annual = 0.0 default: STUB. No borrow-rate data. On USDT-M perps a short
    pays no borrow (only funding); set >0 to stress synthetic short financing / spot margin.
  * Position value for funding/borrow = signed cumulative trade notional (cost basis);
    no mark-price path is available, so mark-to-market drift is ignored.
  * impact uses the square-root law impact_frac = k*sqrt(q/ADV) ("Almgren" form). The
    coefficient k is NOT a constant: by that law k ~= Y*sigma_daily (Y~0.5-1), so it is
    per-symbol -- BTC ~0.015-0.03, high-vol alts ~0.05-0.08. The default impact_k=0.5 is a
    DELIBERATELY CONSERVATIVE STUB that overstates realistic impact ~20-30x (e.g. $1M in BTC
    is single-digit bps, not ~70bp). Use impact_k_from_vol() for a calibrated per-symbol
    value; cost-sensitive verdicts MUST be read as impact-calibration-dependent. Makers: none.
  * funding_default_rate_8h=0.0 when market_df has no funding_rate (funding then 0).
Conventions: costs are positive = money lost; funding may be negative (received).
"""
from __future__ import annotations
from dataclasses import dataclass, replace, asdict
import numpy as np
import pandas as pd

FUNDING_INTERVAL = pd.Timedelta(hours=8)


@dataclass
class CostParams:
    taker_fee: float = 0.00045        # 0.045% Binance USD-M taker
    maker_fee: float = 0.00018        # 0.018% (as specified)
    impact_k: float = 0.5             # CONSERVATIVE STUB; ~20-30x high. Prefer impact_k_from_vol()
    min_spread_bps: float = 1.0       # full spread floor; taker pays >= half of it
    maker_impact: bool = False        # makers pay no impact/spread
    borrow_rate_annual: float = 0.0   # short financing, STUB (see module doc)
    funding_default_rate_8h: float = 0.0
    participation_cap: float | None = 0.10  # max share of bar volume per fill; None = off
    end_ts: pd.Timestamp | None = None  # horizon for borrow accrual of last trade

    def replace(self, **kw):
        return replace(self, **kw)


def _params(p):
    if p is None:
        return CostParams()
    if isinstance(p, dict):
        return CostParams(**p)
    return p


def _sign(side: pd.Series) -> np.ndarray:
    if side.dtype.kind in "iuf":
        return np.sign(side.to_numpy(float))
    return np.where(side.astype(str).str.lower().isin(["buy", "b", "long", "1"]), 1.0, -1.0)


def impact_bps(notional, adv, params, is_maker=False):
    """Taker slippage in bps: max(half-spread floor, k*sqrt(q/ADV)). Makers: 0."""
    p = _params(params)
    notional = np.asarray(notional, float)
    adv = np.asarray(adv, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        imp = p.impact_k * np.sqrt(np.abs(notional) / adv) * 1e4
    imp = np.where(np.isfinite(imp), imp, 0.0)
    out = np.maximum(imp, p.min_spread_bps / 2.0)
    if p.maker_impact:
        return out
    return np.where(np.asarray(is_maker, bool), 0.0, out)



def impact_k_from_vol(sigma_daily, Y=0.5):
    """Calibrated per-symbol square-root-impact coefficient k = Y * sigma_daily.

    The square-root law gives impact_frac = Y * sigma * sqrt(participation) with Y~0.5-1,
    so the coefficient in impact_frac = k*sqrt(q/ADV) is k = Y*sigma_daily, i.e. per-symbol,
    not a global constant. Example: BTC sigma_daily~0.03 -> k~0.015; alt sigma_daily~0.08 ->
    k~0.04. Feed the resulting k into CostParams(impact_k=...) per symbol. Y is a free
    parameter that should be fixed in a pre-registration, then stress-swept (sigma/2, sigma, 2 sigma).
    """
    return Y * np.asarray(sigma_daily, float)

def apply_participation_cap(trades_df, market_df, params):
    """Split orders into child fills capped at participation_cap*bar_volume_usd per bar.

    Unfilled remainder rolls to the next bars of that symbol. Needs market_df columns
    ts, symbol, bar_volume_usd. Returns fills with parent_id, ordered_usd, filled
    notional_usd; leftover at end of data is returned in attrs['unfilled'] (list) and
    as rows with notional 0 are NOT emitted.
    """
    p = _params(params)
    t = trades_df.reset_index(drop=True).copy()
    t["parent_id"] = t.index
    if p.participation_cap is None or "bar_volume_usd" not in market_df.columns:
        t["ordered_usd"] = t["notional_usd"]
        t.attrs["unfilled"] = []
        return t
    bars = {s: g.sort_values("ts")[["ts", "bar_volume_usd"]].to_numpy(object)
            for s, g in market_df.groupby("symbol")}
    used: dict = {}
    rows, unfilled = [], []
    for r in t.sort_values(["ts"], kind="stable").itertuples(index=False):
        rem = float(r.notional_usd)
        d = r._asdict()
        arr = bars.get(r.symbol)
        if arr is None:
            rows.append({**d, "ordered_usd": rem}); continue
        for bts, vol in arr:
            if rem <= 1e-9:
                break
            if bts < r.ts:
                continue
            cap = p.participation_cap * float(vol) - used.get((r.symbol, bts), 0.0)
            fill = min(rem, max(cap, 0.0))
            if fill <= 0:
                continue
            used[(r.symbol, bts)] = used.get((r.symbol, bts), 0.0) + fill
            rows.append({**d, "ts": bts, "notional_usd": fill, "ordered_usd": float(r.notional_usd)})
            rem -= fill
        if rem > 1e-9:
            unfilled.append((r.parent_id, r.symbol, rem))
    out = pd.DataFrame(rows).sort_values("ts", kind="stable").reset_index(drop=True)
    out.attrs["unfilled"] = unfilled
    return out


def apply_costs(trades_df, market_df, params=None):
    """Per-trade cost breakdown + net P&L.

    trades_df: ts, symbol, side ('buy'/'sell' or +1/-1), notional_usd, is_maker
               [optional gross_pnl_usd].
    market_df: ts, symbol, adv_usd [opt funding_rate (per 8h, at funding ts),
               opt bar_volume_usd].  ADV taken as-of trade ts (backward).
    Returns DataFrame with fee_usd, impact_usd, funding_usd, borrow_usd, total_cost_usd,
    gross_pnl_usd, net_pnl_usd (+ bps columns). Funding/borrow of a holding period is
    attributed to the trade that last changed the position before it.
    """
    p = _params(params)
    t = apply_participation_cap(trades_df, market_df, p)
    unfilled = list(t.attrs.get("unfilled", []))
    t = t.sort_values("ts", kind="stable").reset_index(drop=True)
    t["ts"] = pd.to_datetime(t["ts"])
    m = market_df.copy(); m["ts"] = pd.to_datetime(m["ts"])
    # ADV as-of
    adv = m.dropna(subset=["adv_usd"]).sort_values("ts")[["ts", "symbol", "adv_usd"]]
    t = pd.merge_asof(t, adv, on="ts", by="symbol", direction="backward")
    if t["adv_usd"].isna().any():  # fall back to earliest ADV for symbol
        first = adv.groupby("symbol")["adv_usd"].first()
        t["adv_usd"] = t["adv_usd"].fillna(t["symbol"].map(first))
    sgn = _sign(t["side"])
    t["signed_usd"] = sgn * t["notional_usd"].astype(float)
    mk = t["is_maker"].astype(bool).to_numpy()
    fee_rate = np.where(mk, p.maker_fee, p.taker_fee)
    t["fee_usd"] = t["notional_usd"] * fee_rate
    ibps = impact_bps(t["notional_usd"], t["adv_usd"], p, mk)
    t["impact_bps"] = ibps
    t["impact_usd"] = t["notional_usd"] * ibps / 1e4
    t["funding_usd"] = 0.0
    t["borrow_usd"] = 0.0

    has_f = "funding_rate" in m.columns
    fund = m.dropna(subset=["funding_rate"]) if has_f else None
    end_ts = pd.Timestamp(p.end_ts) if p.end_ts is not None else max(t["ts"].max(), m["ts"].max())
    for sym, idx in t.groupby("symbol").groups.items():
        g = t.loc[idx]
        ts = g["ts"].to_numpy()
        pos = g["signed_usd"].cumsum().to_numpy()  # position after each trade
        # funding events
        f = fund[fund["symbol"] == sym].sort_values("ts") if has_f else m.iloc[0:0].assign(funding_rate=[])
        for fts, fr in zip(f["ts"].to_numpy(), f["funding_rate"].to_numpy(float)):
            k = np.searchsorted(ts, fts, side="left") - 1  # last trade strictly before
            if k < 0 or abs(pos[k]) < 1e-12:
                continue
            t.loc[g.index[k], "funding_usd"] += pos[k] * fr  # long pays when rate>0
        if not has_f and p.funding_default_rate_8h:
            nxt = np.append(ts[1:], np.datetime64(end_ts))
            n8 = (nxt - ts) / np.timedelta64(8, "h")
            t.loc[g.index, "funding_usd"] += pos * p.funding_default_rate_8h * np.floor(n8)
        # borrow on short notional over holding interval
        nxt = np.append(ts[1:], np.datetime64(end_ts))
        yrs = (nxt - ts) / np.timedelta64(365 * 24, "h")
        short = np.clip(-pos, 0, None)
        t.loc[g.index, "borrow_usd"] += short * p.borrow_rate_annual * np.clip(yrs, 0, None)

    t["total_cost_usd"] = t[["fee_usd", "impact_usd", "funding_usd", "borrow_usd"]].sum(axis=1)
    if "gross_pnl_usd" not in t.columns:
        t["gross_pnl_usd"] = 0.0
    t["gross_pnl_usd"] = t["gross_pnl_usd"].fillna(0.0)
    t["net_pnl_usd"] = t["gross_pnl_usd"] - t["total_cost_usd"]
    t["cost_bps"] = t["total_cost_usd"] / t["notional_usd"] * 1e4
    t.attrs["unfilled"] = unfilled
    return t


def round_trip_cost_bps(notional, adv, params=None, maker_entry=False, maker_exit=False,
                        hold_hours=0.0, funding_rate_8h=None, short=False):
    """Total entry+exit cost in bps of notional (fees + impact + funding + borrow).

    funding_rate_8h: per-8h rate; long pays, short receives (sign flips with `short`).
    """
    p = _params(params)
    fees = (p.maker_fee if maker_entry else p.taker_fee) + (p.maker_fee if maker_exit else p.taker_fee)
    imp = (float(impact_bps(notional, adv, p, maker_entry)) + float(impact_bps(notional, adv, p, maker_exit))) / 1e4
    fr = p.funding_default_rate_8h if funding_rate_8h is None else funding_rate_8h
    fund = fr * (-1 if short else 1) * (hold_hours / 8.0)
    borrow = p.borrow_rate_annual * hold_hours / (365 * 24) if short else 0.0
    return (fees + imp + fund + borrow) * 1e4
