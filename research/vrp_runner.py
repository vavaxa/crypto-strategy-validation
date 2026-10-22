"""VRP study. Frozen spec: research/PREREG_VRP.md. Measurement layer + short-variance-swap proxy.
Writes reports/vrp.{md,json}. Run: .venv/bin/python research/vrp_runner.py"""
from __future__ import annotations
import sys, json, math
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from research.overlay_runner import hac, stats_of, sr, boot_sr_diff   # same HAC/stat machinery
from research.validation.sharpe import deflated_sharpe_ratio, probabilistic_sharpe_ratio
from research.validation.bootstrap import stationary_bootstrap_indices

ANN = 365.0
H = 30
THR = 5.0          # vol points: conditional regime = DVOL - trailing30d RV > 5  (fixed a priori)
V0 = 0.005         # constant vega: 0.5% of equity per vol point (fixed a priori)
VT_TARGET = 0.10   # vol-target: 10% annualised on trailing 60d vol of the constant-vega book, shift(1)
VT_WIN = 60
VT_CAP = 2.0       # risk cap on scale
ROLL = 0.25        # roll/hedge friction, vol points per tranche entry (fixed a priori)
S_LIST = [1.0, 1.5, 2.0]; S_HEAD = 1.5
NTRIALS = 4
OUT = ROOT / "reports"
CONFIGS = [(r, z) for r in ("always", "cond") for z in ("constvega", "voltarget")]


def nw_mean(x, lag):
    x = np.asarray(x, float); x = x[~np.isnan(x)]; T = len(x); m = x.mean()
    S = float(hac(x[:, None], lag)[0, 0]); se = math.sqrt(S / T)
    return dict(mean=float(m), nw_se=se, nw_t=float(m / se) if se > 0 else float("nan"), n=T)


def load(sym, cur):
    d = pd.read_parquet(ROOT / "data/mech/spot_klines_1d_binance.parquet")
    d = d[d.symbol == sym].set_index("ts").sort_index()[["o", "h", "l", "c"]]
    d = d[d.index < pd.Timestamp.now(tz="UTC").normalize()]            # drop today's partial bar
    iv = pd.read_parquet(ROOT / f"data/mech/dvol_{cur}.parquet").set_index("ts").sort_index()
    iv = iv[iv.index < pd.Timestamp.now(tz="UTC").normalize()]
    df = d.join(iv["close"].rename("iv"), how="inner")
    df = df.reindex(pd.date_range(df.index[0], df.index[-1], freq="D", tz="UTC"))
    return df, int(df.iv.isna().sum())


def prep(df):
    df = df.copy()
    df["r"] = np.log(df.c / df.c.shift(1))
    df["gk"] = 0.5 * np.log(df.h / df.l) ** 2 - (2 * math.log(2) - 1) * np.log(df.c / df.o) ** 2
    df["r2"] = df.r ** 2
    return df


def fwd_rv(df, h, kind="cc"):
    """RV over returns t+1..t+h (close t -> close t+h). Uses FUTURE data: measurement only, never a signal."""
    if kind == "cc":
        sd = df.r.rolling(h).std().shift(-h)       # window t+1..t+h
    else:
        sd = np.sqrt(df.gk.rolling(h).mean().shift(-h))
    return sd * math.sqrt(ANN) * 100


def trail_rv(df, h=30):
    return df.r.rolling(h).std() * math.sqrt(ANN) * 100          # returns t-h+1..t : as-of t


