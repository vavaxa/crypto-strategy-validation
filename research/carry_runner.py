"""FORM-L funding-carry study (long-only, buy LOW/negative funding) per research/PREREG_CARRY.md.

Usage: .venv/bin/python research/carry_runner.py [--force]
Output: reports/carry.md, reports/carry.json ; cache research/mech_cache/carry_*.pkl (resumable).
Grid (16), target_vol, band, cap, split and decision rule are FROZEN; nothing here tunes them.
Reuses research/mech_runner.py helpers (PIT universe recipe, stats_of, oof_table, decision_stats)
and research/execution/costs.py, research/validation/*.

Time base: 8h bars aligned to funding settlements (00/08/16 UTC), built from 1h klines of the 77
funded symbols; PIT liquidity ranking is the same daily top-30 trailing-30d-quote-volume recipe over
all 689 symbols, then intersected with funding-available symbols.
A-PRIORI CHOICES for underspecified items (fixed before looking at results, documented in report):
  * decision at close of bar k-1 uses funding events with ts STRICTLY < close instant (the event stamped
    exactly at the close is excluded); trade at OPEN of bar k.
  * funding event stamped exactly at bar-open t_k is charged on the PRE-trade position W_{k-1}; events
    stamped inside the bar on W_k.
  * min 10 eligible members to hold risk; quintile = ceil(0.2*n) lowest; z-tilt weight ~ max(-z,0);
    vol-target = scale so trailing-90-bar (30d) estimated book vol = 20%, gross <= 1 (no leverage);
    cap 10%/coin applied after (no redistribution); no-trade band = skip a per-coin change when
    |target-held| <= 20% * max(target, held) (entries and full exits always trade).
  * P6 limit (not given in PREREG): stress-window max DD <= 15%; bootstrap 1y worst-case (5th pct of
    maxDD) <= 35%; "hidden short-vol" flag if daily skew < -1 or excess kurtosis > 10.
  * P8 target book size = $5M (not given in PREREG).
"""
from __future__ import annotations
import sys, os, json, time, pickle, math, warnings
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import research.mech_runner as M
from research.mech_runner import (N_UNIVERSE, RANK_WIN, MIN_MEMBERS_START, HOLDOUT_FRAC, STABLE_BASES, ANN,
                                  stats_of, sr_d, oof_table, decision_stats, to_ns)
from research.execution.costs import CostParams, impact_bps
from research.validation.sharpe import sharpe_lo
from research.validation.bootstrap import block_bootstrap_ci, stationary_bootstrap_indices
from research.validation.data_snooping import hansen_spa

warnings.filterwarnings("ignore")
M.N_TRIALS = 16                      # decision_stats reads this module global (n_trials = 16)
VERSION = "v1"
MECH = ROOT / "data" / "mech"
CACHE = ROOT / "research" / "mech_cache"
OUT = ROOT / "reports"
CAPITAL = 1_000_000.0
BPY = 365.25 * 3                     # 8h bars per year
TARGET_VOL = 0.20
BAND = 0.20
CAP = 0.10
MIN_ELIG = 10
VOL_WIN, VOL_MIN = 90, 60
IMPACT_KS = [0.125, 0.25, 0.5, 1.0, 2.0]
CAPS_USD = [1e5, 1e6, 5e6, 2e7, 5e7]
TARGET_BOOK = 5e6
STRESS = {"LUNA": ("2022-05-07", "2022-05-20"), "FTX": ("2022-11-06", "2022-11-16")}
DD_LIMIT, BOOT_DD_LIMIT = 0.15, 0.35

GRID = {}
for w in (3, 7):
    for sel in ("quint", "z"):
        for wt in ("eq", "vt"):
            for rb in ("8h", "1d"):
                GRID[f"w{w}d|{sel}|{wt}|{rb}"] = dict(win=w, sel=sel, wt=wt, rb=rb)
assert len(GRID) == 16


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ---------------------------------------------------------------- data
def load_raw():
    d1 = pd.read_parquet(MECH / "klines_1d_binance.parquet")
    d1["ts"] = to_ns(d1["ts"])
    uni = pd.read_parquet(MECH / "universe_binance.parquet")
    for c in ("onboard_ts", "delivery_ts"):
        uni[c] = to_ns(uni[c])
    fu = pd.read_parquet(MECH / "funding_binance.parquet", columns=["symbol", "ts", "funding_rate"])
    fu["ts"] = to_ns(fu["ts"]).dt.round("min")
    k1 = pd.read_parquet(MECH / "klines_1h_binance.parquet", columns=["symbol", "ts", "o", "c"])
    k1["ts"] = to_ns(k1["ts"])
    return d1, uni, fu, k1


