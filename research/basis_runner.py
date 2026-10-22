"""FORM-N delta-neutral basis carry (cash-and-carry): LONG spot / SHORT perp on coins with POSITIVE funding.

Usage: .venv/bin/python research/basis_runner.py [--force]
Output: reports/basis_carry.md, reports/basis_carry.json ; cache research/mech_cache/basis_*.pkl (resumable).

PREREG_CARRY.md: FORM-N is computed ONLY for the best FORM-L config and does NOT multiply n_trials.
FROZEN hyperparameters (= FORM-L `w7d|z|vt|1d`): 7d trailing funding window, z-score magnitude, vol-target
weights, daily rebalance, target_vol 0.20, no-trade band 20%, cap 10%/coin, MIN_ELIG 10. ONE primary config.
Only the CONSTRUCTION changes (sign + hedge). n_trials = 1. No grid.

A-PRIORI CHOICES where spec is silent (fixed before looking at results):
  * Universe = FORM-L PIT top-30 members (identical recipe, via carry_runner.Ctx) AND funded AND has Binance spot
    AND spot close finite at the decision bar AND spot ADV finite. 8 perps with no spot excluded.
  * Selection: raw weight = max(z,0) / sigma_perp where z = cross-sectional z of trailing-7d funding sum, AND the
    coin's own trailing funding must be > 0 (short perp must be paid). sigma = trailing 30d perp vol (as FORM-L).
  * Sleeve vol-target: scale = min(0.20 / vol_of_hedged_book, 1), the hedged-book vol measured on the trailing
    spot-minus-perp return stream (i.e. the real residual risk of the sleeve), never levered above 1.
  * Weights W = $ notional of EACH leg as fraction of book; sum W <= 1; 10% cap per coin (no redistribution).
    Book = one-leg notional. Perp initial margin is NOT charged as extra capital in the headline (diagnostic
    return-on-committed-capital rows are given for margin 20% and 100%). No liquidation/margin-call model.
  * P&L per 8h bar: W_{k-1}*(spotGap - perpGap) + W_k*(spotIntra - perpIntra)  (open-to-open booking, trade at
    OPEN of bar k from decisions at close k-1), + funding RECEIVED on the short perp (rate>0 earns, rate<0 pays),
    event stamped at bar open on W_{k-1}, events inside bar on W_k (identical to carry_runner).
  * Costs: BOTH legs on |dW| at open. Perp taker 4.5 bp (costs.py). Spot taker 10 bp (Binance spot VIP0 default,
    no BNB discount; assumption, stressed). Impact: costs.impact_bps with perp ADV for perp leg, spot ADV for spot leg.
    Spot has no borrow; perp short has no borrow line (funding only).
  * Spot bar holes: spot close ffill (<=6 bars), open filled from previous close; if still missing a held coin's
    spot return is set equal to its perp return (zero basis pnl) and the count is reported.
  * Decision-rule thresholds (not in PREREG): stress-window max DD <= 15%; 'hidden short-vol' if daily skew < -1 or
    excess kurt > 10; |corr to BTC daily| < 0.3 required.
"""
from __future__ import annotations
import sys, json, time, pickle, math, warnings
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import research.carry_runner as CR
from research.carry_runner import Ctx, nw_t, dd_stats, apply_band, pct, log
from research.mech_runner import (N_UNIVERSE, RANK_WIN, HOLDOUT_FRAC, ANN, stats_of, sr_d, to_ns)
from research.execution.costs import CostParams, impact_bps
from research.validation.sharpe import sharpe_lo, probabilistic_sharpe_ratio, deflated_sharpe_ratio
from research.validation.bootstrap import block_bootstrap_ci, stationary_bootstrap_indices

warnings.filterwarnings("ignore")
MECH, CACHE, OUT = CR.MECH, CR.CACHE, CR.OUT
BPY, TARGET_VOL, CAP, MIN_ELIG = CR.BPY, CR.TARGET_VOL, CR.CAP, CR.MIN_ELIG
VOL_WIN, VOL_MIN = CR.VOL_WIN, CR.VOL_MIN
STRESS = CR.STRESS
SPOT_FEE = 0.0010
PERP_FEE = CostParams().taker_fee
CAPITAL = 1e6
IMPACT_KS = [0.125, 0.25, 0.5, 1.0, 2.0]
CAPS_USD = [1e5, 1e6, 5e6, 2e7]
CFG = dict(win=7, sel="z", wt="vt", rb="1d")
NAME = "w7d|z|vt|1d (long spot / short perp)"
VERSION = "v1"


# ---------------------------------------------------------------- context with spot
class SCtx(Ctx):
    def __init__(self, raw, spot1h, spot1d, scale, end=None):
        super().__init__(raw, end)
        s = spot1h[spot1h["symbol"].isin(self.cols) & (spot1h["ts"] < self.end + pd.Timedelta(days=1))].sort_values("ts")
        s = s[s["ts"] >= self.didx[0]].copy()
        s["b"] = s["ts"].dt.floor("8h")
        g = s.groupby(["b", "symbol"])
        SO = g["o"].first().unstack().reindex(index=self.idx, columns=self.cols)
        SC = g["c"].last().unstack().reindex(index=self.idx, columns=self.cols)
        self.SC_raw = SC.copy()
        SC = SC.ffill(limit=6)
        SO = SO.fillna(SC.shift(1))
        self.SO, self.SC = SO, SC
        self.has_spot_cols = [c for c in self.cols if s["symbol"].eq(c).any()]
        self.scale = pd.Series({c: float(scale.get(c, {}).get("scale", 1)) for c in self.cols})
        # basis at bar close (as-of the bar close; perp close / scaled spot close - 1)
        self.basis = self.C / (self.SC * self.scale.values) - 1.0
        # spot ADV (30d trailing quote volume, known before the day)
        q = spot1d[spot1d["symbol"].isin(self.cols) & (spot1d["ts"] <= self.end)]
        QV = q.pivot(index="ts", columns="symbol", values="quote_volume").sort_index()
        QV = QV.reindex(columns=self.cols)
        qv30 = QV.rolling(RANK_WIN, min_periods=RANK_WIN).mean().shift(1)
        self.adv_s = qv30.reindex(self.day).values
        # hedged residual returns (spot minus perp) known through bar k-1, for sleeve vol
        rp = self.C / self.C.shift(1) - 1.0
        rs = self.SC / self.SC.shift(1) - 1.0
        self.rvh = (rs - rp).shift(1).fillna(0.0).values
        # spot-valid at decision (close of bar k-1)
        self.spot_ok = (np.isfinite(self.SC.shift(1).values) & np.isfinite(self.adv_s))