# ------------------------------------------------------------------ measurement layer
def measure(df, h=30, kind="cc"):
    rv = fwd_rv(df, h, kind); vrp = df.iv - rv; vv = df.iv ** 2 - rv ** 2
    m = vrp.dropna(); out = dict(h=h, rv=kind, n=len(m), start=str(m.index[0].date()), end=str(m.index[-1].date()))
    out.update(nw_mean(m.values, h))
    out["hit_rate"] = float((m > 0).mean()); out["median"] = float(m.median())
    out["mean_iv"] = float(df.iv.loc[m.index].mean()); out["mean_rv"] = float(rv.loc[m.index].mean())
    out["var_terms_mean"] = float(vv.dropna().mean()); out["var_terms_median"] = float(vv.dropna().median())
    out["var_terms_nw_t"] = nw_mean(vv.dropna().values, h)["nw_t"]
    out["skew"] = float(stats.skew(m)); out["kurt_excess"] = float(stats.kurtosis(m))
    nov = m.iloc[::h]; out["nonoverlap"] = dict(n=len(nov), mean=float(nov.mean()), t=float(nov.mean() / (nov.std(ddof=1) / math.sqrt(len(nov)))), hit=float((nov > 0).mean()))
    out["by_year"] = {}
    for y, g in m.groupby(m.index.year):
        if len(g) >= 30:
            q = nw_mean(g.values, h); out["by_year"][int(y)] = dict(n=len(g), mean=q["mean"], nw_t=q["nw_t"], hit=float((g > 0).mean()))
    half = len(m) // 2
    out["halves"] = {k: dict(mean=float(g.mean()), nw_t=nw_mean(g.values, h)["nw_t"], hit=float((g > 0).mean())) for k, g in (("first", m.iloc[:half]), ("second", m.iloc[half:]))}
    # left tail
    def win(a, b):
        g = m.loc[a:b]; w = g.idxmin()
        return dict(window=f"{a}..{b}", worst_entry=str(w.date()), min_vrp=float(g.min()), iv_at=float(df.iv[w]), rv_fwd=float(rv[w]),
                    var_vrp_min=float(vv[w]), mean_vrp=float(g.mean()))
    out["LUNA"] = win("2022-04-15", "2022-05-31"); out["FTX"] = win("2022-10-15", "2022-11-30")
    # worst spikes: greedy, separated by >=30 days
    s = m.sort_values(); picked = []
    for t, v in s.items():
        if all(abs((t - p).days) >= 30 for p, _ in picked): picked.append((t, v))
        if len(picked) == 6: break
    out["worst_windows"] = [dict(entry=str(t.date()), vrp=float(v), iv=float(df.iv[t]), rv_fwd=float(rv[t]), var_vrp=float(vv[t])) for t, v in picked]
    out["pct"] = {p: float(np.percentile(m, p)) for p in (1, 5, 25, 50, 75, 95)}
    return out


# ------------------------------------------------------------------ strategy proxy
def run_config(df, regime, sizing, s, roll, rv_kind="cc"):
    tr = trail_rv(df, 30)
    if regime == "always": sig = pd.Series(1.0, index=df.index)
    else: sig = ((df.iv - tr) > THR).astype(float).where(tr.notna(), 0.0)
    # tranche daily accrual: (K^2 - x_u)/(2K*h) per tranche-unit, weight 1/h each -> multiply to total vega 1 when book is full
    x2 = (df.r2 if rv_kind == "cc" else df.gk) * ANN * 1e4
    K = (df.iv - s - roll).values; n = len(df); x2v = x2.values; sg = sig.values
    pnl = np.zeros(n)
    for t in range(n):
        if sg[t] == 0 or np.isnan(K[t]): continue
        hi = min(n, t + 1 + H)
        pnl[t + 1:hi] += sg[t] * (K[t] ** 2 - x2v[t + 1:hi]) / (2 * K[t]) / H / H
    pnl = pd.Series(pnl, index=df.index)          # vol pts per unit total vega; full book of 30 tranches => monthly ~ (K - RV)
    ret = V0 * pnl                                # equity return per day, constant vega
    if sizing == "voltarget":
        vol = ret.rolling(VT_WIN).std().shift(1) * math.sqrt(ANN)   # trailing, shift(1)
        # scale uses the s=0 independent book? -> use the same-config ret (headline) trailing vol; fixed a priori
        scale = (VT_TARGET / vol).clip(upper=VT_CAP)
        ret = ret * scale
    return ret, sig


def run_config_vt(df, regime, s, roll, rv_kind="cc"):
    """vol-target scale is computed from the gross (s=0) book of the same regime so cost levels do not change sizing."""
    ret_g, sig = run_config(df, regime, "constvega", 0.0, 0.0, rv_kind)
    vol = ret_g.rolling(VT_WIN).std().shift(1) * math.sqrt(ANN)
    scale = (VT_TARGET / vol).clip(upper=VT_CAP)
    ret_n, _ = run_config(df, regime, "constvega", s, roll, rv_kind)
    return ret_n * scale, sig


def book(df, regime, sizing, s, roll, rv_kind="cc"):
    if sizing == "constvega": return run_config(df, regime, "constvega", s, roll, rv_kind)[0]
    return run_config_vt(df, regime, s, roll, rv_kind)[0]


def eval_index(df):
    first_iv = df.iv.first_valid_index()
    start = first_iv + pd.Timedelta(days=VT_WIN + H + 5)       # warmup: trailing RV 30d, vt window 60d, tranches full
    end = df.r.dropna().index[-1]
    return df.index[(df.index >= start) & (df.index <= end)]


