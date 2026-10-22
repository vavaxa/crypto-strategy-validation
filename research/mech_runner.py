"""Backtest + validation runner for the frozen trend/breakout pre-registration (research only).

Usage:  .venv/bin/python research/mech_runner.py [--force]
Output: reports/mech_trend.md, reports/mech_trend.json ; cache in research/mech_cache/ (resumable).
Grid, sizing, risk, decision rule are FROZEN (PREREGISTRATION.md); nothing here tunes them.
Everything is wired from existing modules: strategy/trend.py, execution/costs.py, validation/*.
"""
from __future__ import annotations
import sys, os, json, time, pickle, warnings, itertools, math
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from research.strategy.trend import generate_positions
from research.execution.costs import CostParams, impact_bps, apply_costs
from research.validation.sharpe import deflated_sharpe_ratio, probabilistic_sharpe_ratio, sharpe_lo
from research.validation.overfitting import pbo_cscv
from research.validation.data_snooping import whites_reality_check, hansen_spa
from research.validation.bootstrap import block_bootstrap_ci
from research.validation.cross_validation import purged_kfold

warnings.filterwarnings("ignore")
MECH = ROOT / "data" / "mech"
CACHE = ROOT / "research" / "mech_cache"
REPORT = ROOT / "reports" / "mech_trend.md"
CACHE.mkdir(exist_ok=True)
REPORT.parent.mkdir(exist_ok=True)

# ---------------- fixed choices (a priori, not tuned) ----------------
N_UNIVERSE = 30            # top-N by trailing quote volume, fixed for every config
RANK_WIN = 30              # trailing days for liquidity ranking / ADV
MIN_MEMBERS_START = 10     # evaluation starts when >=10 PIT members exist (data fact, not performance)
CAPITAL = 1_000_000.0      # notional used for the impact term
HOLDOUT_FRAC = 0.20
FWD_H = 10                 # forward horizon (days) for event studies
STABLE_BASES = {"USDC", "BUSD", "TUSD", "FDUSD", "USDP", "DAI", "USDE", "EUR", "AEUR", "PAXG", "XAUT"}
FIXED = dict(vol_targeting=True, target_vol=0.20, kelly_f=0.25, atr_stop_k=3.0, max_drawdown=0.25,
             allow_short=False, bars_per_year=365.0)
SIGNALS = [("brk20/10", dict(style="breakout", donchian_n=20, exit_n=10)),
           ("brk20/20", dict(style="breakout", donchian_n=20, exit_n=20)),
           ("brk55/10", dict(style="breakout", donchian_n=55, exit_n=10)),
           ("brk55/20", dict(style="breakout", donchian_n=55, exit_n=20)),
           ("tsmom30", dict(style="tsmom", mom_lookback=30)),
           ("tsmom90", dict(style="tsmom", mom_lookback=90))]
VARIANTS = [("bare", {}), ("+vol", dict(confirm_volume=True)), ("+oi", dict(confirm_oi=True)),
            ("+reg", dict(regime_filter=True))]
GRID = {f"{s}|{v}": {**sp, **vp, **FIXED} for s, sp in SIGNALS for v, vp in VARIANTS}
assert len(GRID) == 24
N_TRIALS = 24
ANN = 365.0


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def to_ns(s):
    return pd.to_datetime(s, utc=True).astype("datetime64[ns, UTC]")


# ---------------- data ----------------
def load_raw():
    d1 = pd.read_parquet(MECH / "klines_1d_binance.parquet")
    d1["ts"] = to_ns(d1["ts"])
    uni = pd.read_parquet(MECH / "universe_binance.parquet")
    for c in ("onboard_ts", "delivery_ts"):
        uni[c] = to_ns(uni[c])
    fu = pd.read_parquet(MECH / "funding_binance.parquet")
    fu["ts"] = to_ns(fu["ts"]).dt.round("min")
    oi = pd.read_parquet(MECH / "oi_1h_binance.parquet", columns=["symbol", "ts", "sum_open_interest_value"])
    oi["ts"] = to_ns(oi["ts"])
    oi = oi[oi["ts"].dt.hour == 0].rename(columns={"sum_open_interest_value": "oi"})  # 00:00 UTC snapshot (state at prior close)
    return d1, uni, fu, oi


class Panel:
    """Wide daily panel truncated at `end` (inclusive). Nothing after `end` is visible."""

    def __init__(self, raw, end=None):
        d1, uni, fu, oi = raw
        last_complete = pd.Timestamp.now(tz="UTC").normalize() - pd.Timedelta(days=1)  # drop today's partial bar
        end = last_complete if end is None else min(pd.Timestamp(end), last_complete)
        self.end = end
        perp = set(uni.loc[uni["is_usdt_perp"], "symbol"])
        base = uni.set_index("symbol")["base"].to_dict()
        deliv = uni.set_index("symbol")["delivery_ts"].to_dict()
        d = d1[(d1["ts"] <= end) & d1["symbol"].isin(perp)]
        d = d[~d["symbol"].map(base).isin(STABLE_BASES)]
        d = d[(d["quote_volume"] > 0) & (d["c"] > 0)]
        d = d[d["ts"] < d["symbol"].map(deliv).fillna(pd.Timestamp("2100-01-01", tz="UTC")).astype("datetime64[ns, UTC]")]
        w = lambda col: d.pivot(index="ts", columns="symbol", values=col).sort_index()
        self.C, self.O, self.H, self.L = w("c"), w("o"), w("h"), w("l")
        self.V, self.QV, self.TBQ = w("volume"), w("quote_volume"), w("taker_buy_quote_volume")
        self.idx, self.cols = self.C.index, self.C.columns
        # PIT liquidity: value at i uses days <= i (known at close i)
        self.qv30 = self.QV.rolling(RANK_WIN, min_periods=RANK_WIN).mean()
        elig = self.qv30.notna() & self.C.notna()
        rk = self.qv30.where(elig).rank(axis=1, ascending=False, method="first")
        self.rank = rk
        self.member = (rk <= N_UNIVERSE) & elig
        self.adv = self.qv30.shift(1)      # ADV known before the trade at open i
        self.base = base
        # OI daily (00:00 snapshot at day t = state at close t-1), as-of aligned
        o = oi[oi["ts"] <= end + pd.Timedelta(days=1)].pivot(index="ts", columns="symbol", values="oi").sort_index()
        self.oi = o.reindex(o.index.union(self.idx)).ffill().reindex(self.idx).reindex(columns=self.cols)
        self.oi_avail = self.oi.notna() & (self.oi.notna().rolling(6).sum() == 6)
        # funding: sum of events inside each daily bar [t, t+1d)
        f = fu[fu["ts"] < end + pd.Timedelta(days=1)].copy()
        f["day"] = f["ts"].dt.floor("D")
        self.fsum = f.groupby(["day", "symbol"])["funding_rate"].sum().unstack().reindex(self.idx).reindex(columns=self.cols)
        first = f.groupby("symbol")["day"].min(); last = f.groupby("symbol")["day"].max()
        fa = pd.DataFrame(False, index=self.idx, columns=self.cols)
        for s in first.index:
            if s in fa.columns:
                fa.loc[(fa.index >= first[s]) & (fa.index <= last[s]), s] = True
        self.fund_avail = fa
        self.fsum = self.fsum.where(fa).fillna(0.0)
        # start of evaluation
        cnt = self.member.sum(axis=1)
        self.start = cnt.index[cnt >= MIN_MEMBERS_START][0]
        self.cand = [c for c in self.cols if self.member[c].any()]

    def price_df(self, cols):
        parts = []
        for nm, df in (("close", self.C), ("high", self.H), ("low", self.L), ("volume", self.V)):
            parts.append(df[cols].stack(future_stack=True).rename(nm) if False else df[cols].stack().rename(nm))
        p = pd.concat(parts, axis=1).reset_index()
        p.columns = ["ts_utc", "symbol", "close", "high", "low", "volume"]
        return p

    def oi_df(self, cols):
        o = self.oi[cols].stack().rename("oi").reset_index()
        o.columns = ["ts_utc", "symbol", "oi"]
        return o