def load_spot():
    s1 = pd.read_parquet(MECH / "spot_klines_1h_binance.parquet", columns=["symbol", "ts", "o", "c"])
    s1["ts"] = to_ns(s1["ts"])
    sd = pd.read_parquet(MECH / "spot_klines_1d_binance.parquet", columns=["symbol", "ts", "quote_volume"])
    sd["ts"] = to_ns(sd["ts"])
    sm = json.loads((MECH / "spot_map.json").read_text())
    return s1, sd, sm


# ---------------------------------------------------------------- weights (FORM-N construction)
def targets(ctx, k):
    N = len(ctx.cols)
    w = CFG["win"]
    e = ctx.memb[k] & ctx.featok[w][k] & ctx.spot_ok[k] & np.isfinite(ctx.sig[k]) & (ctx.sig[k] > 0)
    ids = np.flatnonzero(e)
    n = len(ids)
    out = np.zeros(N)
    if n < MIN_ELIG:
        return out
    fv = ctx.feat[w][k][ids]
    sd = fv.std(ddof=1)
    if not sd > 0:
        return out
    z = (fv - fv.mean()) / sd
    raw = np.where(fv > 0, np.maximum(z, 0.0), 0.0)          # POSITIVE funding only (short perp is paid)
    raw = raw / ctx.sig[k][ids]
    s = raw.sum()
    if not s > 0:
        return out
    wv = raw / s
    H = ctx.rvh[max(0, k - VOL_WIN):k][:, ids]
    if len(H) >= VOL_MIN:
        pv = (H @ wv).std(ddof=1) * math.sqrt(BPY)
        if pv > 0:
            wv = wv * min(TARGET_VOL / pv, 1.0)
    out[ids] = np.minimum(wv, CAP)
    return out


def build_W(ctx):
    T, N = len(ctx.idx), len(ctx.cols)
    W = np.zeros((T, N)); held = np.zeros(N)
    for k in range(1, T):
        if ctx.hour[k] == 0:
            held = apply_band(held, targets(ctx, k))
        W[k] = held
    return pd.DataFrame(W, index=ctx.idx, columns=ctx.cols)


def build_naive(ctx):
    """Diagnostic: every eligible member with trailing funding>0, equal weight, same band/cap (no z-selection/vt)."""
    T, N = len(ctx.idx), len(ctx.cols)
    W = np.zeros((T, N)); held = np.zeros(N)
    for k in range(1, T):
        if ctx.hour[k] == 0:
            e = ctx.memb[k] & ctx.featok[7][k] & ctx.spot_ok[k]
            ids = np.flatnonzero(e)
            tg = np.zeros(N)
            if len(ids) >= MIN_ELIG:
                pos = ids[ctx.feat[7][k][ids] > 0]
                if len(pos):
                    tg[pos] = min(1.0 / len(ids), CAP)
            held = apply_band(held, tg)
        W[k] = held
    return pd.DataFrame(W, index=ctx.idx, columns=ctx.cols)


def cached(tag, name, fn, force):
    f = CACHE / f"basis_{VERSION}_{tag}_{name}.pkl"
    if f.exists() and not force:
        return pickle.load(open(f, "rb"))
    W = fn()
    pickle.dump(W, open(f, "wb"))
    return W


# ---------------------------------------------------------------- accounting
def account(ctx, W, impact_k=0.5, capital=CAPITAL, fee_mult=1.0, detail=False):
    cols = list(W.columns)
    ci = [ctx.cols.index(c) for c in cols]
    O, C = ctx.O[cols], ctx.C[cols]
    SO, SC = ctx.SO[cols], ctx.SC[cols]
    gP = (O / C.shift(1) - 1.0)
    iP = (C / O - 1.0)
    gS = (SO / SC.shift(1) - 1.0)
    iS = (SC / SO - 1.0)
    gS = gS.where(gS.notna(), gP).fillna(0.0); iS = iS.where(iS.notna(), iP).fillna(0.0)
    gP = gP.fillna(0.0); iP = iP.fillna(0.0)
    Wp = W.shift(1).fillna(0.0)
    price_perp = -(Wp * gP + W * iP).sum(axis=1)                      # short perp
    price_spot = (Wp * gS + W * iS).sum(axis=1)                       # long spot
    price = price_perp + price_spot
    dW = (W - Wp).abs()
    cp = CostParams(impact_k=impact_k)
    impP = impact_bps((dW * capital).values, ctx.adv[:, ci], cp)
    impS = impact_bps((dW * capital).values, ctx.adv_s[:, ci], cp)
    fee = (dW * (PERP_FEE + SPOT_FEE) * fee_mult).sum(axis=1)
    impact = (dW * ((impP + impS) / 1e4)).sum(axis=1)
    carry = (Wp * ctx.F0[cols] + W * ctx.F1[cols]).sum(axis=1)       # + = received by short perp
    net = price + carry - fee - impact
    b = pd.DataFrame({"price": price, "price_perp": price_perp, "price_spot": price_spot, "fee": fee, "impact": impact,
                      "carry": carry, "turn": dW.sum(axis=1), "expo": W.abs().sum(axis=1), "net": net})
    g = b.groupby(ctx.day)
    d = g[["price", "price_perp", "price_spot", "fee", "impact", "carry", "turn"]].sum()
    d["net"] = g["net"].apply(lambda x: float(np.prod(1 + x.values) - 1))
    d["expo"] = g["expo"].mean()
    d["gross_nocost"] = d["price"] + d["carry"]
    return d