def strat_stats(r, label, ntr=NTRIALS):
    r = np.asarray(r, float); st = stats_of(r)
    sk, ku = float(stats.skew(r)), float(stats.kurtosis(r, fisher=False))
    d = deflated_sharpe_ratio(st["sharpe"] / math.sqrt(ANN), ntr, len(r), skew=sk, kurt=ku)       # per-period SR, daily T
    m = nw_mean(r, 30)
    # non-overlapping 30d sums
    nm = len(r) // H; mo = r[:nm * H].reshape(nm, H).sum(1)
    sk_m, ku_m = float(stats.skew(mo)), float(stats.kurtosis(mo, fisher=False)); srm = mo.mean() / mo.std(ddof=1)
    dm = deflated_sharpe_ratio(float(srm), ntr, nm, skew=sk_m, kurt=ku_m)
    st.update(dict(label=label, skew=sk, kurt=ku, mean_daily=m["mean"], nw_t_mean=m["nw_t"], dsr_daily=d["dsr"], psr_daily=d["psr"],
                   monthly=dict(n=nm, mean=float(mo.mean()), sharpe_ann=float(srm * math.sqrt(12)), t=float(mo.mean() / (mo.std(ddof=1) / math.sqrt(nm))),
                                dsr=dm["dsr"], psr=dm["psr"], hit=float((mo > 0).mean()), worst=float(mo.min()), best=float(mo.max()),
                                skew=sk_m, kurt=ku_m, worst_over_mean=float(mo.min() / mo.mean()) if mo.mean() != 0 else None)))
    sd = r.std(ddof=1); st["worst_day_sigma"] = float((r.min() - r.mean()) / sd) if sd > 0 else None
    st["worst_day"] = float(r.min())
    return st


def dd_in(r, a, b):
    g = r.loc[a:b]
    if len(g) == 0: return None
    eq = (1 + g).cumprod(); pk = np.maximum.accumulate(np.r_[1.0, eq.values])[1:]
    return dict(window=f"{a}..{b}", pnl_sum=float(g.sum()), max_dd_in_window=float((eq.values / pk - 1).min()), worst_day=float(g.min()))


def tail_char(r, df):
    eq = (1 + r).cumprod(); dd = eq / eq.cummax() - 1
    # worst rolling 30d sum
    w30 = r.rolling(30).sum(); t = w30.idxmin()
    return dict(LUNA=dd_in(r, "2022-05-01", "2022-06-30"), FTX=dd_in(r, "2022-11-01", "2022-12-31"),
                worst_30d_window=dict(end=str(t.date()), sum=float(w30.min())), maxdd=float(dd.min()), maxdd_date=str(dd.idxmin().date()),
                total_gain=float(r[r > 0].sum()), total_loss=float(r[r < 0].sum()),
                gains_erased_by_worst_30d=float(-w30.min() / r.sum()) if r.sum() > 0 else None,
                cum_final=float(eq.iloc[-1]))


def btc_link(r, btc):
    b = btc.reindex(r.index); ok = b.notna()
    r, b = r[ok], b[ok]
    out = dict(corr_daily=float(r.corr(b)), corr_down_days=float(r[b < 0].corr(b[b < 0])))
    beta = np.cov(r, b)[0, 1] / b.var(); out["beta"] = float(beta)
    out["mean_ret_on_btc_down_days"] = float(r[b < 0].mean()); out["mean_ret_on_btc_up_days"] = float(r[b > 0].mean())
    for th in (-0.03, -0.05, -0.10):
        g = r[b <= th]; out[f"btc_le_{int(th*100)}pct"] = dict(n=int(len(g)), mean=float(g.mean()) if len(g) else None, sum=float(g.sum()) if len(g) else None, hit=float((g > 0).mean()) if len(g) else None)
    # monthly
    nm = len(r) // H; rm = r.values[:nm * H].reshape(nm, H).sum(1); bm = np.log(1 + b.values[:nm * H]).reshape(nm, H).sum(1)
    out["corr_monthly"] = float(np.corrcoef(rm, bm)[0, 1])
    dn = bm < 0; out["monthly_btc_down"] = dict(n=int(dn.sum()), mean_strat=float(rm[dn].mean()), hit=float((rm[dn] > 0).mean()))
    out["monthly_btc_up"] = dict(n=int((~dn).sum()), mean_strat=float(rm[~dn].mean()), hit=float((rm[~dn] > 0).mean()))
    q = np.quantile(bm, 0.2); lo = bm <= q; out["monthly_btc_worst20pct"] = dict(n=int(lo.sum()), mean_strat=float(rm[lo].mean()), hit=float((rm[lo] > 0).mean()))
    return out