class Ctx:
    """Everything visible up to day `end` (inclusive). Nothing later exists in memory."""

    def __init__(self, raw, end=None):
        d1, uni, fu, k1 = raw
        last_complete = pd.Timestamp.now(tz="UTC").normalize() - pd.Timedelta(days=1)
        end = last_complete if end is None else min(pd.Timestamp(end), last_complete)
        self.end = end
        # ---- PIT universe: identical recipe to mech_runner.Panel (all 689 symbols) ----
        perp = set(uni.loc[uni["is_usdt_perp"], "symbol"])
        base = uni.set_index("symbol")["base"].to_dict()
        deliv = uni.set_index("symbol")["delivery_ts"].to_dict()
        d = d1[(d1["ts"] <= end) & d1["symbol"].isin(perp)]
        d = d[~d["symbol"].map(base).isin(STABLE_BASES)]
        d = d[(d["quote_volume"] > 0) & (d["c"] > 0)]
        d = d[d["ts"] < d["symbol"].map(deliv).fillna(pd.Timestamp("2100-01-01", tz="UTC")).astype("datetime64[ns, UTC]")]
        QV = d.pivot(index="ts", columns="symbol", values="quote_volume").sort_index()
        Cd = d.pivot(index="ts", columns="symbol", values="c").sort_index()
        self.didx = Cd.index
        qv30 = QV.rolling(RANK_WIN, min_periods=RANK_WIN).mean()
        elig = qv30.notna() & Cd.notna()
        rk = qv30.where(elig).rank(axis=1, ascending=False, method="first")
        self.member_d = (rk <= N_UNIVERSE) & elig            # row i: known at close i
        self.adv_d = qv30.shift(1)                            # ADV known before day i
        funded = set(fu["symbol"])
        self.cand = [c for c in Cd.columns if c in funded and self.member_d[c].any()]
        self.n_mem_d = self.member_d.sum(axis=1)
        self.n_mem_funded_d = self.member_d[self.cand].sum(axis=1)
        # ---- 8h price grid from 1h klines (funded candidates) ----
        k = k1[k1["symbol"].isin(self.cand) & (k1["ts"] < end + pd.Timedelta(days=1))].sort_values("ts")
        k = k[k["ts"] >= self.didx[0]]
        k["b"] = k["ts"].dt.floor("8h")
        g = k.groupby(["b", "symbol"])
        O8 = g["o"].first().unstack()
        C8 = g["c"].last().unstack()
        self.idx = pd.date_range(self.didx[0], end + pd.Timedelta(hours=16), freq="8h", tz="UTC")
        self.cols = list(self.cand)
        self.O = O8.reindex(index=self.idx, columns=self.cols)
        self.C = C8.reindex(index=self.idx, columns=self.cols)
        self.day = self.idx.floor("D")
        self.hour = self.idx.hour
        # per-bar membership (day D-1 close) and ADV (as mech: known before day D)
        self.memb = self.member_d[self.cols].shift(1).reindex(self.day).fillna(False).values.astype(bool)
        self.adv = self.adv_d[self.cols].reindex(self.day).values
        # ---- funding events -> per-bar bins ----
        f = fu[fu["symbol"].isin(self.cols) & (fu["ts"] < end + pd.Timedelta(days=1))].copy()
        f["b"] = f["ts"].dt.floor("8h")
        f["at_open"] = f["ts"] == f["b"]
        F0 = f[f["at_open"]].groupby(["b", "symbol"])["funding_rate"].sum().unstack()
        F1 = f[~f["at_open"]].groupby(["b", "symbol"])["funding_rate"].sum().unstack()
        Nn = f.groupby(["b", "symbol"])["funding_rate"].count().unstack()
        rix = lambda x: x.reindex(index=self.idx, columns=self.cols).fillna(0.0)
        self.F0, self.F1, self.Nev = rix(F0), rix(F1), rix(Nn)
        self.Ftot = self.F0 + self.F1
        # trailing funding features: bins <= k-1  (events strictly before the open instant of bar k)
        self.feat, self.featok = {}, {}
        for w in (3, 7):
            nb = 3 * w
            S = self.Ftot.rolling(nb, min_periods=nb).sum().shift(1)
            Nc = self.Nev.rolling(nb, min_periods=nb).sum().shift(1)
            ok = (Nc >= math.ceil(0.8 * nb)) & S.notna()
            self.feat[w], self.featok[w] = S.values, ok.values
        # vol inputs: returns known through bar k-1
        r8 = self.C / self.C.shift(1) - 1.0
        self.rv = r8.shift(1).fillna(0.0).values
        self.sig = (r8.rolling(VOL_WIN, min_periods=VOL_MIN).std().shift(1) * math.sqrt(BPY)).values
        # eval start: first day with >= MIN_MEMBERS_START eligible (7d feature) at 00:00 bar
        cnt = (self.memb & self.featok[7]).sum(axis=1)
        s = pd.Series(cnt, index=self.idx)
        s0 = s[self.hour == 0]
        self.start = s0.index[s0.values >= MIN_MEMBERS_START][0]

    def coverage(self):
        a = pd.DataFrame({"members": self.n_mem_d, "funded": self.n_mem_funded_d}).loc[self.start:]
        a["year"] = a.index.year
        return a


# ---------------------------------------------------------------- weights
def targets(ctx, cfg, k):
    """Raw (pre-band) target vector at bar k for config cfg, using only info through close of bar k-1."""
    N = len(ctx.cols)
    w = cfg["win"]
    e = ctx.memb[k] & ctx.featok[w][k]
    if cfg["wt"] == "vt":
        e = e & np.isfinite(ctx.sig[k]) & (ctx.sig[k] > 0)
    ids = np.flatnonzero(e)
    n = len(ids)
    out = np.zeros(N)
    if n < MIN_ELIG:
        return out
    fv = ctx.feat[w][k][ids]
    if cfg["sel"] == "quint":
        m = max(1, math.ceil(0.2 * n))
        sel = np.argsort(fv, kind="stable")[:m]
        raw = np.zeros(n); raw[sel] = 1.0
    else:
        sd = fv.std(ddof=1)
        if not sd > 0:
            return out
        z = (fv - fv.mean()) / sd
        raw = np.maximum(-z, 0.0)
    if cfg["wt"] == "vt":
        raw = raw / ctx.sig[k][ids]
    s = raw.sum()
    if not s > 0:
        return out
    wv = raw / s
    if cfg["wt"] == "vt":
        H = ctx.rv[max(0, k - VOL_WIN):k][:, ids]
        if len(H) >= VOL_MIN:
            pv = (H @ wv).std(ddof=1) * math.sqrt(BPY)
            if pv > 0:
                wv = wv * min(TARGET_VOL / pv, 1.0)
    out[ids] = np.minimum(wv, CAP)
    return out


def apply_band(held, tgt):
    new = tgt.copy()
    both = (tgt > 0) & (held > 0)
    skip = both & (np.abs(tgt - held) <= BAND * np.maximum(tgt, held))
    new[skip] = held[skip]
    return new


def build_W(ctx, cfg):
    T, N = len(ctx.idx), len(ctx.cols)
    W = np.zeros((T, N))
    held = np.zeros(N)
    daily = cfg["rb"] == "1d"
    for k in range(1, T):
        if (not daily) or ctx.hour[k] == 0:
            held = apply_band(held, targets(ctx, cfg, k))
        W[k] = held
    return pd.DataFrame(W, index=ctx.idx, columns=ctx.cols)


def build_naive(ctx, vt=False):
    """No funding selection: every eligible PIT member (funded), equal weight (optionally vol-targeted)."""
    T, N = len(ctx.idx), len(ctx.cols)
    W = np.zeros((T, N)); held = np.zeros(N)
    for k in range(1, T):
        if ctx.hour[k] == 0:
            e = ctx.memb[k] & ctx.featok[7][k]
            if vt:
                e = e & np.isfinite(ctx.sig[k]) & (ctx.sig[k] > 0)
            ids = np.flatnonzero(e)
            tg = np.zeros(N)
            if len(ids) >= MIN_ELIG:
                wv = np.full(len(ids), 1.0 / len(ids))
                if vt:
                    H = ctx.rv[max(0, k - VOL_WIN):k][:, ids]
                    pv = (H @ wv).std(ddof=1) * math.sqrt(BPY)
                    if pv > 0:
                        wv = wv * min(TARGET_VOL / pv, 1.0)
                tg[ids] = np.minimum(wv, CAP)
            held = apply_band(held, tg)
        W[k] = held
    return pd.DataFrame(W, index=ctx.idx, columns=ctx.cols)