def positions(panel, name, params, tag, mask=None, force=False):
    f = CACHE / f"W_{tag}_{name.replace('/', '-').replace('|', '_').replace('+', 'p')}.pkl"
    if f.exists() and not force:
        return pickle.load(open(f, "rb"))
    cols = panel.cand
    M = panel.member[cols] if mask is None else mask[cols]
    pos = generate_positions(panel.price_df(cols), panel.oi_df(cols) if params.get("confirm_oi") else None,
                             None, params, member_mask=M)
    W = pos.pivot(index="ts_utc", columns="symbol", values="target_weight")
    W.index = pd.DatetimeIndex(W.index).tz_localize("UTC").astype("datetime64[ns, UTC]")  # trend.py emits naive-UTC ts (idx.values)
    W = W.reindex(index=panel.idx, columns=cols).fillna(0.0)
    assert (W.abs().values > 0).any(), "all-zero weights: index mismatch?"
    pickle.dump(W, open(f, "wb"))
    return W


# ---------------- accounting ----------------
def account(panel, W, impact_mult=1.0, funding_mode="drag", drag=0.0):
    """Daily net return series. Weight row T is decided at close T-1 and traded at OPEN T:
    pnl_T = W_{T-1} * (O_T/C_{T-1}-1) + W_T * (C_T/O_T-1).  Costs on |W_T - W_{T-1}| at open T."""
    cols = list(W.columns)
    O, C = panel.O[cols], panel.C[cols]
    gap = (O / C.shift(1) - 1.0).fillna(0.0)
    intra = (C / O - 1.0).fillna(0.0)
    Wp = W.shift(1).fillna(0.0)
    gross = (Wp * gap + W * intra).sum(axis=1)
    dW = (W - Wp).abs()
    cp = CostParams(impact_k=0.5 * impact_mult)
    imp = impact_bps((dW * CAPITAL).values, panel.adv[cols].values, cp)   # costs.py, bps
    fee = (dW * cp.taker_fee).sum(axis=1)
    impact = (dW * (imp / 1e4)).sum(axis=1)
    fav = panel.fund_avail[cols]
    if funding_mode == "drag":
        fr = panel.fsum[cols].where(fav, drag)
    else:
        fr = panel.fsum[cols]
    funding = (W * fr).sum(axis=1)
    net = gross - fee - impact - funding
    return pd.DataFrame({"gross": gross, "fee": fee, "impact": impact, "funding": funding, "net": net,
                         "turnover": dW.sum(axis=1), "exposure": W.abs().sum(axis=1)})


def stats_of(r):
    r = np.asarray(r, float)
    if len(r) < 3 or r.std(ddof=1) == 0:
        return dict(sharpe=0.0, cagr=0.0, maxdd=0.0, ret=0.0)
    eq = np.cumprod(1 + r)
    peak = np.maximum.accumulate(eq)
    yrs = len(r) / ANN
    return dict(sharpe=float(r.mean() / r.std(ddof=1) * math.sqrt(ANN)),
                cagr=float(eq[-1] ** (1 / yrs) - 1) if eq[-1] > 0 else -1.0,
                maxdd=float((eq / peak - 1).min()), ret=float(eq[-1] - 1))


def sr_d(r):
    r = np.asarray(r, float)
    return float(r.mean() / r.std(ddof=1)) if r.std(ddof=1) > 0 else 0.0


# ---------------- benchmarks ----------------
def bench_btc(panel, impact_mult, **kw):
    W = pd.DataFrame(0.0, index=panel.idx, columns=["BTCUSDT"]); W["BTCUSDT"] = 1.0
    return account(panel, W, impact_mult, **kw)


def bench_sma(panel, impact_mult, **kw):
    cols = panel.cand
    C = panel.C[cols]
    up = (C > C.rolling(100).mean()) & panel.member[cols]
    n = panel.member[cols].sum(axis=1).replace(0, np.nan)
    D = up.astype(float).div(n, axis=0).fillna(0.0)          # decision at close i
    W = D.shift(1).fillna(0.0)                                 # held from i+1, traded at open i+1
    # account() expects row T = weight traded at open T: that's W already.
    return account(panel, W, impact_mult, **kw)


# ---------------- validation helpers ----------------
def eval_grid(panel, Ws, idx_eval, impact_mult, drag, funding_mode="drag"):
    rets = {}
    accs = {}
    for k, W in Ws.items():
        a = account(panel, W, impact_mult, funding_mode, drag)
        accs[k] = a.loc[idx_eval]
        rets[k] = accs[k]["net"]
    return pd.DataFrame(rets), accs


def oof_table(R, n_splits=5, emb=0.02):
    splits = purged_kfold(len(R), n_splits, emb)
    rows = {}
    for k in R.columns:
        v = R[k].values
        fs = [sr_d(v[te]) * math.sqrt(ANN) for _, te in splits]
        rows[k] = dict(oof_sharpe=float(np.mean(fs)), oof_min=float(np.min(fs)), folds=fs, **stats_of(v))
    return pd.DataFrame(rows).T, splits