def full_study(df, tag):
    ev = eval_index(df); n = len(ev); is_end = ev[int(n * 0.8) - 1]
    ev_is, ev_ho = ev[ev <= is_end], ev[ev > is_end]
    res = dict(tag=tag, eval=f"{ev[0].date()}..{ev[-1].date()}", n=n, is_end=str(is_end.date()), n_is=len(ev_is), n_ho=len(ev_ho))
    btc = df.c.pct_change()
    books = {}
    for reg, sz in CONFIGS:
        nm = f"{reg}|{sz}"
        books[nm] = {s: book(df, reg, sz, s, ROLL).loc[ev] for s in [0.0] + S_LIST}
        books[nm]["gk"] = book(df, reg, sz, S_HEAD, ROLL, "gk").loc[ev]
    res["configs"] = {}
    for nm, bk in books.items():
        rr = bk[S_HEAD]; g = bk[0.0]
        c = dict(gross=strat_stats(g.values, nm + " gross"), net=strat_stats(rr.values, nm + f" net s={S_HEAD}"))
        c["net_is"] = strat_stats(rr.loc[ev_is].values, nm + " IS"); c["net_ho"] = strat_stats(rr.loc[ev_ho].values, nm + " HO")
        c["cost_gate"] = {str(s): dict(mean_daily=float(bk[s].mean()), ann_ret=float(bk[s].mean() * ANN), sharpe=sr(bk[s].values), nw_t=nw_mean(bk[s].values, 30)["nw_t"]) for s in S_LIST}
        c["cost_gate"]["gross_s0"] = dict(mean_daily=float(g.mean()), ann_ret=float(g.mean() * ANN), sharpe=sr(g.values), nw_t=nw_mean(g.values, 30)["nw_t"])
        signs = {np.sign(bk[s].mean()) for s in S_LIST}; c["sign_flip_across_s"] = len(signs) > 1
        # breakeven s (cost where mean pnl = 0) via linear interpolation over a wide scan
        ss = np.arange(0, 12.1, 1.0); ms = [book(df, *nm.split("|"), s, ROLL).loc[ev].mean() for s in ss]
        be = None
        for i in range(1, len(ss)):
            if ms[i - 1] > 0 >= ms[i]: be = float(ss[i - 1] + ms[i - 1] / (ms[i - 1] - ms[i]) * (ss[i] - ss[i - 1])); break
        c["breakeven_s"] = be
        c["gk_net"] = strat_stats(bk["gk"].values, nm + " GK net")
        c["tail"] = tail_char(rr, df); c["btc"] = btc_link(rr, btc)
        res["configs"][nm] = c
    # selection on IS only (headline net s)
    isbest = max(books, key=lambda k: sr(books[k][S_HEAD].loc[ev_is].values)); res["best_is"] = isbest
    res["is_sharpes"] = {k: sr(books[k][S_HEAD].loc[ev_is].values) for k in books}
    res["ho_sharpes"] = {k: sr(books[k][S_HEAD].loc[ev_ho].values) for k in books}
    res["_books"] = books
    return res