# ---------------------------------------------------------------- stats helpers
def sig_block(r, label=""):
    r = np.asarray(r, float)
    T = len(r)
    s = stats_of(r)
    sk, ku = float(stats.skew(r)), float(stats.kurtosis(r, fisher=False))
    sr = sr_d(r)
    out = dict(n=T, sharpe=s["sharpe"], cagr=s["cagr"], maxdd=s["maxdd"], mean_bps_yr=float(r.mean() * 365 * 1e4),
               nw_t_mean=nw_t(r), skew=sk, excess_kurt=ku - 3.0)
    try:
        psr = probabilistic_sharpe_ratio(sr, T, sk, ku)
        dsr = deflated_sharpe_ratio(sr, 1, T, sk, ku)            # n_trials = 1 (primary only)
        out.update(psr=psr["psr"], psr_p=psr["p_value"], dsr=dsr["dsr"], dsr_p=dsr["p_value"])
    except Exception as e:
        out.update(psr=float("nan"), dsr=float("nan"), psr_p=float("nan"), dsr_p=float("nan"), err=str(e))
    try:
        lo = sharpe_lo(r, q=365, nw_lag=10)
        out.update(lo_sharpe_annual=float(lo["sharpe_annual"]), lo_eta=float(lo["eta"]), lo_t=float(lo["t_stat"]), lo_p=float(lo["p_value"]))
    except Exception as e:
        out.update(lo_err=str(e))
    ci_m = block_bootstrap_ci(r, np.mean, n_boot=1000, rng=0)
    out["mean_ci_bps_yr"] = [ci_m["ci_low"] * 365e4, ci_m["ci_high"] * 365e4]
    ci_s = block_bootstrap_ci(r, sr_d, n_boot=1000, rng=0)
    out["sharpe_ci"] = [ci_s["ci_low"] * math.sqrt(ANN), ci_s["ci_high"] * math.sqrt(ANN)]
    return out


def bps(x):
    return float(x.mean() * 365 * 1e4)