def decision_stats(R, best, bench, nb=1000):
    r = R[best].values
    T = len(r)
    sr = sr_d(r)
    srs = np.array([sr_d(R[c].values) for c in R.columns])
    dsr = deflated_sharpe_ratio(sr, N_TRIALS, T, float(stats.skew(r)), float(stats.kurtosis(r, fisher=False)),
                                var_sr=float(srs.var(ddof=1)))
    psr = probabilistic_sharpe_ratio(sr, T, float(stats.skew(r)), float(stats.kurtosis(r, fisher=False)))
    pbo = pbo_cscv(R.values, n_splits=16)
    out = dict(sr_daily=sr, dsr=dsr, psr=psr, pbo=pbo["pbo"], n_comb=pbo["n_combinations"], bench={})
    for nm, b in bench.items():
        wrc = whites_reality_check(R.values, b.values, n_boot=nb, rng=0)
        spa = hansen_spa(R.values, b.values, n_boot=nb, rng=0)
        out["bench"][nm] = dict(wrc_p=float(wrc["p_value"]), spa_p=float(spa["p_value"]),
                                best_vs_bench=list(R.columns)[int(spa["best"])] if not isinstance(spa["best"], str) else spa["best"])
    return out


# ---------------- event studies (mechanism surrogates) ----------------
def entries(panel, W, idx_eval):
    Wp = W.shift(1).fillna(0.0)
    ent = (W > 1e-9) & (Wp <= 1e-9)
    ent = ent.loc[idx_eval]
    pos = np.argwhere(ent.values)
    cols = list(W.columns)
    out = pd.DataFrame({"t": ent.index[pos[:, 0]], "sym": [cols[j] for j in pos[:, 1]]})
    return out