def main():
    OUT.mkdir(exist_ok=True)
    out = {}
    dfb, gapb = load("BTCUSDT", "btc"); dfb = prep(dfb)
    dfe, gape = load("ETHUSDT", "eth"); dfe = prep(dfe)
    dv = pd.read_parquet(ROOT / "data/mech/dvol_btc.parquet")
    out["coverage"] = dict(btc_dvol_rows=len(dv), btc_range=f"{dv.ts.min().date()}..{dv.ts.max().date()}", btc_close_min=float(dv.close.min()), btc_close_max=float(dv.close.max()),
                           btc_missing_days_after_join=gapb, eth_dvol_rows=len(pd.read_parquet(ROOT / 'data/mech/dvol_eth.parquet')), eth_missing_days=gape,
                           sanity_in_10_200=bool(dv.close.between(10, 200).all()), spot_last_used=str(dfb.index[-1].date()))
    meas = {}
    for nm, df in (("BTC", dfb), ("ETH", dfe)):
        meas[nm] = {"h30_cc": measure(df, 30, "cc"), "h30_gk": measure(df, 30, "gk"), "h7_cc": measure(df, 7, "cc")}
    out["measurement"] = meas
    sb = full_study(dfb, "BTC"); se = full_study(dfe, "ETH")
    # ETH replication: same four configs (no re-selection)
    out["strategy"] = {"BTC": {k: v for k, v in sb.items() if k != "_books"}, "ETH": {k: v for k, v in se.items() if k != "_books"}}
    # paired bootstrap of best vs zero: stationary bootstrap CI for annualised net mean (best IS config)
    b = sb["best_is"]; r = sb["_books"][b][S_HEAD].values
    idx = stationary_bootstrap_indices(len(r), 30, 2000, rng=0); bm = np.array([r[i].mean() * ANN for i in idx])
    out["strategy"]["BTC"]["boot_best_ann_ret_ci95"] = [float(np.percentile(bm, 2.5)), float(np.percentile(bm, 97.5))]
    # lookahead self-audit: perturb future (shuffle post-t returns of tranche) -> check signal independent of future
    df2 = dfb.copy(); cut = df2.index[1500]; rng = np.random.default_rng(0)
    df2.loc[df2.index > cut, ["o", "h", "l", "c"]] = df2.loc[df2.index > cut, ["o", "h", "l", "c"]].values[::-1]
    df2 = prep(df2)
    tr1, tr2 = trail_rv(dfb), trail_rv(df2)
    sig_a = ((dfb.iv - tr1) > THR).loc[:cut]; sig_b = ((df2.iv - tr2) > THR).loc[:cut]
    out["audit"] = dict(signal_unchanged_when_future_prices_scrambled=bool((sig_a == sig_b).all()), cut=str(cut.date()))
    ev = eval_index(dfb); r_a = book(dfb, "always", "constvega", 1.5, ROLL).loc[:cut]; r_b = book(df2, "always", "constvega", 1.5, ROLL).loc[:cut]
    # pnl up to cut must change only through returns <= cut, i.e. prefix identical
    out["audit"]["book_prefix_unchanged_when_future_scrambled"] = bool(np.allclose(r_a.fillna(0).values, r_b.fillna(0).values))
    vt_a = book(dfb, "always", "voltarget", 1.5, ROLL).loc[:cut]; vt_b = book(df2, "always", "voltarget", 1.5, ROLL).loc[:cut]
    out["audit"]["voltarget_prefix_unchanged"] = bool(np.allclose(vt_a.fillna(0).values, vt_b.fillna(0).values))
    out["decision"] = decide(out, sb, se)
    json.dump(out, open(OUT / "vrp.json", "w"), indent=1, default=lambda o: None if (isinstance(o, float) and math.isnan(o)) else str(o))
    write_md(out)
    print("done")