def build_btc(ctx):
    W = pd.DataFrame(0.0, index=ctx.idx, columns=ctx.cols)
    W["BTCUSDT"] = 1.0
    W.iloc[0] = 0.0
    return W


def cached(tag, name, fn, force):
    f = CACHE / f"carry_{VERSION}_{tag}_{name.replace('|', '_')}.pkl"
    if f.exists() and not force:
        return pickle.load(open(f, "rb"))
    W = fn()
    pickle.dump(W, open(f, "wb"))
    return W


# ---------------------------------------------------------------- accounting (8h -> daily)
def account(ctx, W, impact_k=0.5, capital=CAPITAL):
    """Weight row k decided at close k-1, traded at OPEN k:
    price_k = W_{k-1}*(O_k/C_{k-1}-1) + W_k*(C_k/O_k-1);  costs on |dW| at open (ADV shift(1)).
    Funding: event stamped at bar open charged on W_{k-1}; events inside bar on W_k. Long pays when rate>0."""
    cols = list(W.columns)
    O, C = ctx.O[cols], ctx.C[cols]
    gap = (O / C.shift(1) - 1.0).fillna(0.0)
    intra = (C / O - 1.0).fillna(0.0)
    Wp = W.shift(1).fillna(0.0)
    price = (Wp * gap + W * intra).sum(axis=1)
    dW = (W - Wp).abs()
    cp = CostParams(impact_k=impact_k)
    ci = [ctx.cols.index(c) for c in cols]
    imp = impact_bps((dW * capital).values, ctx.adv[:, ci], cp)
    fee = (dW * cp.taker_fee).sum(axis=1)
    impact = (dW * (imp / 1e4)).sum(axis=1)
    fcost = (Wp * ctx.F0[cols] + W * ctx.F1[cols]).sum(axis=1)     # cost > 0 = paid
    net = price - fee - impact - fcost
    b = pd.DataFrame({"price": price, "fee": fee, "impact": impact, "carry": -fcost, "net": net,
                      "turn": dW.sum(axis=1), "expo": W.abs().sum(axis=1)})
    g = b.groupby(ctx.day)
    d = g[["price", "fee", "impact", "carry", "turn"]].sum()
    d["net"] = g["net"].apply(lambda x: float(np.prod(1 + x.values) - 1))
    d["expo"] = g["expo"].mean()
    return d


def dd_stats(r):
    r = np.asarray(r, float)
    eq = np.cumprod(1 + r)
    peak = np.maximum.accumulate(np.r_[1.0, eq])[1:]
    return float((eq / peak - 1).min())


def nw_t(x, lag=10):
    x = np.asarray(x, float); T = len(x); m = x.mean(); xc = x - m
    v = xc @ xc / T
    for l in range(1, lag + 1):
        v += 2 * (1 - l / (lag + 1)) * (xc[l:] @ xc[:-l]) / T
    return float(m / math.sqrt(v / T)) if v > 0 else float("nan")


def pct(x):
    return f"{100 * x:.1f}%"