# ---------------------------------------------------------------- main
def main():
    force = "--force" in sys.argv
    t0 = time.time()
    CACHE.mkdir(exist_ok=True)
    log("loading")
    raw = CR.load_raw()
    s1, sd, sm = load_spot()
    full = SCtx(raw, s1, sd, sm)
    dates = full.didx[(full.didx >= full.start) & (full.didx <= full.end)]
    n = len(dates)
    cut = int(round((1 - HOLDOUT_FRAC) * n))
    is_dates, ho_dates = dates[:cut], dates[cut:]
    is_last = is_dates[-1]
    log(f"eval {dates[0].date()}..{dates[-1].date()} n={n}; IS ..{is_last.date()} ({cut}); HO {ho_dates[0].date()}.. ({len(ho_dates)})")
    isc = SCtx(raw, s1, sd, sm, end=is_last)

    # ---- coverage ----
    memb_spot = full.memb & full.spot_ok & full.featok[7]
    d0 = pd.DataFrame({"members": full.n_mem_d, "funded": full.n_mem_funded_d}).loc[full.start:full.end]
    h0 = np.flatnonzero(full.hour == 0)
    ms = pd.Series(full.memb[h0].sum(axis=1), index=full.day[h0])
    mfs = pd.Series(memb_spot[h0].sum(axis=1), index=full.day[h0])
    d0["funded_and_spot"] = mfs.reindex(d0.index)
    d0["year"] = d0.index.year
    no_spot = sorted(set(full.cand) - set(full.has_spot_cols))
    cover = dict(
        mean_members=float(d0["members"].mean()), mean_funded=float(d0["funded"].mean()),
        mean_funded_and_spot=float(d0["funded_and_spot"].mean()), min_funded_and_spot=int(d0["funded_and_spot"].min()),
        frac_of_members=float(d0["funded_and_spot"].sum() / d0["members"].sum()),
        frac_of_funded=float(d0["funded_and_spot"].sum() / d0["funded"].sum()),
        no_spot_excluded=no_spot, n_candidates_funded=len(full.cand), n_with_spot=len(full.has_spot_cols),
        by_year={int(y): dict(members=float(g["members"].mean()), funded=float(g["funded"].mean()),
                              funded_and_spot=float(g["funded_and_spot"].mean()))
                 for y, g in d0.groupby("year")})
    log("coverage", cover["mean_members"], cover["mean_funded_and_spot"], "no-spot", no_spot)

    # ---- weights ----
    log("weights IS")
    W_is = cached("is", "primary", lambda: build_W(isc), force)
    log("weights full")
    W_f = cached("full", "primary", lambda: build_W(full), force)
    Wn_f = cached("full", "naive", lambda: build_naive(full), force)
    Wn_is = cached("is", "naive", lambda: build_naive(isc), force)
    n_is_bars = len(isc.idx)
    cols_is = [full.cols.index(c) for c in isc.cols]
    sub = W_f.iloc[:n_is_bars].values
    leak = float(np.abs(sub[:, cols_is] - W_is.values).max())
    leak_rest = float(np.abs(np.delete(sub, cols_is, axis=1)).max()) if len(cols_is) < sub.shape[1] else 0.0
    log(f"holdout isolation: max|W_full-W_IS| {leak:.2e}, non-IS symbols {leak_rest:.2e}")

    # ---- primary: full-sample accounting at impact 0.5 / $1M ----
    A = account(full, W_f, 0.5)
    N_ = account(full, Wn_f, 0.5)
    Afull = A.loc[dates]; Nfull = N_.loc[dates]
    a_is, a_ho = A.loc[is_dates], A.loc[ho_dates]
    held_cnt = (W_f.values > 0).sum(axis=1)
    cnt_daily = pd.Series(held_cnt, index=full.idx)[full.hour == 0]
    cnt_daily.index = full.day[full.hour == 0]
    cnt_daily = cnt_daily.loc[dates]

    gross_carry = bps(Afull["carry"]); price_bps = bps(Afull["price"]); cost_bps = bps(Afull["fee"] + Afull["impact"])
    net_bps = bps(Afull["net"])
    expo = float(Afull["expo"].mean())
    P1 = dict(
        gross_carry_bps_yr=gross_carry, price_leg_bps_yr=price_bps, fee_bps_yr=bps(Afull["fee"]), impact_bps_yr=bps(Afull["impact"]),
        total_cost_bps_yr=cost_bps, net_bps_yr=net_bps, gross_before_cost_bps_yr=bps(Afull["gross_nocost"]),
        mean_gross_expo=expo, turnover_per_yr=float(Afull["turn"].mean() * 365),
        carry_pct_of_notional_yr=float(Afull["carry"].sum() / Afull["expo"].sum() * 365 * 100),
        mean_held_coins=float(cnt_daily.mean()),
        price_perp_pct_yr=float(Afull["price_perp"].mean() * 365 * 100), price_spot_pct_yr=float(Afull["price_spot"].mean() * 365 * 100),
        carry_nw_t=nw_t(Afull["carry"].values), price_nw_t=nw_t(Afull["price"].values), cost_to_carry=float(cost_bps / gross_carry) if gross_carry else float("nan"),
        roundtrip_cost_bps_per_notional=float((PERP_FEE + SPOT_FEE) * 2 * 1e4))
    P1["return_on_committed_cap_bps_yr"] = {"margin_20pct": net_bps / 1.2, "margin_100pct": net_bps / 2.0}
    full_stats = sig_block(Afull["net"].values)
    is_stats = sig_block(a_is["net"].values)
    ho_stats = sig_block(a_ho["net"].values)
    nets_naive = sig_block(Nfull["net"].values)
    P_naive = dict(carry_bps_yr=bps(Nfull["carry"]), price_bps_yr=bps(Nfull["price"]), cost_bps_yr=bps(Nfull["fee"] + Nfull["impact"]),
                   net_bps_yr=bps(Nfull["net"]), sharpe=nets_naive["sharpe"], expo=float(Nfull["expo"].mean()),
                   turn_yr=float(Nfull["turn"].mean() * 365))
    holdout = dict(is_=is_stats, ho=ho_stats, carry_bps_yr_ho=bps(a_ho["carry"]), carry_bps_yr_is=bps(a_is["carry"]),
                   price_bps_yr_ho=bps(a_ho["price"]), cost_bps_yr_ho=bps(a_ho["fee"] + a_ho["impact"]),
                   net_bps_yr_ho=bps(a_ho["net"]), same_sign=bool(is_stats["sharpe"] > 0 and ho_stats["sharpe"] > 0),
                   start=str(ho_dates[0].date()), end=str(ho_dates[-1].date()), n=len(ho_dates))
    log(f"net {net_bps:.0f} bps/yr (carry {gross_carry:.0f}, price {price_bps:.0f}, cost {cost_bps:.0f}) SR {full_stats['sharpe']:.2f}")

    # ---- BTC correlation ----
    btcC = full.C["BTCUSDT"]
    btc_d = btcC.groupby(full.day).last().pct_change().reindex(dates)
    r = Afull["net"]
    dfc = pd.DataFrame({"s": r, "b": btc_d}).dropna()
    cor_d = float(dfc.corr().iloc[0, 1])
    wk = (1 + dfc).resample("W").prod() - 1
    cor_w = float(wk.corr().iloc[0, 1])
    beta = float(np.cov(dfc["s"], dfc["b"])[0, 1] / dfc["b"].var())
    down = dfc["b"] < dfc["b"].quantile(0.05)
    up = dfc["b"] > dfc["b"].quantile(0.95)
    corr_yr = {int(y): float(g.corr().iloc[0, 1]) for y, g in dfc.groupby(dfc.index.year) if len(g) > 30}
    corr_stress = {}
    for nm, (a, b) in STRESS.items():
        g = dfc.loc[a:b]
        corr_stress[nm] = float(g.corr().iloc[0, 1]) if len(g) > 4 else float("nan")
    corr_price_leg = float(pd.DataFrame({"s": Afull["price"], "b": btc_d}).dropna().corr().iloc[0, 1])
    btc_corr = dict(daily=cor_d, weekly=cor_w, beta=beta, price_leg_only_daily=corr_price_leg,
                    mean_ret_on_btc_worst5pct_days_bps=float(dfc.loc[down, "s"].mean() * 1e4),
                    mean_ret_on_btc_best5pct_days_bps=float(dfc.loc[up, "s"].mean() * 1e4),
                    mean_ret_all_days_bps=float(dfc["s"].mean() * 1e4), by_year=corr_yr, in_stress=corr_stress,
                    threshold=0.3, pass_=bool(abs(cor_d) < 0.3))

    # ---- stress windows ----
    # per-coin daily basis (last bar close of day)
    bas_d = full.basis.groupby(full.day).last()
    dbas = bas_d.diff()
    Wd = W_f.groupby(full.day).mean()                                   # avg held weight in day
    stress = {}
    for nm, (a, b) in STRESS.items():
        seg = Afull["net"].loc[a:b].values
        price_seg = Afull["price"].loc[a:b]
        held = (Wd.loc[a:b] > 0)
        db = dbas.loc[a:b].where(held)
        stack = db.abs().stack()
        top = stack.sort_values(ascending=False).head(3)
        allmem = dbas.loc[a:b].abs().stack().sort_values(ascending=False).head(3)
        stress[nm] = dict(maxdd=dd_stats(seg), cum_ret=float(np.prod(1 + seg) - 1), worst_day_net=float(seg.min()),
                          worst_day_price_leg=float(price_seg.min()), cum_price_leg=float(price_seg.sum()),
                          cum_carry=float(Afull["carry"].loc[a:b].sum()),
                          mean_expo=float(Afull["expo"].loc[a:b].mean()), mean_held=float(cnt_daily.loc[a:b].mean()),
                          worst_held_coin_basis_move_day=[(str(i[0].date()), i[1], float(v)) for i, v in top.items()],
                          worst_any_member_basis_move_day=[(str(i[0].date()), i[1], float(v)) for i, v in allmem.items()])
    # sleeve-level worst days overall
    pr = Afull["price"]
    worst_price_days = [(str(i.date()), float(v)) for i, v in pr.nsmallest(5).items()]
    worst_net_days = [(str(i.date()), float(v)) for i, v in Afull["net"].nsmallest(5).items()]
    rb_ = Afull["net"].values
    sd_ = rb_.std(ddof=1)
    q01 = float(np.percentile(rb_, 1)); es = float(rb_[rb_ <= q01].mean())
    idxb = stationary_bootstrap_indices(len(rb_), 20, 1000, rng=1)
    bdd = np.array([dd_stats(rb_[idxb[i][:365]]) for i in range(len(idxb))])
    # price-leg moments: is the hedge book short-vol? price-leg skew, and corr of price leg with |BTC| moves
    pl = Afull["price"].values
    absb = dfc["b"].abs().reindex(Afull.index)
    sv = pd.DataFrame({"p": Afull["price"], "a": absb}).dropna()
    price_vs_absbtc = float(sv.corr().iloc[0, 1])
    # 1d basis dislocation = sleeve-weighted daily basis change; tail ratio
    tail = dict(
        stress=stress, skew=float(stats.skew(rb_)), excess_kurt=float(stats.kurtosis(rb_, fisher=True)),
        price_leg_skew=float(stats.skew(pl)), price_leg_excess_kurt=float(stats.kurtosis(pl, fisher=True)),
        price_leg_worst_day=float(pl.min()), price_leg_worst_day_sigmas=float(pl.min() / pl.std(ddof=1)),
        price_leg_daily_std_bps=float(pl.std(ddof=1) * 1e4), worst_net_day=float(rb_.min()), worst_net_day_sigmas=float(rb_.min() / sd_),
        es1=es, boot_1y_maxdd_p5=float(np.percentile(bdd, 5)), boot_1y_maxdd_median=float(np.median(bdd)),
        full_maxdd=full_stats["maxdd"], worst_price_days=worst_price_days, worst_net_days=worst_net_days,
        corr_price_leg_vs_abs_btc=price_vs_absbtc, carry_share_of_net=float(Afull["carry"].sum() / max(Afull["net"].sum(), 1e-12)))
    tail["hidden_shortvol_flag"] = bool(tail["skew"] < -1 or tail["excess_kurt"] > 10)
    tail["price_leg_shortvol_flag"] = bool(tail["price_leg_skew"] < -1 or tail["price_leg_excess_kurt"] > 10)
    tail["stress_pass"] = bool(all(stress[k]["maxdd"] >= -0.15 for k in stress))

    # ---- capacity (IS-window convention of carry_runner? use full sample, same book) ----
    cap_rows = {}
    for cp_ in CAPS_USD:
        a = account(full, W_f, 0.5, cp_).loc[dates]
        s = sig_block(a["net"].values)
        cap_rows[str(int(cp_))] = dict(sharpe=s["sharpe"], net_bps_yr=s["mean_bps_yr"], nw_t=s["nw_t_mean"],
                                       cost_bps_yr=bps(a["fee"] + a["impact"]), cagr=s["cagr"], psr=s["psr"])
    # ---- cost / fee stress ----
    stress_tab = {}
    for fm in (1.0, 2.0):
        for ik in IMPACT_KS:
            a = account(full, W_f, ik, CAPITAL, fee_mult=fm).loc[dates]
            s = stats_of(a["net"].values)
            stress_tab[f"fee{fm:g}x|k{ik:g}"] = dict(net_bps_yr=bps(a["net"]), sharpe=s["sharpe"], cost_bps_yr=bps(a["fee"] + a["impact"]),
                                                   nw_t=nw_t(a["net"].values), sign_pos=bool(a["net"].mean() > 0 and s["sharpe"] > 0))
    # DIAGNOSTIC ONLY (not the primary/verdict): spread-floor-only costs (impact_k=0) and breakeven impact_k
    diag_k0 = {}
    for fm in (1.0, 2.0):
        a = account(full, W_f, 0.0, CAPITAL, fee_mult=fm).loc[dates]
        sb = sig_block(a["net"].values)
        diag_k0[f"fee{fm:g}x|k0"] = dict(net_bps_yr=sb["mean_bps_yr"], sharpe=sb["sharpe"], nw_t=sb["nw_t_mean"], psr_p=sb["psr_p"],
                                        lo_p=sb.get("lo_p"), ci=sb["mean_ci_bps_yr"], cost_bps_yr=bps(a["fee"] + a["impact"]), maxdd=sb["maxdd"])
    lo_, hi_ = 0.0, 0.125
    if bps(account(full, W_f, hi_).loc[dates]["net"]) < 0 < bps(account(full, W_f, lo_).loc[dates]["net"]):
        for _ in range(12):
            mid = (lo_ + hi_) / 2
            if bps(account(full, W_f, mid).loc[dates]["net"]) > 0: lo_ = mid
            else: hi_ = mid
        be_k = (lo_ + hi_) / 2
    else:
        be_k = float("nan")
    # breakeven fee multiple (linear in fee at k=0.5)
    base = account(full, W_f, 0.0).loc[dates]   # breakeven fee multiple measured at impact_k=0 (spread floor only)
    fee_b = bps(base["fee"]); rest = bps(base["net"]) + fee_b
    breakeven_fee_mult = float(rest / fee_b) if fee_b > 0 else float("nan")
    # cheaper-fee scenario (BNB spot 7.5bp, VIP perp maker-ish not assumed): spot fee 0.075% -> informational
    # ---- year table ----
    yrs = {}
    for y in sorted(set(dates.year)):
        m = dates.year == y
        r_ = Afull["net"].values[m]
        yrs[int(y)] = dict(days=int(m.sum()), net_ret=float(np.prod(1 + r_) - 1), sharpe=sr_d(r_) * math.sqrt(ANN) if len(r_) > 5 else float("nan"),
                           carry_bps_yr=bps(Afull["carry"][m]), price_bps_yr=bps(Afull["price"][m]), cost_bps_yr=bps(Afull["fee"][m] + Afull["impact"][m]),
                           expo=float(Afull["expo"][m].mean()), held=float(cnt_daily[m].mean()))
    # spot-hole diagnostic on held coin-bars
    sc_nan = ~np.isfinite(full.SC_raw.values)
    held_mask = W_f.values > 0
    hole_frac = float((sc_nan & held_mask).sum() / max(held_mask.sum(), 1))

    verdict = {}
    verdict["1_net_carry_pos_sig"] = (bool(net_bps > 0 and full_stats["mean_ci_bps_yr"][0] > 0 and full_stats["nw_t_mean"] > 2),
                                       f"gross carry {gross_carry:.0f}, price {price_bps:.0f}, costs {cost_bps:.0f} -> net {net_bps:.0f} bps/yr; NW t {full_stats['nw_t_mean']:.2f}; CI {full_stats['mean_ci_bps_yr'][0]:.0f}..{full_stats['mean_ci_bps_yr'][1]:.0f}")
    verdict["2_sharpe_sig"] = (bool(full_stats["sharpe"] > 0 and full_stats["psr_p"] < 0.05 and full_stats.get("lo_p", 1) < 0.05),
                                f"SR {full_stats['sharpe']:.2f}, PSR p {full_stats['psr_p']:.3f}, DSR(n=1) p {full_stats['dsr_p']:.3f}, Lo SR {full_stats.get('lo_sharpe_annual', float('nan')):.2f} p {full_stats.get('lo_p', float('nan')):.3f}")
    verdict["3_btc_corr"] = (btc_corr["pass_"], f"daily corr {cor_d:.3f}, weekly {cor_w:.3f}, beta {beta:.3f}")
    verdict["4_tail"] = (bool(tail["stress_pass"] and not tail["hidden_shortvol_flag"] and not tail["price_leg_shortvol_flag"]),
                         f"LUNA DD {pct(stress['LUNA']['maxdd'])}, FTX DD {pct(stress['FTX']['maxdd'])}, skew {tail['skew']:.2f}, exkurt {tail['excess_kurt']:.1f}, price-leg skew {tail['price_leg_skew']:.2f}/exkurt {tail['price_leg_excess_kurt']:.1f}")
    cap_ok = all(v["net_bps_yr"] > 0 for k, v in cap_rows.items() if k in ("100000", "1000000", "5000000", "20000000"))
    verdict["5_capacity"] = (cap_ok, "net bps/yr by book: " + ", ".join(f"${int(float(k)/1e6*10)/10}M {v['net_bps_yr']:.0f}" for k, v in cap_rows.items()))
    allpos = all(v["sign_pos"] for v in stress_tab.values())
    verdict["6_cost_robust"] = (allpos, f"{sum(v['sign_pos'] for v in stress_tab.values())}/{len(stress_tab)} cost scenarios positive; breakeven impact_k {be_k:.3f}; breakeven fee mult at k=0 {breakeven_fee_mult:.2f}x")
    verdict["7_holdout"] = (bool(holdout["same_sign"] and ho_stats["mean_bps_yr"] > 0), f"HO SR {ho_stats['sharpe']:.2f}, net {ho_stats['mean_bps_yr']:.0f} bps/yr (IS SR {is_stats['sharpe']:.2f}); Bybit/forward pending")
    testable = [v[0] for k, v in verdict.items()]
    overall = "CONFIRMED (supporting points 7-Bybit/forward-paper pending)" if all(testable) else "NOT CONFIRMED"

    out = dict(generated=time.strftime("%Y-%m-%d %H:%M:%S"), config=NAME, n_trials=1,
               window=dict(start=str(dates[0].date()), end=str(dates[-1].date()), n_days=n, is_end=str(is_last.date()), ho_start=str(ho_dates[0].date())),
               coverage=cover, carry_cost_decomp=P1, full=full_stats, is_=is_stats, naive_positive_funding_diag=P_naive,
               btc=btc_corr, tail=tail, capacity=cap_rows, cost_stress=stress_tab, diag_k0=diag_k0, breakeven_impact_k=be_k, breakeven_fee_mult=breakeven_fee_mult,
               holdout=holdout, by_year=yrs, spot_hole_frac_on_held=hole_frac,
               verdicts={k: dict(status="PASS" if v[0] else "FAIL", number=v[1]) for k, v in verdict.items()}, overall=overall,
               audit=dict(holdout_leak_max_abs_dW=leak, holdout_leak_nonIS_symbols=leak_rest),
               assumptions=dict(perp_fee=PERP_FEE, spot_fee=SPOT_FEE, target_vol=TARGET_VOL, cap=CAP, band=CR.BAND, impact_k=0.5,
                                capital=CAPITAL, min_elig=MIN_ELIG))
    OUT.mkdir(exist_ok=True)
    (OUT / "basis_carry.json").write_text(json.dumps(out, indent=1, default=str))
    write_md(out)
    log(f"done {time.time()-t0:.0f}s overall: {overall}")