def decide(out, sb, se):
    D = {}
    m = out["measurement"]["BTC"]["h30_cc"]
    yrs = m["by_year"]; pos_years = sum(1 for v in yrs.values() if v["mean"] > 0)
    D["1_premium"] = dict(verdict="PASS" if (m["mean"] > 0 and m["nw_t"] > 2 and pos_years == len(yrs)) else ("PARTIAL" if m["mean"] > 0 and m["nw_t"] > 2 else "FAIL"),
                          mean=m["mean"], nw_t=m["nw_t"], hit=m["hit_rate"], years_positive=f"{pos_years}/{len(yrs)}", halves=m["halves"])
    best = sb["best_is"]; c = sb["configs"][best]
    allc = sb["configs"]
    d2 = dict(best_is=best, net_ann_ret=c["net"]["ann_ret"], net_sharpe=c["net"]["sharpe"], nw_t=c["net"]["nw_t_mean"],
              dsr_daily=c["net"]["dsr_daily"], dsr_monthly=c["net"]["monthly"]["dsr"], sign_flip=c["sign_flip_across_s"], breakeven_s=c["breakeven_s"],
              all_net_positive=[k for k, v in allc.items() if v["net"]["mean_daily"] > 0])
    ok = c["net"]["mean_daily"] > 0 and c["net"]["monthly"]["dsr"] > 0.95 and c["net"]["dsr_daily"] > 0.95 and not c["sign_flip_across_s"]
    d2["verdict"] = "PASS" if ok else ("cost-unconfirmed" if c["sign_flip_across_s"] else "FAIL")
    D["2_net_pnl"] = d2
    t = c["tail"]; mo = c["net"]["monthly"]
    ruin = (c["net"]["skew"] < -1 or c["net"]["kurt"] > 10) 
    D["3_tail"] = dict(verdict="FAIL (insurance-selling tail)" if ruin else "bounded?", skew=c["net"]["skew"], kurt=c["net"]["kurt"], worst_day_sigma=c["net"]["worst_day_sigma"],
                       maxdd=t["maxdd"], LUNA=t["LUNA"], FTX=t["FTX"], worst_30d=t["worst_30d_window"], monthly_worst_over_mean=mo["worst_over_mean"], gains_erased=t["gains_erased_by_worst_30d"])
    bt = c["btc"]
    D["4_btc_corr"] = dict(verdict="NOT a diversifier (loses in BTC crashes)" if (bt["corr_down_days"] > 0.3 or bt["btc_le_-5pct"]["sum"] < 0 or bt["monthly_btc_worst20pct"]["mean_strat"] < 0) else "uncorrelated", btc_le_5pct_sum=bt["btc_le_-5pct"]["sum"], btc_le_10pct_sum=bt["btc_le_-10pct"]["sum"], worst20_months_mean=bt["monthly_btc_worst20pct"]["mean_strat"], **{k: bt[k] for k in ("corr_daily", "corr_monthly", "corr_down_days", "beta", "mean_ret_on_btc_down_days", "mean_ret_on_btc_up_days")})
    ho = c["net_ho"]; eb = se["configs"][best]
    D["5_holdout_eth"] = dict(holdout_sharpe=ho["sharpe"], holdout_mean_daily=ho["mean_daily"], holdout_same_sign=ho["mean_daily"] > 0 and c["net"]["mean_daily"] > 0,
                              eth_net_sharpe=eb["net"]["sharpe"], eth_net_ann_ret=eb["net"]["ann_ret"], eth_dsr_monthly=eb["net"]["monthly"]["dsr"], live_forward="PENDING",
                              verdict="PENDING (live/forward required; tail not confirmable)")
    D["6_robust"] = dict(cost_gate_sign_flip=c["sign_flip_across_s"], gk_net_sharpe=c["gk_net"]["sharpe"], gk_net_ann_ret=c["gk_net"]["ann_ret"], cc_net_sharpe=c["net"]["sharpe"],
                         verdict="PASS" if (not c["sign_flip_across_s"] and c["gk_net"]["mean_daily"] > 0) else "FAIL")
    allpass = D["1_premium"]["verdict"] == "PASS" and D["2_net_pnl"]["verdict"] == "PASS" and not D["3_tail"]["verdict"].startswith("FAIL") and D["4_btc_corr"]["verdict"] == "uncorrelated" and D["6_robust"]["verdict"] == "PASS"
    D["overall"] = "VRP-edge CONFIRMED (pending live)" if allpass else "NOT CONFIRMED as tradeable edge"
    return D


def f(x, p=2):
    return "n/a" if x is None else (f"{x:.{p}f}" if isinstance(x, (int, float)) else str(x))