# ---------------------------------------------------------------- main
def main():
    force = "--force" in sys.argv
    t0 = time.time()
    CACHE.mkdir(exist_ok=True)
    log("loading")
    raw = load_raw()
    full = Ctx(raw)
    dates = full.didx[(full.didx >= full.start) & (full.didx <= full.end)]
    n = len(dates)
    cut = int(round((1 - HOLDOUT_FRAC) * n))
    is_dates, ho_dates = dates[:cut], dates[cut:]
    is_last = is_dates[-1]
    log(f"eval {dates[0].date()}..{dates[-1].date()} n={n}; IS ..{is_last.date()} ({cut}); HO {ho_dates[0].date()}..{ho_dates[-1].date()} ({len(ho_dates)})")
    isc = Ctx(raw, end=is_last)
    assert isc.start == full.start
    log(f"funded candidates: IS {len(isc.cols)} full {len(full.cols)}")

    cov = full.coverage()
    coverage = dict(mean_members=float(cov["members"].mean()), mean_funded=float(cov["funded"].mean()),
                    frac=float(cov["funded"].sum() / cov["members"].sum()),
                    by_year={int(y): dict(members=float(g["members"].mean()), funded=float(g["funded"].mean()),
                                          frac=float(g["funded"].sum() / g["members"].sum()))
                             for y, g in cov.groupby("year")},
                    min_funded=int(cov["funded"].min()))
    log("coverage", coverage["frac"], coverage["mean_funded"])

    # ---- weights on IS ctx ----
    log("weights IS")
    Wis = {k: cached("is", k, lambda c=c: build_W(isc, c), force) for k, c in GRID.items()}
    Wn_is = cached("is", "naive_eq", lambda: build_naive(isc), force)
    Wnv_is = cached("is", "naive_vt", lambda: build_naive(isc, vt=True), force)
    Wb_is = build_btc(isc)
    log(f"weights done {time.time()-t0:.0f}s")

    res = {}
    for ik in IMPACT_KS:
        accs = {k: account(isc, W, ik).loc[is_dates] for k, W in Wis.items()}
        R = pd.DataFrame({k: a["net"] for k, a in accs.items()})
        bt = account(isc, Wb_is, ik).loc[is_dates]
        nv = account(isc, Wn_is, ik).loc[is_dates]
        nvt = account(isc, Wnv_is, ik).loc[is_dates]
        tab, splits = oof_table(R)
        best = tab["oof_sharpe"].astype(float).idxmax()
        ds = decision_stats(R, best, {"BTC buy&hold": bt["net"], "Naive EW (no selection)": nv["net"]})
        bst, bts, nvs = stats_of(R[best].values), stats_of(bt["net"].values), stats_of(nv["net"].values)
        p4 = bool(bst["sharpe"] > bts["sharpe"] and bst["sharpe"] > nvs["sharpe"]
                  and bst["cagr"] > bts["cagr"] and bst["cagr"] > nvs["cagr"])
        res[ik] = dict(accs=accs, R=R, bt=bt, nv=nv, nvt=nvt, tab=tab, best=best, ds=ds, bst=bst, bts=bts, nvs=nvs, p4=p4)
        log(f"impact_k {ik}: best {best} oofSR {tab.loc[best,'oof_sharpe']:.2f} IS SR {bst['sharpe']:.2f} cagr {bst['cagr']:.3f} "
            f"| BTC {bts['sharpe']:.2f}/{bts['cagr']:.3f} naive {nvs['sharpe']:.2f}/{nvs['cagr']:.3f} p4={p4} "
            f"DSRp={ds['dsr']['p_value']:.3f} PBO={ds['pbo']:.3f}")
    B = res[0.5]
    best, R, tab, ds = B["best"], B["R"], B["tab"], B["ds"]
    accs = B["accs"]

    # ---- per-config table (impact_k 0.5) ----
    def brow(a):
        s = stats_of(a["net"].values)
        return dict(is_sharpe=s["sharpe"], net_cagr=s["cagr"], maxdd=s["maxdd"], carry_bps_yr=float(a["carry"].mean() * 365 * 1e4),
                    price_pct_yr=float(a["price"].mean() * 365), cost_pct_yr=float((a["fee"] + a["impact"]).mean() * 365),
                    turn_yr=float(a["turn"].mean() * 365), expo=float(a["expo"].mean()))
    cfg_rows = {}
    for k in GRID:
        cfg_rows[k] = dict(oof_sharpe=float(tab.loc[k, "oof_sharpe"]), **brow(accs[k]))
    bench_rows = {"BTC buy&hold": brow(B["bt"]), "Naive EW (no selection)": brow(B["nv"]),
                  "Naive vol-targeted (diagnostic)": brow(B["nvt"])}

    # ---- P1 realized funding cashflow ----
    cf = accs[best]["carry"].values
    ci1 = block_bootstrap_ci(cf, np.mean, n_boot=1000, rng=0)
    p1 = dict(mean_bps_yr=float(cf.mean() * 365 * 1e4), nw_t=nw_t(cf), ci_lo_bps_yr=ci1["ci_low"] * 365 * 1e4,
              ci_hi_bps_yr=ci1["ci_high"] * 365 * 1e4)
    p1["pass"] = bool(p1["mean_bps_yr"] > 0 and p1["ci_lo_bps_yr"] > 0)
    p1["all_configs_bps_yr"] = {k: cfg_rows[k]["carry_bps_yr"] for k in GRID}
    dcf = accs[best]["carry"].values - B["nv"]["carry"].values
    p1["vs_naive_bps_yr"] = float(dcf.mean() * 365 * 1e4)
    p1["vs_naive_nw_t"] = nw_t(dcf)
    p1["carry_pct_of_notional_yr"] = float(accs[best]["carry"].sum() / accs[best]["expo"].sum() * 365 * 100)
    p1["naive_carry_pct_of_notional_yr"] = float(B["nv"]["carry"].sum() / B["nv"]["expo"].sum() * 365 * 100)

    # ---- P2 / P3 / P4 ----
    p2 = dict(dsr_p=float(ds["dsr"]["p_value"]), dsr=float(ds["dsr"]["dsr"]), pbo=float(ds["pbo"]), sr_star=float(ds["dsr"]["sr_star"]))
    p2["pass"] = bool(p2["dsr_p"] < 0.05 and p2["dsr"] > 0 and p2["pbo"] < 0.05)
    p3 = {k: dict(spa_p=v["spa_p"], wrc_p=v["wrc_p"]) for k, v in ds["bench"].items()}
    p3["pass"] = bool(all(v["spa_p"] < 0.05 for v in ds["bench"].values()))
    p3["diag_vs_naive_vt_spa_p"] = float(hansen_spa(R.values, B["nvt"]["net"].values, n_boot=1000, rng=0)["p_value"])
    bst, bts, nvs = B["bst"], B["bts"], B["nvs"]
    p4 = dict(best=bst, btc=bts, naive=nvs, p4_by_impact={str(ik): res[ik]["p4"] for ik in IMPACT_KS}, pass_at_base=B["p4"])

    # ---- cost gate ----
    gate_rows = {}
    for ik in IMPACT_KS:
        r = res[ik]
        gate_rows[str(ik)] = dict(mult=ik / 0.5, best=r["best"], is_sharpe=r["bst"]["sharpe"], net_cagr=r["bst"]["cagr"],
                                  btc_sharpe=r["bts"]["sharpe"], btc_cagr=r["bts"]["cagr"], naive_sharpe=r["nvs"]["sharpe"],
                                  naive_cagr=r["nvs"]["cagr"], p4=r["p4"], dsr_p=r["ds"]["dsr"]["p_value"], pbo=r["ds"]["pbo"],
                                  spa_btc=r["ds"]["bench"]["BTC buy&hold"]["spa_p"], spa_naive=r["ds"]["bench"]["Naive EW (no selection)"]["spa_p"])
    invariant = len({v["p4"] for v in gate_rows.values()}) == 1
    best_changes = len({v["best"] for v in gate_rows.values()}) > 1
    gate = dict(rows=gate_rows, p4_invariant=invariant, best_config_changes=best_changes,
                label="cost-robust (p4 invariant)" if invariant else "COST-UNCONFIRMED")

    # ---- holdout: evaluate the ONE best config once (impact 0.5) ----
    log("holdout: weights on full ctx for best + benchmarks")
    Wbest_f = cached("full", best, lambda: build_W(full, GRID[best]), force)
    Wn_f = cached("full", "naive_eq", lambda: build_naive(full), force)
    cols_is = [full.cols.index(c) for c in isc.cols]
    n_is_bars = len(isc.idx)
    sub = Wbest_f.iloc[:n_is_bars].values
    leak = float(np.abs(sub[:, cols_is] - Wis[best].values).max())
    rest = np.delete(sub, cols_is, axis=1)
    leak_rest = float(np.abs(rest).max()) if rest.size else 0.0
    log(f"holdout-isolation check: max|W_full-W_IS| on IS rows = {leak:.2e}; weight on non-IS symbols in IS rows {leak_rest:.2e}")
    af = account(full, Wbest_f, 0.5)
    nf = account(full, Wn_f, 0.5)
    bf = account(full, build_btc(full), 0.5)
    ho = {}
    for nm, a in (("best", af), ("btc", bf), ("naive", nf)):
        ho[nm] = dict(ho=stats_of(a.loc[ho_dates]["net"].values), is_=stats_of(a.loc[is_dates]["net"].values),
                      carry_bps_yr_ho=float(a.loc[ho_dates]["carry"].mean() * 365 * 1e4),
                      price_pct_yr_ho=float(a.loc[ho_dates]["price"].mean() * 365),
                      carry_bps_yr_is=float(a.loc[is_dates]["carry"].mean() * 365 * 1e4))
    rh = af.loc[ho_dates]["net"].values
    ci_sh = block_bootstrap_ci(rh, sr_d, n_boot=1000, rng=0)
    ho["best"]["sharpe_ci_daily"] = [ci_sh["ci_low"] * math.sqrt(ANN), ci_sh["ci_high"] * math.sqrt(ANN)]
    ho["best"]["carry_nw_t"] = nw_t(af.loc[ho_dates]["carry"].values)
    same_sign = ho["best"]["ho"]["sharpe"] > 0 and ho["best"]["is_"]["sharpe"] > 0
    ho_beats = ho["best"]["ho"]["sharpe"] > ho["btc"]["ho"]["sharpe"] and ho["best"]["ho"]["sharpe"] > ho["naive"]["ho"]["sharpe"]
    ho_in_ci = ho["best"]["sharpe_ci_daily"][0] <= ho["best"]["is_"]["sharpe"] <= ho["best"]["sharpe_ci_daily"][1]
    ho["component_pass"] = bool(same_sign and ho_beats and ho["best"]["carry_bps_yr_ho"] > 0)
    ho["same_sign"], ho["beats_both"], ho["is_sharpe_within_ho_ci"] = bool(same_sign), bool(ho_beats), bool(ho_in_ci)
    log(f"HO best SR {ho['best']['ho']['sharpe']:.2f} (IS {ho['best']['is_']['sharpe']:.2f}) BTC {ho['btc']['ho']['sharpe']:.2f} naive {ho['naive']['ho']['sharpe']:.2f}")

    # ---- P6 tail ----
    daily_full = {"best": af["net"], "btc": bf["net"], "naive": nf["net"]}
    stress = {}
    for nm, (a, b) in STRESS.items():
        row = {}
        for who, s in daily_full.items():
            seg = s.loc[a:b].values
            row[who] = dict(maxdd=dd_stats(seg), cum_ret=float(np.prod(1 + seg) - 1), worst_day=float(seg.min()))
        row["best_expo"] = float(af["expo"].loc[a:b].mean())
        stress[nm] = row
    rb = accs[best]["net"].values
    idxb = stationary_bootstrap_indices(len(rb), 20, 1000, rng=1)
    L = 365
    bdd = np.array([dd_stats(rb[idxb[i][:L]]) for i in range(len(idxb))])
    btr = B["bt"]["net"].values
    bdd_btc = np.array([dd_stats(btr[idxb[i][:L]]) for i in range(len(idxb))])
    skew, exk = float(stats.skew(rb)), float(stats.kurtosis(rb, fisher=True))
    q01 = float(np.percentile(rb, 1)); es = float(rb[rb <= q01].mean()); sd = float(rb.std(ddof=1))
    tail = dict(stress=stress, boot_1y_maxdd_p5=float(np.percentile(bdd, 5)), boot_1y_maxdd_p1=float(np.percentile(bdd, 1)),
                boot_1y_maxdd_median=float(np.median(bdd)), btc_boot_1y_maxdd_p5=float(np.percentile(bdd_btc, 5)),
                skew=skew, excess_kurt=exk, worst_day=float(rb.min()), worst_day_sigmas=float(rb.min() / sd), es1=es,
                es1_sigmas=float(es / sd),
                carry_share_of_net=float(accs[best]["carry"].sum() / max(accs[best]["net"].sum(), 1e-12)),
                hidden_shortvol_flag=bool(skew < -1 or exk > 10))
    tail["stress_pass"] = bool(all(stress[k]["best"]["maxdd"] >= -DD_LIMIT for k in stress))
    tail["boot_pass"] = bool(tail["boot_1y_maxdd_p5"] >= -BOOT_DD_LIMIT)
    p6 = dict(**tail)
    p6["pass"] = bool(tail["stress_pass"] and tail["boot_pass"] and not tail["hidden_shortvol_flag"])

    # ---- P8 capacity + decay ----
    cap_rows = {}
    for cp_ in CAPS_USD:
        a = account(isc, Wis[best], 0.5, cp_).loc[is_dates]
        bn = account(isc, Wb_is, 0.5, cp_).loc[is_dates]
        nvv = account(isc, Wn_is, 0.5, cp_).loc[is_dates]
        s = stats_of(a["net"].values)
        cap_rows[str(int(cp_))] = dict(sharpe=s["sharpe"], cagr=s["cagr"], cost_pct_yr=float((a["fee"] + a["impact"]).mean() * 365),
                                       btc_sharpe=stats_of(bn["net"].values)["sharpe"], naive_sharpe=stats_of(nvv["net"].values)["sharpe"],
                                       naive_cagr=stats_of(nvv["net"].values)["cagr"], btc_cagr=stats_of(bn["net"].values)["cagr"])
    yrs = {}
    d_ret, d_car, d_nv = af["net"].loc[dates], af["carry"].loc[dates], nf["net"].loc[dates]
    fday = full.idx.floor("D")
    for y in sorted(set(dates.year)):
        m = dates.year == y
        r_ = d_ret.values[m]
        mm = (fday.year == y)
        fv_ = full.Ftot.values[mm][full.memb[mm]]
        agg_f = float(fv_.mean() * BPY * 1e4) if fv_.size else float("nan")
        yrs[int(y)] = dict(days=int(m.sum()), sharpe=sr_d(r_) * math.sqrt(ANN) if len(r_) > 5 else float("nan"),
                           carry_bps_yr=float(d_car.values[m].mean() * 365 * 1e4),
                           net_ret=float(np.prod(1 + r_) - 1), naive_ret=float(np.prod(1 + d_nv.values[m]) - 1),
                           member_mean_funding_bps_yr=agg_f)
    ys = sorted(yrs)
    rho_c = stats.spearmanr(ys, [yrs[y]["carry_bps_yr"] for y in ys])
    rho_f = stats.spearmanr(ys, [yrs[y]["member_mean_funding_bps_yr"] for y in ys])
    tb, c1 = cap_rows[str(int(TARGET_BOOK))], cap_rows[str(int(1e6))]
    cap_ok = bool(tb["sharpe"] >= 0.5 * c1["sharpe"] and tb["sharpe"] > max(tb["btc_sharpe"], tb["naive_sharpe"]))
    last2 = ys[-2:]
    decay_ok = bool(all(yrs[y]["net_ret"] > yrs[y]["naive_ret"] and yrs[y]["net_ret"] > 0 for y in last2))
    p8 = dict(capacity=cap_rows, target_book_usd=TARGET_BOOK, capacity_ok=cap_ok, by_year=yrs, decay_ok_last2y=decay_ok,
              spearman_year_vs_carry=[float(rho_c.statistic), float(rho_c.pvalue)],
              spearman_year_vs_member_funding=[float(rho_f.statistic), float(rho_f.pvalue)])
    p8["pass"] = bool(cap_ok and decay_ok)

    verdicts = {
        "1_who_pays": (p1["pass"], f"mean realized carry {p1['mean_bps_yr']:.0f} bps/yr, NW t={p1['nw_t']:.2f}, 95% CI [{p1['ci_lo_bps_yr']:.0f},{p1['ci_hi_bps_yr']:.0f}]"),
        "2_dsr_pbo": (p2["pass"], f"DSR={p2['dsr']:.3f} (p={p2['dsr_p']:.3f}), PBO={p2['pbo']:.3f}"),
        "3_spa": (p3["pass"], "SPA p: " + ", ".join(f"{k} {v['spa_p']:.3f}" for k, v in ds['bench'].items())),
        "4_net_vs_bench": (B["p4"], f"best SR {bst['sharpe']:.2f}/CAGR {pct(bst['cagr'])} vs BTC {bts['sharpe']:.2f}/{pct(bts['cagr'])}, naive {nvs['sharpe']:.2f}/{pct(nvs['cagr'])}; gate: {gate['label']}"),
        "5_holdout_paper": (None, f"holdout component {'PASS' if ho['component_pass'] else 'FAIL'} (HO SR {ho['best']['ho']['sharpe']:.2f} vs BTC {ho['btc']['ho']['sharpe']:.2f}, naive {ho['naive']['ho']['sharpe']:.2f}); paper pending"),
        "6_tail": (p6["pass"], f"LUNA DD {pct(stress['LUNA']['best']['maxdd'])}, FTX DD {pct(stress['FTX']['best']['maxdd'])}, boot-1y maxDD p5 {pct(tail['boot_1y_maxdd_p5'])}, skew {skew:.2f}, exkurt {exk:.1f}"),
        "7_bybit": (None, "pending (Bybit replication, cloud)"),
        "8_capacity": (p8["pass"], f"Sharpe 1M {c1['sharpe']:.2f} -> 5M {tb['sharpe']:.2f} -> 20M {cap_rows['20000000']['sharpe']:.2f}; last-2y beats naive: {decay_ok}"),
    }
    testable_all = all(v[0] is True for v in verdicts.values() if v[0] is not None) and ho["component_pass"]
    if not testable_all:
        overall = "NOT CONFIRMED"
    elif not invariant:
        overall = "COST-UNCONFIRMED (testable points pass; points 5 paper and 7 pending; p4 not invariant to impact_k)"
    else:
        overall = "COST-UNCONFIRMED (path (a) unavailable here; testable points pass; points 5 paper and 7 pending)"
    audit_checks = dict(holdout_leak_max_abs_dW=leak, holdout_leak_nonIS_symbols=leak_rest, n_trials=16, embargo=0.02, k=5,
                        holdout_frac=HOLDOUT_FRAC)

    out = dict(generated=time.strftime("%Y-%m-%d %H:%M:%S"),
               window=dict(start=str(dates[0].date()), end=str(dates[-1].date()), is_end=str(is_last.date()),
                           ho_start=str(ho_dates[0].date()), n_days=n, n_is=cut, n_ho=len(ho_dates)),
               coverage=coverage, configs=cfg_rows, benchmarks=bench_rows, best=best, best_oof=float(tab.loc[best, "oof_sharpe"]),
               verdicts={k: dict(status=("PASS" if v[0] is True else "FAIL" if v[0] is False else "pending"), number=v[1]) for k, v in verdicts.items()},
               p1=p1, p2=p2, p3=p3, p4=p4, cost_gate=gate, holdout=ho, p6=p6, p8=p8, overall=overall, audit_checks=audit_checks,
               assumptions=dict(target_vol=TARGET_VOL, band=BAND, cap=CAP, min_elig=MIN_ELIG, capital=CAPITAL, impact_k=0.5,
                                dd_limit=DD_LIMIT, boot_dd_limit=BOOT_DD_LIMIT, target_book=TARGET_BOOK))
    OUT.mkdir(exist_ok=True)
    (OUT / "carry.json").write_text(json.dumps(out, indent=1, default=str))
    write_md(out)
    log(f"done {time.time()-t0:.0f}s ; overall: {overall}")