def event_frame(panel, ev, W_cols, sig):
    """Features at the SIGNAL bar (close of day T-1) and forward return from OPEN T."""
    idx = panel.idx
    loc = idx.get_indexer(ev["t"])
    ok = loc >= 2
    ev = ev[ok].copy(); loc = loc[ok]
    ev["loc"] = loc
    rows = []
    O, C, QV, TBQ = panel.O, panel.C, panel.QV, panel.TBQ
    oiw, rank = panel.oi, panel.rank
    fs, fav = panel.fsum, panel.fund_avail
    for s, g in ev.groupby("sym"):
        l = g["loc"].values
        o = O[s].values; c = C[s].values
        fwd = np.full(len(l), np.nan)
        m = l + FWD_H < len(idx)
        fwd[m] = o[l[m] + FWD_H] / o[l[m]] - 1
        up = c[l - 1] > c[l - 2]
        tbr = TBQ[s].values[l - 1] / QV[s].values[l - 1]
        oiv = oiw[s].values
        oichg = oiv[l] / oiv[l - 1] - 1          # 00:00 snapshot at T vs T-1: change over day T-1 (known at close T-1)
        fsv = fs[s].values; fa = fav[s].values
        f3 = np.array([fsv[max(0, x - 3):x].mean() if fa[x - 1] else np.nan for x in l])
        rows.append(pd.DataFrame(dict(t=g["t"].values, sym=s, fwd=fwd, up=up, tbr=tbr, oichg=oichg, f3=f3,
                                      rank=rank[s].values[l - 1])))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def welch(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    a, b = a[~np.isnan(a)], b[~np.isnan(b)]
    if len(a) < 10 or len(b) < 10:
        return dict(diff=np.nan, p=np.nan, na=len(a), nb=len(b))
    t, p = stats.ttest_ind(a, b, equal_var=False)
    return dict(diff=float(a.mean() - b.mean()), p=float(p), na=len(a), nb=len(b), ma=float(a.mean()), mb=float(b.mean()))


# ---------------- main ----------------
def pct(x):
    return f"{100 * x:.1f}%"


def main():
    force = "--force" in sys.argv
    t0 = time.time()
    log("loading")
    raw = load_raw()
    full = Panel(raw)
    dates = full.idx[full.idx >= full.start]
    n = len(dates)
    cut = int(round((1 - HOLDOUT_FRAC) * n))
    is_dates, ho_dates = dates[:cut], dates[cut:]
    is_last = is_dates[-1]
    log(f"eval {dates[0].date()}..{dates[-1].date()} n={n}; IS {is_dates[0].date()}..{is_last.date()} ({cut}); HO {ho_dates[0].date()}..{ho_dates[-1].date()} ({len(ho_dates)})")
    # IS panel: NOTHING after is_last is visible while selecting
    isp = Panel(raw, end=is_last)
    assert (isp.member.loc[is_dates].values == full.member.loc[is_dates, isp.cols].values).all(), "PIT membership differs IS vs full"
    log(f"universe: N={N_UNIVERSE}; ever-member symbols IS={len(isp.cand)}, full={len(full.cand)}")

    # funding drag from IS only: median daily funding sum over symbols with funding data
    m = isp.fsum.where(isp.fund_avail).loc[is_dates].stack()
    drag = float(m.median())
    drag_mean = float(m.mean())
    log(f"funding drag (median daily sum, IS, 77-sym) = {drag:.6f}/day (mean {drag_mean:.6f})")

    # coverage stats
    mem = isp.member.loc[is_dates]
    cov_f = float((isp.fund_avail.loc[is_dates] & mem).values.sum() / mem.values.sum())
    cov_oi = float((isp.oi_avail.loc[is_dates] & mem).values.sum() / mem.values.sum())
    cov_f_all = float((full.fund_avail.loc[dates] & full.member.loc[dates]).values.sum() / full.member.loc[dates].values.sum())
    thr = float(isp.qv30.where(isp.member).loc[is_dates].min(axis=1).median())
    log(f"coverage IS: funding {cov_f:.2%} oi {cov_oi:.2%}; median rank-{N_UNIVERSE} qv30 {thr:,.0f}")

    # ---- positions (IS panel only) ----
    log("positions IS (24 + 6 oi-control)")
    Ws = {k: positions(isp, k, p, "is", force=force) for k, p in GRID.items()}
    oi_mask = isp.member & isp.oi_avail
    Wc = {}
    for s, sp in SIGNALS:
        Wc[s] = positions(isp, f"{s}|ctrl_oi", {**sp, **FIXED}, "isctrl", mask=oi_mask, force=force)
    log(f"positions done {time.time()-t0:.0f}s")

    base_cfg = {}
    results = {}
    verdict_by_mult = {}
    for mult in (1.0, 0.5, 2.0):
        R, accs = eval_grid(isp, Ws, is_dates, mult, drag)
        bt = bench_btc(isp, mult, funding_mode="drag", drag=drag).loc[is_dates]["net"]
        sm = bench_sma(isp, mult, funding_mode="drag", drag=drag).loc[is_dates]["net"]
        tab, splits = oof_table(R)
        best = tab["oof_sharpe"].astype(float).idxmax()
        ds = decision_stats(R, best, {"BTC buy&hold": bt, "SMA100 equal-weight": sm})
        bst = stats_of(R[best].values)
        bts, sms = stats_of(bt.values), stats_of(sm.values)
        verdict_by_mult[mult] = dict(R=R, accs=accs, tab=tab, best=best, ds=ds, bt=bt, sm=sm, bst=bst, bts=bts, sms=sms)
        log(f"mult {mult}: best {best} oofSR {tab.loc[best,'oof_sharpe']:.2f} IS SR {bst['sharpe']:.2f} DSR p={ds['dsr']['p_value']:.3f} PBO={ds['pbo']:.3f}")
    B = verdict_by_mult[1.0]
    R, tab, best = B["R"], B["tab"], B["best"]

    # sensitivity without funding on missing (base cost)
    R_nf, _ = eval_grid(isp, Ws, is_dates, 1.0, 0.0, funding_mode="drag")
    tab_nf, _ = oof_table(R_nf)
    best_nf = tab_nf["oof_sharpe"].astype(float).idxmax()

    # ---- P1 (net, base cost) ----
    sr_ann = lambda s: sr_d(s.values) * math.sqrt(ANN)
    p1 = {}
    for var, ctrl in (("+vol", None), ("+oi", "oi")):
        deltas, rows = [], []
        fil_ret, bare_ret = [], []
        for s, _ in SIGNALS:
            rf = R[f"{s}|{var}"]
            if ctrl == "oi":
                rb = account(isp, Wc[s], 1.0, "drag", drag).loc[is_dates]["net"]
            else:
                rb = R[f"{s}|bare"]
            deltas.append(sr_ann(rf) - sr_ann(rb)); rows.append((s, sr_ann(rb), sr_ann(rf)))
            fil_ret.append(rf.values); bare_ret.append(rb.values)
        dd = np.mean(fil_ret, axis=0) - np.mean(bare_ret, axis=0)
        ci = block_bootstrap_ci(dd, lambda x: np.mean(x) * ANN, n_boot=1000, rng=0)
        p1[var] = dict(rows=rows, mean_delta=float(np.mean(deltas)), n_improved=int(np.sum(np.array(deltas) > 0)),
                       ci_low=ci["ci_low"], ci_high=ci["ci_high"], ann_ret_diff=ci["point"])
    p1_for = any(v["mean_delta"] > 0 and v["n_improved"] >= 4 and v["ci_low"] > 0 for v in p1.values())
    p1_against = all(v["mean_delta"] < 0 and v["ci_high"] < 0 for v in p1.values())
    p1_status = "FOR" if p1_for else ("AGAINST" if p1_against else "INCONCLUSIVE")

    # ---- event studies on the 6 bare signals (IS, pooled) ----
    evs = []
    for s, _ in SIGNALS:
        e = entries(isp, Ws[f"{s}|bare"], is_dates)
        e["sig"] = s
        evs.append(e)
    ev = pd.concat(evs, ignore_index=True)
    ef = event_frame(isp, ev, None, None)
    # base rates over all member-days (IS): up-day & flags
    memb = isp.member.loc[is_dates]
    Cc = isp.C
    upall = (Cc.shift(1) > Cc.shift(2)).loc[is_dates]    # at day T: signal bar T-1 up
    tbrall = (isp.TBQ / isp.QV).shift(1).loc[is_dates]
    oichall = (isp.oi / isp.oi.shift(1) - 1).loc[is_dates]
    oiok = isp.oi_avail.loc[is_dates]
    base_tbr = float((((tbrall < 0.5) & upall & memb).values.sum()) / ((upall & memb).values.sum()))
    base_oi = float((((oichall < -0.01) & upall & memb & oiok).values.sum()) / ((upall & memb & oiok).values.sum()))
    e_up = ef[ef["up"]]
    e_tbr = e_up[e_up["tbr"] < 0.5]
    p_tbr = float(stats.binomtest(len(e_tbr), len(e_up), base_tbr, alternative="greater").pvalue) if len(e_up) else np.nan
    e_oi_all = e_up[e_up["oichg"].notna()]
    e_oi = e_oi_all[e_oi_all["oichg"] < -0.01]
    p_oi = float(stats.binomtest(len(e_oi), len(e_oi_all), base_oi, alternative="greater").pvalue) if len(e_oi_all) else np.nan
    fw_tbr = welch(e_tbr["fwd"], e_up[e_up["tbr"] >= 0.5]["fwd"])
    fw_oi = welch(e_oi["fwd"], e_oi_all[e_oi_all["oichg"] >= -0.01]["fwd"])
    cl_tbr = len(e_tbr) / max(len(e_up), 1) / base_tbr if base_tbr else np.nan
    cl_oi = len(e_oi) / max(len(e_oi_all), 1) / base_oi if base_oi else np.nan
    def p2_flag(cl, p, fw):
        if cl > 1.2 and p < 0.05 and fw["diff"] > 0:
            return "FOR"
        if cl < 0.8 or (fw["p"] < 0.05 and fw["diff"] < 0):
            return "AGAINST"
        return "INCONCLUSIVE"
    p2a, p2b = p2_flag(cl_tbr, p_tbr, fw_tbr), p2_flag(cl_oi, p_oi, fw_oi)
    p2_status = "FOR" if "FOR" in (p2a, p2b) and "AGAINST" not in (p2a, p2b) else ("AGAINST" if "AGAINST" in (p2a, p2b) and "FOR" not in (p2a, p2b) else "INCONCLUSIVE")

    # P4: funding at signal (trailing 3d mean), low vs high
    ef_f = ef[ef["f3"].notna() & ef["fwd"].notna()]
    med_f = float(ef_f["f3"].median()) if len(ef_f) else np.nan
    w4 = welch(ef_f[ef_f["f3"] <= med_f]["fwd"], ef_f[ef_f["f3"] > med_f]["fwd"])
    p4_status = "INCONCLUSIVE"
    if w4["p"] == w4["p"]:
        if w4["p"] < 0.05 and w4["diff"] > 0:
            p4_status = "FOR"
        elif w4["p"] < 0.05 and w4["diff"] < 0:
            p4_status = "AGAINST"
    # P3: small vs large by PIT rank at signal bar
    efr = ef[ef["rank"].notna() & ef["fwd"].notna()]
    w3 = welch(efr[efr["rank"] > 10]["fwd"], efr[efr["rank"] <= 10]["fwd"])
    p3_status = "INCONCLUSIVE"
    if w3["p"] == w3["p"]:
        if w3["p"] < 0.05 and w3["diff"] > 0:
            p3_status = "FOR"
        elif w3["p"] < 0.05 and w3["diff"] < 0:
            p3_status = "AGAINST"
    # best-config pnl attribution by rank bucket
    Wb = Ws[best]; cols = list(Wb.columns)
    gap = (isp.O[cols] / isp.C[cols].shift(1) - 1).fillna(0); intra = (isp.C[cols] / isp.O[cols] - 1).fillna(0)
    pnl_s = (Wb.shift(1).fillna(0) * gap + Wb * intra).loc[is_dates]
    rk_prev = isp.rank[cols].shift(1).loc[is_dates]
    attr_small = float(pnl_s.where(rk_prev > 10, 0).values.sum()); attr_large = float(pnl_s.where(rk_prev <= 10, 0).values.sum())
    # P5 decay
    rb = R[best]
    half = len(rb) // 2
    s1, s2 = rb.values[:half], rb.values[half:]
    l1, l2 = sharpe_lo(s1), sharpe_lo(s2)
    zdec = (l1["sharpe"] - l2["sharpe"]) / math.sqrt(l1["se"] ** 2 + l2["se"] ** 2)
    yr = rb.groupby(rb.index.year).apply(lambda x: sr_d(x.values) * math.sqrt(ANN) if len(x) > 30 else np.nan).dropna()
    yr_med = R.groupby(R.index.year).apply(lambda x: np.nanmedian([sr_d(x[c].values) * math.sqrt(ANN) for c in x.columns]))
    if l2["sharpe"] < l1["sharpe"] and zdec > 1.64:
        p5_status = "FOR"
    elif l2["sharpe"] > l1["sharpe"] and zdec < -1.64:
        p5_status = "AGAINST"
    else:
        p5_status = "INCONCLUSIVE"
    p6_status = "UNTESTABLE"
    gates = dict(P1=p1_status, P2=p2_status, P3=p3_status, P4=p4_status, P5=p5_status, P6=p6_status)
    n_for = sum(gates[k] == "FOR" for k in ("P2", "P3", "P4", "P5", "P6"))
    any_against = any(v == "AGAINST" for v in gates.values())
    point6 = (p1_status == "FOR") and n_for >= 2 and not any_against
    log("gates", gates)

    # ---- select done -> NOW (and only now) evaluate best on holdout, once ----
    log(f"BEST (IS-selected) = {best}; evaluating holdout once")
    pbest = GRID[best]
    Wfull = positions(full, best, pbest, "full", force=force)
    Wis_chk = Ws[best].loc[is_dates]
    leak_diff = float((Wfull.reindex(columns=Wis_chk.columns).loc[is_dates].fillna(0) - Wis_chk).abs().values.max())
    log(f"holdout-isolation check: max |W_full - W_IS| on IS rows = {leak_diff:.3e}")
    ho = {}
    for mult in (1.0, 0.5, 2.0):
        bm = verdict_by_mult[mult]["best"]
        Wf = Wfull if bm == best else positions(full, bm, GRID[bm], "full", force=force)
        a_full = account(full, Wf, mult, "drag", drag)
        bt_f = bench_btc(full, mult, funding_mode="drag", drag=drag)
        sm_f = bench_sma(full, mult, funding_mode="drag", drag=drag)
        ho[mult] = dict(best=bm, strat=stats_of(a_full.loc[ho_dates]["net"].values),
                        is_=stats_of(a_full.loc[is_dates]["net"].values),
                        btc=stats_of(bt_f.loc[ho_dates]["net"].values), sma=stats_of(sm_f.loc[ho_dates]["net"].values),
                        turn=float(a_full.loc[ho_dates]["turnover"].mean()), expo=float(a_full.loc[ho_dates]["exposure"].mean()),
                        gross=stats_of(a_full.loc[ho_dates]["gross"].values),
                        net_series=a_full.loc[ho_dates]["net"])
    # no-funding-on-missing sensitivity for best
    acc_nf = account(full, Wfull, 1.0, "nofund_missing", 0.0)
    ho_nf = stats_of(acc_nf.loc[ho_dates]["net"].values); is_nf = stats_of(acc_nf.loc[is_dates]["net"].values)

    # ---- cost-model validation: vectorised vs costs.apply_costs on a sample ----
    win = is_dates[600:900]
    sample_cols = [c for c in Ws[best].columns if ((Ws[best][c].diff().abs().loc[win]) > 1e-9).any()][:3]
    tr = []
    Wb2 = Ws[best]
    for c in sample_cols:
        d = (Wb2[c] - Wb2[c].shift(1).fillna(0)).loc[win]
        for t, v in d[d.abs() > 1e-9].items():
            tr.append(dict(ts=t.tz_localize(None), symbol=c, side="buy" if v > 0 else "sell", notional_usd=abs(v) * CAPITAL, is_maker=False))
    cost_chk = None
    if tr:
        mk = isp.adv[sample_cols].stack().rename("adv_usd").reset_index(); mk.columns = ["ts", "symbol", "adv_usd"]; mk["ts"] = mk["ts"].dt.tz_localize(None)
        ac = apply_costs(pd.DataFrame(tr), mk, CostParams())
        vec = account(isp, Wb2[sample_cols], 1.0, "nofund_missing", 0.0).loc[win]
        cost_chk = dict(n_trades=len(tr), apply_costs_fee_impact=float((ac["fee_usd"] + ac["impact_usd"]).sum()),
                        vector_fee_impact=float(((vec["fee"] + vec["impact"]) * CAPITAL).sum()),
                        cap_frac=float((np.array([t["notional_usd"] for t in tr]) > 0.10 * isp.QV.shift(1).stack().reindex(
                            pd.MultiIndex.from_tuples([(t["ts"], t["symbol"]) for t in tr])).values).mean()))
    # participation check over all best-config trades
    dWb = (Ws[best] - Ws[best].shift(1).fillna(0)).abs().loc[is_dates] * CAPITAL
    capviol = float(((dWb > 0.10 * isp.QV[Ws[best].columns].shift(1).loc[is_dates]) & (dWb > 0)).values.sum() / max((dWb > 0).values.sum(), 1))

    # ---- verdict per impact multiplier ----
    def verdict_points(mult):
        V = verdict_by_mult[mult]
        ds, bst = V["ds"], V["bst"]
        h = ho[mult]
        sp_p = max(v["spa_p"] for v in ds["bench"].values())
        pts = {}
        pts[1] = (ds["dsr"]["p_value"] < 0.05 and ds["dsr"]["dsr"] > 0.5, f"DSR={ds['dsr']['dsr']:.3f} (p={ds['dsr']['p_value']:.3f}); SR*={ds['dsr']['sr_star']*math.sqrt(ANN):.2f} ann vs obs {ds['sr_daily']*math.sqrt(ANN):.2f}; PSR(0)={ds['psr']['psr']:.3f}")
        pts[2] = (ds["pbo"] < 0.05, f"PBO={ds['pbo']:.3f} ({ds['n_comb']} CSCV partitions)")
        pts[3] = (sp_p < 0.05, "SPA p: " + "; ".join(f"{k}={v['spa_p']:.3f} (WRC {v['wrc_p']:.3f})" for k, v in ds["bench"].items()))
        pts[4] = (bst["sharpe"] > V["bts"]["sharpe"] and bst["sharpe"] > V["sms"]["sharpe"],
                  f"net Sharpe {bst['sharpe']:.2f} vs BTC B&H {V['bts']['sharpe']:.2f}, SMA100 {V['sms']['sharpe']:.2f} (CAGR {pct(bst['cagr'])} vs {pct(V['bts']['cagr'])} / {pct(V['sms']['cagr'])})")
        hs = h["strat"]
        pts[5] = (hs["sharpe"] > 0 and hs["cagr"] > 0 and hs["sharpe"] >= 0.5 * h["is_"]["sharpe"],
                  f"holdout net Sharpe {hs['sharpe']:.2f}, CAGR {pct(hs['cagr'])}, maxDD {pct(hs['maxdd'])} vs IS Sharpe {h['is_']['sharpe']:.2f} (rule: >0 and >= 0.5x IS)")
        return pts
    pts = {m_: verdict_points(m_) for m_ in (1.0, 0.5, 2.0)}
    pts[1.0][6] = (point6, f"P1={p1_status}; FOR among P2-P6 = {n_for}; any AGAINST = {any_against}; gates={gates}")
    pts[1.0][7] = (False, "NOT RUN in this environment (replication is designated for the cloud on Bybit); counts as not satisfied")

    # ---------------- write report ----------------
    L = []
    A = L.append
    A("# Mechanism study: trend/breakout on Binance USDT-perps (daily)\n")
    A(f"Generated {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())} by `research/mech_runner.py`. Pre-registration frozen; grid/decision rule unchanged.\n")
    ov = "NOT CONFIRMED"
    A(f"## Overall: **{ov}** (edge not confirmed; point 7 was not run and points below decide the rest)\n")
    A("## (a) Universe\n")
    A(f"* Point-in-time **top-N = {N_UNIVERSE}** USDT-perps by trailing {RANK_WIN}-day mean quote volume, ranked at every daily close using only days <= t from `klines_1d_binance` (689 symbols incl. 75+ delisted). Same N for every config, benchmark and window.")
    A(f"* WHY N={N_UNIVERSE}: chosen a priori (before any result) as the 'liquid majors' scale: in 2021-2026 the 30th-ranked coin still trades a median ${thr/1e6:,.0f}M/day (median across days of the rank-30 trailing volume, IS), so a $1M book is <<10% of volume; larger N would pull in mid-caps whose impact is exactly the uncalibrated part of the cost model. Not tuned.")
    A(f"* Eligibility on day t: is_usdt_perp, bar exists with volume>0, t < delivery_ts, >= {RANK_WIN} days of history; pegged/stable bases excluded (`{sorted(STABLE_BASES)}`). Delisted symbols stay members until their last bar (delivery_ts / last archive bar).")
    A(f"* Evaluation starts {dates[0].date()} (first day with >= {MIN_MEMBERS_START} members; early history has <30 listed perps so universe < N). Window {dates[0].date()}..{dates[-1].date()} ({n} days; last partial bar dropped). In-sample (IS) {is_dates[0].date()}..{is_last.date()} ({cut} d); forward holdout {ho_dates[0].date()}..{ho_dates[-1].date()} ({len(ho_dates)} d, last 20%).")
    A(f"* Ever-member symbols: IS {len(isp.cand)}, full {len(full.cand)}. Rebrands (MATIC->POL, MKR->SKY...) are separate symbols (not stitched).")
    A(f"* Coverage of member symbol-days (IS): real funding {pct(cov_f)} (full sample {pct(cov_f_all)}); OI history {pct(cov_oi)} (so **+oi trades only that subset**, almost none before ~2021-12). Missing-funding symbol-days get a constant drag of **{drag*1e4:.2f} bp/day** per unit long (= median daily funding sum across the 77 funded symbols over IS; mean {drag_mean*1e4:.2f}). Sensitivity with 0 drag is below.")
    A(f"* Costs: taker fee {CostParams().taker_fee}, impact = max(0.5bp, impact_k*sqrt(trade/ADV)) from `costs.impact_bps` (impact_k=0.5 STUB), ADV = trailing {RANK_WIN}d quote volume known before the open, notional = |dW| x ${CAPITAL:,.0f}; funding applied on the held weight; borrow n/a (long-only). Participation-cap violations (trade > 10% of previous-day volume): {capviol:.4%} of trades. Vectorised cost path vs `costs.apply_costs` (fee+impact) on {cost_chk['n_trades'] if cost_chk else 0} sample trades: {cost_chk['vector_fee_impact']:.2f} vs {cost_chk['apply_costs_fee_impact']:.2f} USD." if cost_chk else "")
    A("\n## (b) All 24 configs, in-sample (net of fees, impact, funding)\n")
    A("OOF = purged 5-fold (embargo 2%) over the IS window; params are fixed (no training), so the OOF series is the IS series cut into 5 contiguous test folds and 'OOF Sharpe' = mean of the 5 fold Sharpes (annualised sqrt(365)).\n")
    A("| config | OOF Sharpe (mean of 5) | worst fold | IS net Sharpe | net CAGR | maxDD | rank |")
    A("|---|---|---|---|---|---|---|")
    order = tab["oof_sharpe"].astype(float).sort_values(ascending=False)
    for k in order.index:
        r = tab.loc[k]
        A(f"| {k} | {r['oof_sharpe']:.2f} | {r['oof_min']:.2f} | {r['sharpe']:.2f} | {pct(r['cagr'])} | {pct(r['maxdd'])} | {list(order.index).index(k)+1} |")
    A(f"| **BTC buy&hold (same costs)** | - | - | {B['bts']['sharpe']:.2f} | {pct(B['bts']['cagr'])} | {pct(B['bts']['maxdd'])} | |")
    A(f"| **SMA100 equal-weight (same costs)** | - | - | {B['sms']['sharpe']:.2f} | {pct(B['sms']['cagr'])} | {pct(B['sms']['maxdd'])} | |")
    A(f"\nSelected (max mean-OOF Sharpe): **{best}**. Mean daily turnover (sum|dW|) of best: {B['accs'][best]['turnover'].mean():.3f}; mean gross exposure {B['accs'][best]['exposure'].mean():.2f}.")
    cost_decomp = B["accs"][best][["gross", "fee", "impact", "funding", "net"]].mean() * ANN
    A(f"Best config annualised return decomposition (arithmetic, IS): gross {pct(cost_decomp['gross'])}, fees {pct(-cost_decomp['fee'])}, impact {pct(-cost_decomp['impact'])}, funding {pct(-cost_decomp['funding'])}, net {pct(cost_decomp['net'])}.")
    A(f"Funding sensitivity: with NO drag on symbols missing funding history, best-by-OOF would be {best_nf}; IS net Sharpe of {best} = {is_nf['sharpe']:.2f} (vs {B['bst']['sharpe']:.2f}), holdout net Sharpe {ho_nf['sharpe']:.2f} (vs {ho[1.0]['strat']['sharpe']:.2f}).\n")
    A("## (c) 7-point decision rule (base costs, impact_k=0.5)\n")
    A("| # | criterion | result | number |")
    A("|---|---|---|---|")
    names = {1: "Best-config DSR>0 at p<0.05 (n_trials=24)", 2: "PBO < 5%", 3: "SPA rejects 'no edge' p<0.05 vs BTC B&H AND SMA100 (worse of the two)",
             4: "Net Sharpe > BTC B&H and > SMA100 (IS)", 5: "Holds on forward holdout (net>0, Sharpe >= half of IS)", 6: "Mechanism: P1 FOR, >=2 of P2-P6 FOR, none AGAINST", 7: "Independent replication on Bybit"}
    for i in range(1, 8):
        ok, num = pts[1.0][i]
        A(f"| {i} | {names[i]} | **{'PASS' if ok else 'FAIL'}** | {num} |")
    npass = sum(pts[1.0][i][0] for i in range(1, 8))
    A(f"\n{npass}/7 pass. Rule requires all 7 -> **edge NOT CONFIRMED**." if npass < 7 else "\nAll 7 pass.")
    A("\n## (d) impact_k sensitivity (x0.5 / x1 / x2)\n")
    A("| impact_k | best (by OOF) | IS Sharpe | DSR p | PBO | SPA p (worse) | pt1 | pt2 | pt3 | pt4 | pt5 | holdout Sharpe |")
    A("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for m_ in (0.5, 1.0, 2.0):
        V = verdict_by_mult[m_]; P = pts[m_]
        A(f"| {0.5*m_:.2f} | {V['best']} | {V['bst']['sharpe']:.2f} | {V['ds']['dsr']['p_value']:.3f} | {V['ds']['pbo']:.3f} | {max(v['spa_p'] for v in V['ds']['bench'].values()):.3f} | " +
          " | ".join('PASS' if P[i][0] else 'FAIL' for i in range(1, 6)) + f" | {ho[m_]['strat']['sharpe']:.2f} |")
    flips = [i for i in range(1, 6) if len({pts[m_][i][0] for m_ in (0.5, 1.0, 2.0)}) > 1]
    A(f"\nPoints 1-5 that FLIP across impact_k: {flips if flips else 'none'}. " + ("Verdict is cost-dependent (flagged)." if flips else "Verdict (NOT CONFIRMED) does not change with impact_k. Note: the selected best config under x0.5/x2 may differ; if it differs, evaluating it on the holdout is an additional look (disclosed)."))
    A(f"\n**Cost-model caveat:** costs.py impact = k*sqrt(trade/ADV) with k=0.5 gives ~{B['accs'][best]['impact'].sum()/max(B['accs'][best]['turnover'].sum(),1e-9)*1e4:.0f} bp per unit traded for this book (uncalibrated STUB, no volatility scaling); with daily vol-target resizing the best config turns over {B['accs'][best]['turnover'].mean():.2f}/day, so impact (not fees) dominates net results and the x0.5/x2 verdicts differ. Treat all net numbers as conditional on this stub.")
    A("\n## (e) Mechanism gates (P2/P4/P6 are SURROGATES; no liquidation or borrow history exists)\n")
    A(f"* **P1 (filter improves edge): {p1_status}.** Net IS Sharpe, bare vs filtered (annualised):")
    for var, v in p1.items():
        A(f"  * {var}{' (bare control restricted to symbol-days with OI history)' if var=='+oi' else ''}: mean dSharpe {v['mean_delta']:+.2f}, improved in {v['n_improved']}/6 signals, annual-return diff of the 6-signal average {pct(v['ann_ret_diff'])} (95% block-bootstrap CI {pct(v['ci_low'])}..{pct(v['ci_high'])}). Per signal (bare->filtered): " + ", ".join(f"{s} {a:.2f}->{b:.2f}" for s, a, b in v["rows"]))
    A(f"  * Rule: FOR needs mean dSharpe>0, >=4/6 improved and CI low>0 for +vol OR +oi; AGAINST if both have mean<0 and CI high<0.")
    A(f"* **P2 liquidation-cluster SURROGATE: {p2_status}.** Pooled entries of the 6 bare signals (IS, n={len(ef)}; entries from different signals overlap in time so p-values are anti-conservative). At the signal bar (close T-1) on an up-day: taker-sell-dominant (taker_buy_ratio<0.5) in {pct(len(e_tbr)/max(len(e_up),1))} of entries vs base rate {pct(base_tbr)} (ratio {cl_tbr:.2f}, binom p={p_tbr:.3f}); fwd-{FWD_H}d return flagged vs not {fw_tbr.get('ma',float('nan')):+.2%} vs {fw_tbr.get('mb',float('nan')):+.2%} (Welch p={fw_tbr['p']:.3f}) -> {p2a}. OI fell >1% on an up-day in {pct(len(e_oi)/max(len(e_oi_all),1))} of entries with OI vs base {pct(base_oi)} (ratio {cl_oi:.2f}, p={p_oi:.3f}, n_oi={len(e_oi_all)}); fwd return flagged vs not {fw_oi.get('ma',float('nan')):+.2%} vs {fw_oi.get('mb',float('nan')):+.2%} (p={fw_oi['p']:.3f}) -> {p2b}.")
    A(f"* **P3 edge concentrates in smaller coins: {p3_status}.** Entries by PIT liquidity rank at the signal bar: rank>10 (n={w3['na']}) mean fwd-{FWD_H}d {w3.get('ma',float('nan')):+.2%} vs rank<=10 (n={w3['nb']}) {w3.get('mb',float('nan')):+.2%}, diff {w3['diff']:+.2%}, Welch p={w3['p']:.3f}. Best-config gross P&L attribution (IS, arithmetic sum of daily contributions): rank>10 {attr_small:+.2f}, rank<=10 {attr_large:+.2f}. Retail-venue split (spot, Coinbase) NOT available -> by-rank proxy only.")
    A(f"* **P4 expensive-short (funding as proxy): {p4_status}.** Entries split at median trailing-3d funding ({med_f*1e4:.2f} bp/day): low-funding (shorts pay / crowded short) mean fwd-{FWD_H}d {w4.get('ma',float('nan')):+.2%} (n={w4['na']}) vs high {w4.get('mb',float('nan')):+.2%} (n={w4['nb']}), diff {w4['diff']:+.2%}, p={w4['p']:.3f}. Real borrow cost history is untestable; funding is the perp surrogate. CAVEAT: trailing funding is a bull-market proxy (high funding = strong-uptrend regimes), so this split is confounded with the market regime and 'AGAINST' here is weak evidence about shorting cost.")
    A(f"* **P5 decay: {p5_status}.** Best config IS first half Sharpe {l1['sharpe']*math.sqrt(ANN):.2f} vs second half {l2['sharpe']*math.sqrt(ANN):.2f} (z of drop = {zdec:.2f}; FOR needs lower 2nd half with z>1.64). By year (best): " + ", ".join(f"{y}: {v:.2f}" for y, v in yr.items()) + ". Median across 24 configs by year: " + ", ".join(f"{y}: {v:.2f}" for y, v in yr_med.items()) + ".")
    A("* **P6 counterparty (account-level liquidations/positions): UNTESTABLE** with free data.")
    A(f"\nGate tally: FOR among P2-P6 = {n_for}; any AGAINST = {any_against}; P1 = {p1_status} -> point 6 {'PASS' if point6 else 'FAIL'}.")
    A("\n## (f) In-sample vs forward holdout (best config, evaluated ONCE after selection)\n")
    h = ho[1.0]
    A(f"Selected on IS only: **{best}** (impact_k 0.5).\n")
    A("| window | net Sharpe | net CAGR | maxDD | total return |")
    A("|---|---|---|---|---|")
    for nm, s_ in (("IS (best)", h["is_"]), ("Holdout (best)", h["strat"]), ("Holdout gross (best, pre-cost)", h["gross"]), ("Holdout BTC buy&hold", h["btc"]), ("Holdout SMA100 EW", h["sma"])):
        A(f"| {nm} | {s_['sharpe']:.2f} | {pct(s_['cagr'])} | {pct(s_['maxdd'])} | {pct(s_['ret'])} |")
    hso = h["net_series"].values
    ci = block_bootstrap_ci(hso, lambda x: float(x.mean() / x.std(ddof=1) * math.sqrt(ANN)), n_boot=1000, rng=0)
    A(f"\nHoldout net Sharpe 95% block-bootstrap CI: {ci['ci_low']:.2f}..{ci['ci_high']:.2f}. Holdout mean turnover {h['turn']:.3f}/day, exposure {h['expo']:.2f}.")
    A("\n## (g) LOOKAHEAD SELF-AUDIT\n")
    A("| risk | how it is prevented in the code |")
    A("|---|---|")
    A(f"| Universe ranking | `Panel.member`: rank on `qv30` = trailing {RANK_WIN}-day mean of quote_volume with value at row i using rows <= i (rolling, no centering); the mask at close i only gates decisions for bar i+1. Not ranked on 'today's top by volume' (that was the selected.json bias). IS and full panels are asserted to give identical membership on IS dates. Delisted symbols are kept until delivery_ts / last bar (no survivorship). |")
    A("| Signal timing | indicators in `trend.py` are trailing with `.shift(1)` on Donchian/exit/vol-median; the decision at close of bar i is shifted so row T carries weight computed from bars < T (verified in code, 9 unit tests pass after the mask patch). |")
    A("| Entry timing | trend.py's own equity curve is close-to-close, but THIS runner books P&L as W[T-1]*(O_T/C_{T-1}-1) + W[T]*(C_T/O_T-1): a signal formed at close T-1 is entered at OPEN T, never at the close it was observed. Costs are charged on |W_T - W_{T-1}| at that open, with ADV known before that open. |")
    A("| Universe vs positions | `member_mask` (new optional arg of `generate_positions`, default None=old behaviour) blocks entries and forces exits for non-members using the mask at close i. This is applied INSIDE the position loop so gross cap/kill-switch see the real portfolio. |")
    A("| Funding as-of | Realised funding is an accounting cost (events inside the bar [t, t+1d) times the weight held in that bar) - never a signal input in the main grid (funding_filter is off). Timestamps rounded to the minute to remove +-1 ms jitter. Missing-funding drag constant is the median over IS dates only. Funding/OI feature in P4 uses days <= T-1. |")
    A("| OI as-of | OI uses the 00:00 UTC snapshot (state at prior close) forward-filled onto the daily index (`trend._asof` ffill only); `oi > oi.shift(5)` is evaluated at close i. +oi therefore blocks symbols/dates without OI history (reported as reduced coverage, not dropped). |")
    A("| Holdout isolation | A separate `Panel(end=IS last day)` is built; all 24 configs, benchmarks, OOF, DSR/PBO/SPA, P1-P5 are computed on it, so no holdout bar exists in memory. Only after `best` is fixed is the full panel loaded and the best config run once. Check: max |W_full - W_IS| on IS rows = " + f"{leak_diff:.2e}" + " (positions on IS rows do not depend on later data). For the impact_k sensitivity the per-multiplier best is also evaluated on the holdout (possible additional look; flagged). |")
    A("| Purged k-fold / embargo | `purged_kfold(n,5,0.02)` test indices used. Since configs have fixed parameters, nothing is trained on the 'train' folds, so purge/embargo is vacuous; the residual leak is path dependence (stop/drawdown state carried across fold boundaries), which is causal and not removed. The OOF number is therefore close to the plain IS Sharpe; selection among 24 is handled by DSR/PBO/SPA, not by the fold split. |")
    A("| Selection bias | Best-of-24 is penalised by DSR (n_trials=24, var_sr from the 24 IS Sharpes), PBO (CSCV, 16 slices) and WRC/SPA vs both benchmarks. |")
    A("| Residual risks (not removable here) | (1) N=30 and window RANK_WIN=30 were fixed before running; (2) delisted-symbol final bars: exit at last close, no delisting-gap loss; (3) rebrand discontinuities; (4) trend.py's internal drawdown halt uses close-to-close equity, slightly different from this runner's open-entry P&L; (5) costs are uncalibrated (impact_k stub, capital $1M assumed); (6) 77-symbol funding drag constant is a assumption; (7) event-study p-values ignore clustering. |")
    A("\n## Files\n`research/mech_runner.py`, `research/strategy/trend.py` (added optional `member_mask`), `research/mech_cache/` (position cache), `reports/mech_trend.md`, `reports/mech_trend.json`.")
    REPORT.write_text("\n".join(L))
    js = dict(best=best, gates=gates, point6=point6, drag=drag, leak_diff=leak_diff,
              pts={str(m_): {str(i): [bool(v[0]), v[1]] for i, v in pts[m_].items()} for m_ in pts},
              holdout={str(m_): {k: v for k, v in ho[m_].items() if k != "net_series"} for m_ in ho},
              best_by_mult={str(m_): verdict_by_mult[m_]["best"] for m_ in verdict_by_mult})
    (ROOT / "reports" / "mech_trend.json").write_text(json.dumps(js, indent=1, default=float))
    log(f"DONE {time.time()-t0:.0f}s -> {REPORT}")


if __name__ == "__main__":
    main()