def write_md(o):
    L = []; a = L.append
    cv = o["coverage"]; mb = o["measurement"]["BTC"]; me = o["measurement"]["ETH"]; D = o["decision"]
    a("# VRP study (prereg: research/PREREG_VRP.md)\n")
    a(f"**Overall: {D['overall']}**\n")
    a("## Coverage"); a(f"- DVOL BTC {cv['btc_range']}, {cv['btc_dvol_rows']} rows, close range {cv['btc_close_min']}..{cv['btc_close_max']} (all in 10..200: {cv['sanity_in_10_200']}); ETH rows {cv['eth_dvol_rows']}. Missing days after join with spot: BTC {cv['btc_missing_days_after_join']}, ETH {cv['eth_missing_days']}. Last spot day used {cv['spot_last_used']} (today's partial bar dropped).\n")
    a("## 1. Measurement: VRP = DVOL - forward RV (vol points)")
    a("| asset/spec | n | mean | NW t | hit IV>RV | median | mean IV | mean RV | var-terms mean (IV^2-RV^2) | var NW t | non-overlap mean / t / hit | skew | exc.kurt |"); a("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for asset, M in (("BTC", mb), ("ETH", me)):
        for k, v in M.items():
            no = v["nonoverlap"]
            a(f"| {asset} {k} | {v['n']} | {f(v['mean'])} | {f(v['nw_t'])} | {f(v['hit_rate'],3)} | {f(v['median'])} | {f(v['mean_iv'])} | {f(v['mean_rv'])} | {f(v['var_terms_mean'],0)} | {f(v['var_terms_nw_t'])} | {f(no['mean'])} / {f(no['t'])} / {f(no['hit'],2)} (n={no['n']}) | {f(v['skew'])} | {f(v['kurt_excess'])} |")
    for asset, M in (("BTC", mb), ("ETH", me)):
        a(f"\n{asset} by year (h30 cc): " + "; ".join(f"{y}: mean {f(v['mean'])}, NW t {f(v['nw_t'])}, hit {f(v['hit'],2)}, n={v['n']}" for y, v in M["h30_cc"]["by_year"].items()))
        a(f"{asset} halves: " + "; ".join(f"{k}: mean {f(v['mean'])}, t {f(v['nw_t'])}, hit {f(v['hit'],2)}" for k, v in M["h30_cc"]["halves"].items()))
        a(f"{asset} VRP percentiles: {M['h30_cc']['pct']}")
    a("\n### Left tail (BTC, h30 cc)")
    for k in ("LUNA", "FTX"):
        v = mb["h30_cc"][k]; a(f"- {k} {v['window']}: worst entry {v['worst_entry']}, VRP {f(v['min_vrp'])} (IV {f(v['iv_at'])}, fwd RV {f(v['rv_fwd'])}), var-terms {f(v['var_vrp_min'],0)}; window mean VRP {f(v['mean_vrp'])}")
    a("- Worst 30d windows (separated >=30d): " + "; ".join(f"{w['entry']}: VRP {f(w['vrp'])} (IV {f(w['iv'])} vs RV {f(w['rv_fwd'])}; var {f(w['var_vrp'],0)})" for w in mb["h30_cc"]["worst_windows"]))
    a("\n## 2. Strategy proxy: short 30d variance swap, daily tranches (BTC)")
    S = o["strategy"]["BTC"]; a(f"Eval {S['eval']} (n={S['n']} days), IS ..{S['is_end']} (n={S['n_is']}), holdout n={S['n_ho']}. Best on IS (net s=1.5): **{S['best_is']}**. V0={V0} equity per vol pt, vol-target {VT_TARGET} cap {VT_CAP}, thr {THR}, roll {ROLL} vol pt.\n")
    a("| config | gross ann ret | gross Sharpe | net ann ret (s=1.5) | net Sharpe | NW t | maxDD | skew | kurt | DSR daily | DSR monthly | monthly Sharpe | monthly hit | breakeven s |"); a("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for k, c in S["configs"].items():
        g, n = c["gross"], c["net"]
        a(f"| {k} | {f(g['ann_ret'],3)} | {f(g['sharpe'])} | {f(n['ann_ret'],3)} | {f(n['sharpe'])} | {f(n['nw_t_mean'])} | {f(n['maxdd'],3)} | {f(n['skew'])} | {f(n['kurt'],1)} | {f(n['dsr_daily'],3)} | {f(n['monthly']['dsr'],3)} | {f(n['monthly']['sharpe_ann'])} | {f(n['monthly']['hit'],2)} | {f(c['breakeven_s'])} |")
    a("\nIS/holdout Sharpe (net s=1.5): " + "; ".join(f"{k}: IS {f(S['is_sharpes'][k])} / HO {f(S['ho_sharpes'][k])}" for k in S["is_sharpes"]))
    a("\n### Cost gate (net ann return / Sharpe / NW t by s)")
    a("| config | gross s=0 | s=1.0 | s=1.5 | s=2.0 | sign flip? |"); a("|---|---|---|---|---|---|")
    for k, c in S["configs"].items():
        cg = c["cost_gate"]; cell = lambda v: f"{f(v['ann_ret'],3)} / {f(v['sharpe'])} / t{f(v['nw_t'])}"
        a(f"| {k} | {cell(cg['gross_s0'])} | {cell(cg['1.0'])} | {cell(cg['1.5'])} | {cell(cg['2.0'])} | {'YES -> cost-unconfirmed' if c['sign_flip_across_s'] else 'no'} |")
    a(f"\nBootstrap 95% CI of best-IS config net annual return: {S['boot_best_ann_ret_ci95']}")
    a("\n### Tail characterization")
    for k, c in S["configs"].items():
        t = c["tail"]; n = c["net"]; mo = n["monthly"]
        a(f"- {k}: skew {f(n['skew'])}, kurt {f(n['kurt'],1)}, worst day {f(n['worst_day'],4)} = {f(n['worst_day_sigma'])} sigma; maxDD {f(t['maxdd'],3)} ({t['maxdd_date']}); worst 30d sum {f(t['worst_30d_window']['sum'],3)} (ending {t['worst_30d_window']['end']}) = {f(t['gains_erased_by_worst_30d'],2)}x of total net gain; monthly worst {f(mo['worst'],3)} vs mean {f(mo['mean'],4)}; monthly skew {f(mo['skew'])}; LUNA(May-Jun22) pnl {f(t['LUNA']['pnl_sum'],3)} maxDD-in-window {f(t['LUNA']['max_dd_in_window'],3)}; FTX(Nov-Dec22) pnl {f(t['FTX']['pnl_sum'],3)} maxDD-in-window {f(t['FTX']['max_dd_in_window'],3)}")
    a("\n### BTC correlation and down-day behaviour (net s=1.5)")
    for k, c in S["configs"].items():
        b = c["btc"]
        a(f"- {k}: corr daily {f(b['corr_daily'])}, down-days corr {f(b['corr_down_days'])}, monthly corr {f(b['corr_monthly'])}, beta {f(b['beta'],4)}; mean ret BTC-down days {f(b['mean_ret_on_btc_down_days'],5)} vs up days {f(b['mean_ret_on_btc_up_days'],5)}; BTC<=-5% days n={b['btc_le_-5pct']['n']} mean {f(b['btc_le_-5pct']['mean'],4)} sum {f(b['btc_le_-5pct']['sum'],3)}; BTC<=-10%: n={b['btc_le_-10pct']['n']} sum {f(b['btc_le_-10pct']['sum'],3)}; months BTC down: n={b['monthly_btc_down']['n']} mean {f(b['monthly_btc_down']['mean_strat'],4)} hit {f(b['monthly_btc_down']['hit'],2)}; BTC-up months mean {f(b['monthly_btc_up']['mean_strat'],4)}; worst-20% BTC months mean {f(b['monthly_btc_worst20pct']['mean_strat'],4)} hit {f(b['monthly_btc_worst20pct']['hit'],2)}")
    a("\n## 5. Holdout (last 20%, supporting) and ETH replication (same 4 configs, no re-selection)")
    for k, c in S["configs"].items():
        ho = c["net_ho"]; e = o["strategy"]["ETH"]["configs"][k]
        a(f"- {k}: BTC HO ann ret {f(ho['ann_ret'],3)}, Sharpe {f(ho['sharpe'])}, maxDD {f(ho['maxdd'],3)} | ETH full net ann ret {f(e['net']['ann_ret'],3)}, Sharpe {f(e['net']['sharpe'])}, maxDD {f(e['net']['maxdd'],3)}, DSR monthly {f(e['net']['monthly']['dsr'],3)}, skew {f(e['net']['skew'])}, sign flip across s: {e['sign_flip_across_s']}; ETH HO Sharpe {f(e['net_ho']['sharpe'])}")
    a("\n## 6. RV-estimator robustness (GK vs close-to-close, net s=1.5, BTC)")
    for k, c in S["configs"].items():
        a(f"- {k}: cc ann ret {f(c['net']['ann_ret'],3)} / Sharpe {f(c['net']['sharpe'])}; GK ann ret {f(c['gk_net']['ann_ret'],3)} / Sharpe {f(c['gk_net']['sharpe'])}")
    a("\n## Decision rule (6 points)")
    for k, v in D.items():
        if k != "overall": a(f"- **{k}**: `{json.dumps(v, default=str)}`")
    au = o["audit"]
    a("\n## Lookahead self-audit")
    a(f"- Forward RV (`fwd_rv`) used ONLY in the measurement layer (VRP_t); the strategy never reads it. Strategy tranche entered at close t using IV_t and trailing RV (returns <= t); accrues returns from t+1 (equivalent of shift(1)); vol-target scale uses trailing 60d std shifted by 1.")
    a(f"- Scramble test (reverse all prices after {au['cut']}): signal unchanged for t<=cut: {au['signal_unchanged_when_future_prices_scrambled']}; always|constvega book prefix unchanged: {au['book_prefix_unchanged_when_future_scrambled']}; vol-target prefix unchanged: {au['voltarget_prefix_unchanged']}. (Prefix includes pnl on days <= cut only from returns <= cut, hence unchanged.)")
    a("- Overlap: 30d windows overlap -> NW HAC lag = 30 on all means; non-overlapping 30d (every 30th obs) reported; DSR also on non-overlapping monthly sums (headline conservative).")
    a("- Holdout: best config chosen on first 80% only (IS Sharpe, net s=1.5); holdout metrics reported once, never used for selection. Grid is exactly 4 configs (n_trials=4); h=7, GK, ETH are robustness outside n_trials. Constants (THR=5, V0, vol-target 10%/cap 2, roll 0.25, s grid) fixed a priori before running; none tuned.")
    a("- Simplifications: daily accrual uses realized r^2 only (no mark-to-market of remaining implied variance); vol-target scales the s=0 book of the same regime so costs do not change sizing; returns arithmetic on fixed equity; no margin/funding costs; Deribit DVOL is an index, not a tradeable quote; the s-vol-point spread is an assumption (live calibration pending).")
    open(OUT / "vrp.md", "w").write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