def write_md(o):
    L = []
    A = L.append
    f2 = lambda x: f"{x:.2f}"
    A("# FORM-L funding-carry study (PREREG_CARRY.md, frozen)\n")
    A(f"Generated {o['generated']}. Long-only: BUY low/negative trailing funding among PIT-liquid members. 16 configs, n_trials=16. Window {o['window']['start']}..{o['window']['end']} "
      f"({o['window']['n_days']} d); IS ..{o['window']['is_end']} ({o['window']['n_is']} d), forward holdout from {o['window']['ho_start']} ({o['window']['n_ho']} d, last 20%).\n")
    A(f"## OVERALL: **{o['overall']}**\n")
    A("| # | Point | Status | Number |\n|---|---|---|---|")
    for k, v in o["verdicts"].items():
        A(f"| {k.split('_')[0]} | {k.split('_', 1)[1]} | **{v['status']}** | {v['number']} |")
    A("")
    c = o["coverage"]
    A("## Universe and coverage\n")
    A(f"PIT top-{N_UNIVERSE} by trailing-{RANK_WIN}d quote volume over all 689 USDT perps (incl. delisted), then intersected with the 77 symbols that have funding history. "
      f"Mean members/day {c['mean_members']:.1f}; mean members WITH funding {c['mean_funded']:.1f} ({pct(c['frac'])} of member-days; min {c['min_funded']}). "
      "Members without funding cannot be traded here (carry universe is a subset of the PIT majors; the 77 were selected partly with today's volume, a residual selection bias that cannot be removed without funding for the other 612).\n")
    A("| year | members/day | with funding/day | coverage |\n|---|---|---|---|")
    for y, v in c["by_year"].items():
        A(f"| {y} | {v['members']:.1f} | {v['funded']:.1f} | {pct(v['frac'])} |")
    A("\n## All 16 configs (IS, net of costs, impact_k=0.5, $1M)\n")
    A("OOF Sharpe = mean over purged 5-fold (embargo 2%). carry = realized funding cashflow (bps of equity/yr, + = received). price = arithmetic price P&L %/yr. cost = fees+impact %/yr.\n")
    A("| config | OOF SR | IS SR | net CAGR | maxDD | carry bps/yr | price %/yr | cost %/yr | turn/yr | gross expo |\n|---|---|---|---|---|---|---|---|---|---|")
    for k, v in o["configs"].items():
        mark = " **(best)**" if k == o["best"] else ""
        A(f"| {k}{mark} | {f2(v['oof_sharpe'])} | {f2(v['is_sharpe'])} | {pct(v['net_cagr'])} | {pct(v['maxdd'])} | {v['carry_bps_yr']:.0f} | {100*v['price_pct_yr']:.1f} | {100*v['cost_pct_yr']:.2f} | {v['turn_yr']:.1f} | {v['expo']:.2f} |")
    for k, v in o["benchmarks"].items():
        A(f"| BENCH {k} | - | {f2(v['is_sharpe'])} | {pct(v['net_cagr'])} | {pct(v['maxdd'])} | {v['carry_bps_yr']:.0f} | {100*v['price_pct_yr']:.1f} | {100*v['cost_pct_yr']:.2f} | {v['turn_yr']:.1f} | {v['expo']:.2f} |")
    p1, p2, p3 = o["p1"], o["p2"], o["p3"]
    A(f"\n## Decision rule, point by point (best config `{o['best']}` chosen by OOF Sharpe)\n")
    A(f"1. **Who pays**: mean realized funding cashflow {p1['mean_bps_yr']:.0f} bps/yr (NW t={p1['nw_t']:.2f}; bootstrap 95% CI [{p1['ci_lo_bps_yr']:.0f},{p1['ci_hi_bps_yr']:.0f}]) -> {'PASS' if p1['pass'] else 'FAIL'}. "
      f"Versus naive no-selection basket: {p1['vs_naive_bps_yr']:.0f} bps/yr (NW t={p1['vs_naive_nw_t']:.2f}). Carry per unit notional: strategy {p1['carry_pct_of_notional_yr']:.2f}%/yr vs naive {p1['naive_carry_pct_of_notional_yr']:.2f}%/yr (negative = longs pay).")
    A(f"2. **DSR/PBO**: DSR={p2['dsr']:.3f}, p={p2['dsr_p']:.3f} (deflated bench SR* {p2['sr_star']:.3f} daily), PBO={p2['pbo']:.3f} -> {'PASS' if p2['pass'] else 'FAIL'}.")
    A("3. **SPA** (all 16 configs vs benchmark): " + "; ".join(f"{k}: SPA p={v['spa_p']:.3f}, WRC p={v['wrc_p']:.3f}" for k, v in p3.items() if isinstance(v, dict))
      + f"; diagnostic vs vol-targeted naive: SPA p={p3['diag_vs_naive_vt_spa_p']:.3f} -> {'PASS' if p3['pass'] else 'FAIL'}.")
    p4 = o["p4"]
    A(f"4. **Net vs benchmarks** (IS, base costs): best SR {f2(p4['best']['sharpe'])}, CAGR {pct(p4['best']['cagr'])}, maxDD {pct(p4['best']['maxdd'])}; BTC {f2(p4['btc']['sharpe'])}/{pct(p4['btc']['cagr'])}/{pct(p4['btc']['maxdd'])}; naive {f2(p4['naive']['sharpe'])}/{pct(p4['naive']['cagr'])}/{pct(p4['naive']['maxdd'])} -> {'PASS' if p4['pass_at_base'] else 'FAIL'} (requires SR and CAGR above both).")
    h = o["holdout"]
    A(f"5. **Holdout + paper**: holdout component {'PASS' if h['component_pass'] else 'FAIL'}; paper-trade pending (forward) -> overall pending, NOT PASS.")
    p6 = o["p6"]
    A(f"6. **Tail**: see section below -> {'PASS' if p6['pass'] else 'FAIL'}.")
    A("7. **Bybit replication**: pending (cloud).")
    p8 = o["p8"]
    A(f"8. **Capacity**: see section below -> {'PASS' if p8['pass'] else 'FAIL'}.\n")
    g = o["cost_gate"]
    A("## Cost gate (impact_k sweep x0.25..x4 of 0.5)\n")
    A("Best config re-selected at each impact_k; point-4 requires best SR and CAGR above BTC and naive (IS).\n")
    A("| impact_k | best cfg | SR | CAGR | BTC SR/CAGR | naive SR/CAGR | P4 | DSR p | PBO | SPA BTC | SPA naive |\n|---|---|---|---|---|---|---|---|---|---|---|")
    for k, v in g["rows"].items():
        A(f"| {k} | {v['best']} | {f2(v['is_sharpe'])} | {pct(v['net_cagr'])} | {f2(v['btc_sharpe'])}/{pct(v['btc_cagr'])} | {f2(v['naive_sharpe'])}/{pct(v['naive_cagr'])} | {'PASS' if v['p4'] else 'FAIL'} | {v['dsr_p']:.3f} | {v['pbo']:.3f} | {v['spa_btc']:.3f} | {v['spa_naive']:.3f} |")
    A(f"\nPoint-4 invariant across all five: **{g['p4_invariant']}** -> label: **{g['label']}**. Best config changes with impact_k: {g['best_config_changes']}. Path (a) (real fills / paper) not available here. "
      "Note: 'cost-robust' only says the point-4 verdict does not depend on impact_k; if it is FAIL everywhere, the edge is simply not there.\n")
    A("## Holdout (best config evaluated once, impact_k=0.5)\n")
    A("| series | IS SR | IS CAGR | IS maxDD | HO SR | HO CAGR | HO maxDD | HO carry bps/yr | IS carry bps/yr |\n|---|---|---|---|---|---|---|---|---|")
    for nm in ("best", "btc", "naive"):
        v = h[nm]
        A(f"| {nm} | {f2(v['is_']['sharpe'])} | {pct(v['is_']['cagr'])} | {pct(v['is_']['maxdd'])} | {f2(v['ho']['sharpe'])} | {pct(v['ho']['cagr'])} | {pct(v['ho']['maxdd'])} | {v['carry_bps_yr_ho']:.0f} | {v['carry_bps_yr_is']:.0f} |")
    A(f"\nHO Sharpe 95% bootstrap CI [{h['best']['sharpe_ci_daily'][0]:.2f}, {h['best']['sharpe_ci_daily'][1]:.2f}]; HO carry NW t={h['best']['carry_nw_t']:.2f}. same-sign: {h['same_sign']}, beats both benchmarks: {h['beats_both']}, IS Sharpe inside HO CI: {h['is_sharpe_within_ho_ci']}.\n")
    A("## Tail (point 6)\n")
    A(f"A-priori limits (not in PREREG, fixed here): stress-window maxDD <= {pct(DD_LIMIT)}; 1y bootstrap 5th-pct maxDD >= -{pct(BOOT_DD_LIMIT)}; short-vol flag if skew < -1 or excess kurtosis > 10.\n")
    A("| window | series | maxDD | cum ret | worst day |\n|---|---|---|---|---|")
    for nm, v in p6["stress"].items():
        for who in ("best", "btc", "naive"):
            A(f"| {nm} | {who} | {pct(v[who]['maxdd'])} | {pct(v[who]['cum_ret'])} | {pct(v[who]['worst_day'])} |")
        A(f"| {nm} | best avg gross exposure | {v['best_expo']:.2f} | | |")
    A(f"\nBootstrap (stationary, 1y paths, 1000): maxDD median {pct(p6['boot_1y_maxdd_median'])}, 5th pct {pct(p6['boot_1y_maxdd_p5'])}, 1st pct {pct(p6['boot_1y_maxdd_p1'])} (BTC 5th pct {pct(p6['btc_boot_1y_maxdd_p5'])}). "
      f"Daily skew {p6['skew']:.2f}, excess kurtosis {p6['excess_kurt']:.1f}, worst day {pct(p6['worst_day'])} ({p6['worst_day_sigmas']:.1f} sigma), 1% ES {pct(p6['es1'])} ({p6['es1_sigmas']:.1f} sigma). "
      f"Carry share of net P&L {pct(p6['carry_share_of_net'])}. Hidden short-vol flag: **{p6['hidden_shortvol_flag']}**. This book is long-only price exposure, so its left tail is mostly directional beta, not a sold-straddle payoff; the carry share and benchmark comparison show how much of the result is carry versus beta.\n")
    A("## Capacity (point 8)\n")
    A(f"Impact = k*sqrt(trade/ADV30d), k=0.5; target book fixed a priori at ${TARGET_BOOK/1e6:.0f}M.\n")
    A("| book $ | SR | CAGR | cost %/yr | BTC SR | naive SR |\n|---|---|---|---|---|---|")
    for k, v in p8["capacity"].items():
        A(f"| {int(k)/1e6:g}M | {f2(v['sharpe'])} | {pct(v['cagr'])} | {100*v['cost_pct_yr']:.2f} | {f2(v['btc_sharpe'])} | {f2(v['naive_sharpe'])} |")
    A(f"\nCapacity prong (SR@5M >= 0.5*SR@1M and > both benchmarks at 5M): {p8['capacity_ok']}. Decay prong (last two years strategy return > 0 and > naive): {p8['decay_ok_last2y']}.\n")
    A("| year | days | SR | strategy carry bps/yr | strategy ret | naive ret | mean member funding bps/yr (paid by longs) |\n|---|---|---|---|---|---|---|")
    for y, v in p8["by_year"].items():
        A(f"| {y} | {v['days']} | {f2(v['sharpe'])} | {v['carry_bps_yr']:.0f} | {pct(v['net_ret'])} | {pct(v['naive_ret'])} | {v['member_mean_funding_bps_yr']:.0f} |")
    A(f"\nSpearman(year, strategy carry) = {p8['spearman_year_vs_carry'][0]:.2f} (p={p8['spearman_year_vs_carry'][1]:.2f}); Spearman(year, mean member funding) = {p8['spearman_year_vs_member_funding'][0]:.2f} (p={p8['spearman_year_vs_member_funding'][1]:.2f}). "
      "Falling member funding with a falling strategy edge would be consistent with an arbitrageable premium; a flat/rising edge would not.\n")
    A("## A-priori choices for underspecified items (fixed before results; not searched)\n")
    A("- Time base 8h bars aligned to funding (from 1h klines), results aggregated to UTC days (mech_runner stats, ANN=365). 8h rebalance = decide every bar; daily = decide at the 00:00 UTC bar only.\n"
      "- target_vol 0.20 via trailing-90-bar book vol, gross <= 1 (no leverage), cap 10%/coin applied after scaling (equal-weight quintile therefore holds ~ceil(0.2n)*10% gross; z-tilt weight ~ max(-z,0)).\n"
      "- No-trade band: skip per-coin changes with |target-held| <= 20% of max(target, held); entries/exits always trade. Min 10 eligible members else flat. Funding eligibility: >=80% of expected events in the window.\n"
      "- Costs: taker 4.5 bp + max(0.5 bp, k*sqrt(trade/ADV30d)) on |dW| at open, capital $1M (mech_runner convention). No borrow (long-only). costs.py participation cap not applied (mech_runner convention).\n"
      "- P6 limits and P8 target book: see Tail/Capacity sections.\n"
      "- Benchmarks: BTC buy&hold pays funding too; naive = all eligible PIT members equal weight (cap 10%), daily rebalance with same band, same costs, no selection. A vol-targeted naive is a diagnostic only.\n")
    A("## LOOKAHEAD SELF-AUDIT (carry-specific)\n")
    ac = o["audit_checks"]
    A("| Risk | Prevention |\n|---|---|")
    A("| Funding as-of timing | Decision for bar k (made at close of bar k-1 = open instant of bar k) uses only funding events with ts strictly < that instant: bins <= k-1 via `.shift(1)` after the rolling sum; the event stamped exactly at the instant is excluded. Timestamps rounded to the minute (ms jitter). |")
    A("| Trailing-window shift | Rolling 9/21 bins (3d/7d) computed on the event series then shifted by one bar; features never include bar k. Eligibility requires >=80% of expected events in the window (no zero-fill of missing history). Vol inputs use returns through bar k-1 (shifted). |")
    A("| Entry at open | Weight row k is traded at O_k: price P&L = W_{k-1}*(O_k/C_{k-1}-1) + W_k*(C_k/O_k-1); costs on |dW| at open using ADV shift(1). |")
    A("| Realized funding booking | Real funding events, not averages: events stamped exactly at bar open (settlement instant) are charged on the PRE-trade weight W_{k-1} (a same-instant trade cannot avoid or capture that payment); events inside the bar on W_k. Long pays when rate>0, receives when <0. |")
    A("| Universe ranking trailing | Daily top-30 by trailing-30d mean quote volume (rolling, row i uses days <= i), membership for bars of day D taken from the close of D-1; delisted symbols kept until delivery; ranked over all 689, then intersected with funded symbols. Not the selected.json ranking (today's volume). |")
    A(f"| Holdout isolation | A separate `Ctx(end=last IS day)` is built; all 16 configs, benchmarks, OOF, DSR/PBO/SPA, cost gate and capacity are computed on it. The full context is used only after `best` is fixed. Empirical check: max abs weight difference on IS rows between full and IS contexts = {ac['holdout_leak_max_abs_dW']:.2e} (weight on symbols absent from IS ctx: {ac['holdout_leak_nonIS_symbols']:.2e}). Residual: the cost gate re-selects `best` per impact_k; only the impact_k=0.5 best is evaluated on the holdout. |")
    A("| Embargo / CV | `purged_kfold(k=5, embargo=2%)` via mech_runner.oof_table on IS daily returns; best by mean OOF Sharpe; n_trials=16 in DSR and the PBO matrix has exactly the 16 configs. Rules have no fitted parameters, so purging only guards serial dependence. |")
    A("| Residual risks | (1) the 77 funded symbols were chosen with today's volume (survivor tilt; see coverage); (2) evaluation start uses a data-count fact, not performance; (3) no L2: impact is the k*sqrt placeholder (hence cost gate); (4) intra-holding weight drift ignored (constant-weight convention shared with mech_runner). |")
    (OUT / "carry.md").write_text("\n".join(L))


if __name__ == "__main__":
    main()