def write_md(o):
    L = []; A = L.append
    f2 = lambda x: f"{x:.2f}"
    P, F = o["carry_cost_decomp"], o["full"]
    A("# FORM-N delta-neutral basis carry (long spot / short perp) - PREREG_CARRY.md FORM-N\n")
    A(f"Generated {o['generated']}. ONE primary config `{o['config']}` (hyperparameters fixed = best FORM-L; n_trials=1, no grid). "
      f"Window {o['window']['start']}..{o['window']['end']} ({o['window']['n_days']} d); IS ..{o['window']['is_end']}; holdout from {o['window']['ho_start']} (last 20%).\n")
    A(f"## OVERALL: **{o['overall']}**\n")
    A("| # | Point | Status | Number |\n|---|---|---|---|")
    for k, v in o["verdicts"].items():
        A(f"| {k.split('_')[0]} | {k.split('_', 1)[1]} | **{v['status']}** | {v['number']} |")
    c = o["coverage"]
    A("\n## Coverage\n")
    A(f"PIT top-{N_UNIVERSE} members/day {c['mean_members']:.1f}; with funding {c['mean_funded']:.1f}; with funding AND Binance spot AND trailing funding feature {c['mean_funded_and_spot']:.1f} "
      f"(min {c['min_funded_and_spot']}; {pct(c['frac_of_members'])} of member-days, {pct(c['frac_of_funded'])} of funded member-days). "
      f"{c['n_with_spot']} of {c['n_candidates_funded']} funded perps have spot. Excluded (no Binance spot): {', '.join(c['no_spot_excluded'])}.\n")
    A("| year | members | funded | funded+spot | mean coins held |\n|---|---|---|---|---|")
    for y, v in c["by_year"].items():
        A(f"| {y} | {v['members']:.1f} | {v['funded']:.1f} | {v['funded_and_spot']:.1f} | {o['by_year'].get(str(y), o['by_year'].get(y, {})).get('held', float('nan')):.1f} |")
    A("\n## 1. Gross basis-carry vs net after two-leg costs (full sample, impact_k 0.5, $1M, bps of book per year)\n")
    A("Book = one-leg notional (sum of weights <= 1). Perp margin NOT counted as extra capital in headline.\n")
    A("| component | bps/yr |\n|---|---|")
    A(f"| funding received (gross carry) | {P['gross_carry_bps_yr']:.0f} |")
    A(f"| hedged price leg (spot - perp, i.e. -basis change) | {P['price_leg_bps_yr']:.0f} |")
    A(f"| gross before costs | {P['gross_before_cost_bps_yr']:.0f} |")
    A(f"| fees (perp 4.5bp + spot 10bp per unit traded) | -{P['fee_bps_yr']:.0f} |")
    A(f"| impact (both legs) | -{P['impact_bps_yr']:.0f} |")
    A(f"| **NET** | **{P['net_bps_yr']:.0f}** |")
    A(f"\nMean gross exposure {P['mean_gross_expo']:.2f}, mean coins held {P['mean_held_coins']:.1f}, turnover {P['turnover_per_yr']:.1f}x book/yr, funding per unit notional {P['carry_pct_of_notional_yr']:.2f}%/yr. "
      f"Carry NW t {P['carry_nw_t']:.2f}; price-leg NW t {P['price_nw_t']:.2f}. Cost/carry = {P['cost_to_carry']:.2f}. Return on committed capital if perp margin 20%: {P['return_on_committed_cap_bps_yr']['margin_20pct']:.0f} bps/yr, if 100%: {P['return_on_committed_cap_bps_yr']['margin_100pct']:.0f}. "
      f"Round-trip fee per unit notional {P['roundtrip_cost_bps_per_notional']:.1f} bp (both legs in and out). Diagnostic naive (all positive-funding members equal weight): carry {o['naive_positive_funding_diag']['carry_bps_yr']:.0f}, price {o['naive_positive_funding_diag']['price_bps_yr']:.0f}, cost -{o['naive_positive_funding_diag']['cost_bps_yr']:.0f}, net {o['naive_positive_funding_diag']['net_bps_yr']:.0f} bps/yr, SR {o['naive_positive_funding_diag']['sharpe']:.2f}.\n")
    A("## 2. Net Sharpe and significance\n")
    A(f"Net SR {F['sharpe']:.2f} (full), CI95 [{F['sharpe_ci'][0]:.2f}, {F['sharpe_ci'][1]:.2f}]; CAGR {pct(F['cagr'])}; maxDD {pct(F['maxdd'])}; mean {F['mean_bps_yr']:.0f} bps/yr, NW t {F['nw_t_mean']:.2f}, bootstrap CI [{F['mean_ci_bps_yr'][0]:.0f},{F['mean_ci_bps_yr'][1]:.0f}]. "
      f"PSR p={F['psr_p']:.3f}; DSR (n_trials=1) p={F['dsr_p']:.3f}; Lo-adjusted SR {F.get('lo_sharpe_annual', float('nan')):.2f} (eta {F.get('lo_eta', float('nan')):.2f}), HAC t {F.get('lo_t', float('nan')):.2f}, p={F.get('lo_p', float('nan')):.3f}. Skew {F['skew']:.2f}, excess kurt {F['excess_kurt']:.1f}.\n")
    b = o["btc"]
    A("## 3. Correlation to BTC\n")
    A(f"Daily corr(sleeve, BTC) = **{b['daily']:.3f}**, weekly {b['weekly']:.3f}, beta {b['beta']:.3f}, price-leg-only daily corr {b['price_leg_only_daily']:.3f}. "
      f"Mean sleeve daily return on BTC worst-5% days {b['mean_ret_on_btc_worst5pct_days_bps']:.1f} bp, best-5% days {b['mean_ret_on_btc_best5pct_days_bps']:.1f} bp, all days {b['mean_ret_all_days_bps']:.1f} bp. By year: {b['by_year']}. In stress windows: {b['in_stress']}. Threshold |corr|<0.3 -> {'PASS' if b['pass_'] else 'FAIL'}.\n")
    t = o["tail"]
    A("## 4. Tail: LUNA / FTX / basis blow-up\n")
    A("| window | maxDD | cum net | worst day net | worst day price-leg | cum price leg | cum carry | expo | coins | worst held-coin 1d basis move | worst any-member 1d basis move |\n|---|---|---|---|---|---|---|---|---|---|---|")
    for k, v in t["stress"].items():
        A(f"| {k} | {pct(v['maxdd'])} | {pct(v['cum_ret'])} | {pct(v['worst_day_net'])} | {pct(v['worst_day_price_leg'])} | {pct(v['cum_price_leg'])} | {pct(v['cum_carry'])} | {v['mean_expo']:.2f} | {v['mean_held']:.1f} | {v['worst_held_coin_basis_move_day'][:1]} | {v['worst_any_member_basis_move_day'][:1]} |")
    A(f"\nFull-sample maxDD {pct(t['full_maxdd'])}; bootstrap 1y maxDD median {pct(t['boot_1y_maxdd_median'])}, p5 {pct(t['boot_1y_maxdd_p5'])}. Net daily skew {t['skew']:.2f}, excess kurt {t['excess_kurt']:.1f}; "
      f"price-leg (basis) daily std {t['price_leg_daily_std_bps']:.1f} bp, skew {t['price_leg_skew']:.2f}, excess kurt {t['price_leg_excess_kurt']:.1f}, worst day {pct(t['price_leg_worst_day'])} ({t['price_leg_worst_day_sigmas']:.1f} sigma); corr(price leg, |BTC ret|) {t['corr_price_leg_vs_abs_btc']:.3f}. "
      f"Worst price-leg days: {t['worst_price_days']}. Worst net days: {t['worst_net_days']}. Flags: net short-vol {t['hidden_shortvol_flag']}, price-leg short-vol {t['price_leg_shortvol_flag']}. Exchange/counterparty risk (FTX-style) is NOT modeled: both legs sit on Binance in this data.\n")
    A("## 5. Capacity (net through impact, both legs)\n")
    A("| book | net SR | net bps/yr | NW t | costs bps/yr | CAGR |\n|---|---|---|---|---|---|")
    for k, v in o["capacity"].items():
        A(f"| ${float(k)/1e6:g}M | {f2(v['sharpe'])} | {v['net_bps_yr']:.0f} | {f2(v['nw_t'])} | {v['cost_bps_yr']:.0f} | {pct(v['cagr'])} |")
    A("\n## 6. Cost / fee stress (full sample, $1M)\n")
    A("| scenario | net bps/yr | net SR | NW t | costs bps/yr | positive? |\n|---|---|---|---|---|---|")
    for k, v in o["cost_stress"].items():
        A(f"| {k} | {v['net_bps_yr']:.0f} | {f2(v['sharpe'])} | {f2(v['nw_t'])} | {v['cost_bps_yr']:.0f} | {'yes' if v['sign_pos'] else 'NO'} |")
    A("\nDIAGNOSTIC (not the primary verdict; the impact model k is an uncalibrated placeholder): spread-floor-only costs (impact_k=0, only the 0.5bp/leg half-spread floor + fees):\n")
    A("| scenario | net bps/yr | net SR | NW t | PSR p | Lo p | CI95 mean bps/yr | maxDD |\n|---|---|---|---|---|---|---|---|")
    for k, v in o["diag_k0"].items():
        A(f"| {k} | {v['net_bps_yr']:.0f} | {f2(v['sharpe'])} | {f2(v['nw_t'])} | {v['psr_p']:.3f} | {v['lo_p']:.3f} | [{v['ci'][0]:.0f},{v['ci'][1]:.0f}] | {pct(v['maxdd'])} |")
    A(f"\nBreakeven impact_k (fee 1x) = {o['breakeven_impact_k']:.4f} (primary k=0.5; grid spans 0.125..2).")
    A(f"\nBreakeven fee multiple (impact_k 0, fees only): {o['breakeven_fee_mult']:.2f}x of assumed fees.\n")
    h = o["holdout"]
    A("## 7. Holdout (supporting; last 20%) and by-year\n")
    A(f"HO {h['start']}..{h['end']} ({h['n']} d): SR {h['ho']['sharpe']:.2f}, net {h['ho']['mean_bps_yr']:.0f} bps/yr (carry {h['carry_bps_yr_ho']:.0f}, price {h['price_bps_yr_ho']:.0f}, cost -{h['cost_bps_yr_ho']:.0f}), NW t {h['ho']['nw_t_mean']:.2f}, maxDD {pct(h['ho']['maxdd'])}. IS SR {h['is_']['sharpe']:.2f}, net {h['is_']['mean_bps_yr']:.0f} bps/yr, carry {h['carry_bps_yr_is']:.0f}. Bybit replication and forward paper: pending.\n")
    A("| year | days | net ret | SR | carry bps | price bps | cost bps | expo | coins |\n|---|---|---|---|---|---|---|---|---|")
    for y, v in o["by_year"].items():
        A(f"| {y} | {v['days']} | {pct(v['net_ret'])} | {f2(v['sharpe'])} | {v['carry_bps_yr']:.0f} | {v['price_bps_yr']:.0f} | {v['cost_bps_yr']:.0f} | {v['expo']:.2f} | {v['held']:.1f} |")
    A("\n## Lookahead self-audit\n")
    A(f"* Funding as-of: trailing-7d funding sum uses only events with ts strictly before the decision (bar-open) instant (carry_runner `.shift(1)` on 8h bins, >=80% event count required); the event stamped exactly at close is excluded.\n"
      f"* Funding booked at true settlement events: event stamped at bar open on pre-trade W_(k-1), events inside the bar on W_k.\n"
      f"* Basis as-of: basis = perp close/(spot close*scale)-1 at bar close; used only for reporting/stress, NOT in selection. Spot validity and spot ADV gates use close of bar k-1 and ADV shift(1) of daily spot volume.\n"
      f"* Next-open booking: decisions at close k-1, trade at OPEN of bar k for BOTH legs; price P&L = W_(k-1)*gap + W_k*intra for each leg.\n"
      f"* Selection/vol shift: sigma and hedged-book vol use returns through bar k-1 only (`shift(1)`); z-score is cross-sectional on same-instant info.\n"
      f"* PIT universe: same top-30 trailing-30d-volume recipe as FORM-L (membership at day D-1 close), intersected with funded & spot (spot listing date implicit via finite spot close/ADV).\n"
      f"* Holdout isolation: weights rebuilt on a context truncated at the last IS day; max|W_full - W_IS| over IS rows = {o['audit']['holdout_leak_max_abs_dW']:.2e}, weight on non-IS symbols in IS rows = {o['audit']['holdout_leak_nonIS_symbols']:.2e}. Hyperparameters fixed a priori from FORM-L (no tuning on holdout; none tuned at all here). Caveat: FORM-L best config was itself selected on the IS window of FORM-L.\n"
      f"* Spot ffill uses only past bars (limit 6); fraction of held coin-bars with raw spot hole {o['spot_hole_frac_on_held']:.4f}.\n"
      f"* Caveats not lookahead: spot fee 10 bp is an assumption (no BNB/VIP); no margin/liquidation model; constant-notional funding approximation; both legs same exchange (counterparty risk unmodeled).\n")
    (OUT / "basis_carry.md").write_text("\n".join(L))


if __name__ == "__main__":
    main()
