"""Carry-as-overlay-to-BTC study. Frozen spec: research/PREREG_OVERLAY.md. Reuses carry_runner machinery;
carry sleeve fixed = w7d|z|vt|1d (NOT re-selected). Writes reports/overlay.{md,json}."""
from __future__ import annotations
import sys, json, math, pickle
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import research.carry_runner as CR
from research.execution.costs import CostParams, impact_bps
from research.validation.bootstrap import stationary_bootstrap_indices

ANN = 365.0
SLEEVE = "w7d|z|vt|1d"
WIN = 60                 # trailing window (days) for vol/cov: fixed a priori
BLOCK = 10               # stationary-bootstrap expected block length (days)
NBOOT = 2000
NTR = 5
TARGET = 0.20
KS = [0.125, 0.25, 0.5, 1.0, 2.0]
BASE_K = 0.5
OUT = ROOT / "reports"


def log(*a): CR.log(*a)


def sr(r): r = np.asarray(r, float); s = r.std(ddof=1); return float(r.mean() / s * math.sqrt(ANN)) if s > 0 else 0.0


def stats_of(r):
    r = np.asarray(r, float); eq = np.cumprod(1 + r); pk = np.maximum.accumulate(np.r_[1.0, eq])[1:]
    yrs = len(r) / ANN
    return dict(ann_ret=float(r.mean() * ANN), cagr=float(eq[-1] ** (1 / yrs) - 1) if eq[-1] > 0 else -1.0,
                vol=float(r.std(ddof=1) * math.sqrt(ANN)), sharpe=sr(r), maxdd=float((eq / pk - 1).min()), n=len(r))


def hac(G, lag):
    T = G.shape[0]; G = G - G.mean(0); S = G.T @ G / T
    for j in range(1, lag + 1):
        w = 1 - j / (lag + 1.0); gm = G[j:].T @ G[:-j] / T; S += w * (gm + gm.T)
    return S


def jkm_hac(r1, r2, lag=None):
    """Sharpe difference SR1-SR2 (per-period), Jobson-Korkie-Memmel in the Ledoit-Wolf (2008) HAC form:
    delta method on (mu1,mu2,m2_1,m2_2) with Newey-West covariance of the moment series. Returns (diff_annual, z, p)."""
    r1, r2 = np.asarray(r1, float), np.asarray(r2, float); T = len(r1)
    lag = lag or int(round(4 * (T / 100.0) ** (2 / 9)))
    G = np.c_[r1, r2, r1 ** 2, r2 ** 2]
    u = G.mean(0); S = hac(G, lag)
    s1, s2 = math.sqrt(u[2] - u[0] ** 2), math.sqrt(u[3] - u[1] ** 2)
    f = u[0] / s1 - u[1] / s2
    g = np.array([u[2] / s1 ** 3, -u[3] / s2 ** 3, -u[0] / (2 * s1 ** 3), u[1] / (2 * s2 ** 3)])
    se = math.sqrt(max(g @ S @ g / T, 1e-30)); z = f / se
    return float(f * math.sqrt(ANN)), float(z), float(2 * (1 - stats.norm.cdf(abs(z)))), float(se * math.sqrt(ANN))


def boot_sr_diff(r1, r2, rng=0, alpha=0.05):
    r1, r2 = np.asarray(r1, float), np.asarray(r2, float); n = len(r1)
    idx = stationary_bootstrap_indices(n, BLOCK, NBOOT, rng=rng)
    d = np.array([sr(r1[i]) - sr(r2[i]) for i in idx])
    return dict(point=sr(r1) - sr(r2), lo=float(np.percentile(d, 100 * alpha / 2)), hi=float(np.percentile(d, 100 * (1 - alpha / 2))),
                p_boot=float(min(1.0, 2 * min((d <= 0).mean(), (d >= 0).mean()))))


# ------------------------------------------------------------------ combos (all trailing, shifted)
def combos(b: pd.Series, c: pd.Series):
    """Daily returns of the 5 frozen combos. Weights for day t use returns up to t-1 only (shift(1)).
    Daily rebalance to target weights; cash earns 0."""
    out = {}
    for f in (0.5, 0.7, 0.9):
        out[f"static_f{f}"] = f * b + (1 - f) * c
    vb, vc = b.rolling(WIN).std().shift(1), c.rolling(WIN).std().shift(1)      # trailing, shift(1)
    wb_d = (1 / vb) / (1 / vb + 1 / vc)
    # inverse-vol: monthly rebalance -> weight fixed at first trading day of each month (value from trailing vol at that date)
    ym = b.index.to_period("M")
    wb_m = wb_d.groupby(ym).transform("first")
    out["invvol_monthly"] = wb_m * b + (1 - wb_m) * c
    # vol-target: base 50/50 (fixed a priori), scale = min(20%/sigma_p, 1) on trailing 60d covariance, shift(1); remainder cash
    base = 0.5 * b + 0.5 * c
    sp = base.rolling(WIN).std().shift(1) * math.sqrt(ANN)       # trailing combo vol (=sqrt(w'Cw) of trailing cov, w=.5/.5)
    scale = (TARGET / sp).clip(upper=1.0)
    out["voltarget20"] = scale * base
    return out


def build_series(raw, full, ks):
    d = pd.DataFrame({"x": 0}, index=full.didx)
    W = CR.cached("full", SLEEVE, lambda: CR.build_W(full, CR.GRID[SLEEVE]), False)   # cache from carry_runner, reused
    carry = {}
    for k in ks:
        a = CR.account(full, W, k)
        carry[k] = a["net"]
    return carry, a


def main():
    t0 = pd.Timestamp.now()
    meta = json.load(open(OUT / "carry.json"))
    assert meta["best"] == SLEEVE
    w = meta["window"]; start, end, is_end = pd.Timestamp(w["start"], tz="UTC"), pd.Timestamp(w["end"], tz="UTC"), pd.Timestamp(w["is_end"], tz="UTC")
    raw = CR.load_raw(); full = CR.Ctx(raw)
    carry, _ = build_series(raw, full, KS)
    # BTC core: spot-style daily close-to-close from klines_1d; single initial purchase costed one-way
    d1 = raw[0]; bt = d1[d1.symbol == "BTCUSDT"].set_index("ts")["c"].sort_index()
    bret = bt.pct_change()
    cp = CostParams(impact_k=BASE_K)
    adv0 = float(full.adv_d.loc[start, "BTCUSDT"])
    imp0 = float(impact_bps(np.array([CR.CAPITAL]), np.array([adv0]), cp)[0]) / 1e4
    buycost = cp.taker_fee + imp0
    log(f"BTC initial purchase cost one-way: fee {cp.taker_fee*1e4:.1f}bp + impact {imp0*1e4:.2f}bp = {buycost*1e4:.2f}bp (ADV0 {adv0:.3g})")
    dates = full.didx[(full.didx >= start) & (full.didx <= end)]
    b_all = bret.reindex(dates).copy(); b_all.iloc[0] = (1 + b_all.iloc[0]) * (1 - buycost) - 1
    assert b_all.notna().all()
    C = {k: carry[k].reindex(dates) for k in KS}
    assert C[BASE_K].notna().all(), C[BASE_K].isna().sum()
    c = C[BASE_K]
    ev = dates[WIN:]                                     # common evaluation window after trailing warmup
    ev_is, ev_ho = ev[ev <= is_end], ev[ev > is_end]
    log(f"eval {ev[0].date()}..{ev[-1].date()} n={len(ev)}; IS n={len(ev_is)} (..{is_end.date()}), HO n={len(ev_ho)}")

    def allcombos(cs):
        return combos(b_all, cs)
    cb = allcombos(c)
    names = list(cb)
    assert len(names) == NTR
    R = {n: cb[n].loc[ev] for n in names}
    b, cc = b_all.loc[ev], c.loc[ev]

    # ---- 1. corr
    corr = dict(full=float(b.corr(cc)), is_=float(b.loc[ev_is].corr(cc.loc[ev_is])), ho=float(b.loc[ev_ho].corr(cc.loc[ev_ho])),
                down_days_corr=float(b[b < 0].corr(cc[b < 0])))
    log("corr", corr)

    # ---- 2. selection on IS only
    tab = {n: stats_of(R[n].loc[ev_is].values) for n in names}
    best = max(names, key=lambda n: tab[n]["sharpe"])
    log("IS sharpes", {n: round(tab[n]["sharpe"], 2) for n in names}, "BTC", round(sr(b.loc[ev_is]), 2), "best", best)

    def vs_btc(rc, rb, rng=0):
        d, z, p, se = jkm_hac(rc, rb)
        bo = boot_sr_diff(rc, rb, rng=rng)
        bo99 = boot_sr_diff(rc, rb, rng=rng, alpha=0.05 / NTR)
        return dict(sharpe_diff=d, jkm_z=z, jkm_p=p, jkm_p_bonf5=min(1.0, p * NTR), boot_ci95=[bo["lo"], bo["hi"]],
                    boot_ci_bonf5_99=[bo99["lo"], bo99["hi"]], boot_p=bo["p_boot"])

    rows_is = {}
    for n in names:
        rows_is[n] = dict(**tab[n], **vs_btc(R[n].loc[ev_is].values, b.loc[ev_is].values))
    btc_is = stats_of(b.loc[ev_is].values); carry_is = stats_of(cc.loc[ev_is].values)

    # ---- MAIN NULL on the best (IS): vs BTC scaled to matched vol + cash
    def main_null(rc, rb):
        s = stats_of(rc); sb = stats_of(rb)
        a = s["vol"] / sb["vol"]                       # BTC fraction matched on vol (a>1 would be leverage; reported)
        blend = a * rb                                   # remainder cash @0
        sbl = stats_of(blend)
        ex = rc - blend                                  # daily excess vs matched-vol BTC+cash
        bo = boot_ci_mean(ex)
        dom_ret = s["ann_ret"] > sbl["ann_ret"]; dom_dd = s["maxdd"] > sbl["maxdd"]   # maxdd negative: larger = shallower
        return dict(btc_fraction_matched=float(a), combo=s, btc_cash_blend=sbl, excess_ann_ret=float(ex.mean() * ANN),
                    excess_ret_ci95=bo, dominates_return=bool(dom_ret), dominates_maxdd=bool(dom_dd))

    def boot_ci_mean(x):
        x = np.asarray(x, float); idx = stationary_bootstrap_indices(len(x), BLOCK, NBOOT, rng=3)
        m = np.array([x[i].mean() for i in idx]) * ANN
        return [float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))]

    mn_is = main_null(R[best].loc[ev_is].values, b.loc[ev_is].values)
    mn_all = {n: main_null(R[n].loc[ev_is].values, b.loc[ev_is].values) for n in names}
    rb_ = rows_is[best]
    sharpe_sig = bool(rb_["sharpe_diff"] > 0 and rb_["jkm_p_bonf5"] < 0.05 and rb_["boot_ci_bonf5_99"][0] > 0)
    sharpe_sig_raw = bool(rb_["sharpe_diff"] > 0 and rb_["jkm_p"] < 0.05 and rb_["boot_ci95"][0] > 0)
    excess_sig = mn_is["excess_ret_ci95"][0] > 0
    p1 = bool(sharpe_sig)
    p2 = bool(rb_["sharpe_diff"] > 0 and sharpe_sig and mn_is["dominates_return"] and mn_is["dominates_maxdd"] and excess_sig)
    p3 = bool(abs(mn_is["combo"]["maxdd"]) <= 0.75 * abs(btc_is["maxdd"]) and mn_is["dominates_return"])
    neg = b.loc[ev_is] < 0
    c_is = cc.loc[ev_is]
    contrib = dict(carry_mean_ann=float(c_is.mean() * ANN), carry_mean_on_btc_down_days_ann=float(c_is[neg].mean() * ANN),
                   carry_mean_on_btc_up_days_ann=float(c_is[~neg].mean() * ANN))
    p4 = bool(corr["is_"] < 0.6 and corr["full"] < 0.6 and contrib["carry_mean_ann"] > 0 and contrib["carry_mean_on_btc_down_days_ann"] > 0)

    # ---- holdout (supporting)
    ho_rows = {n: stats_of(R[n].loc[ev_ho].values) for n in names}
    ho_btc = stats_of(b.loc[ev_ho].values); ho_carry = stats_of(cc.loc[ev_ho].values)
    ho_best = dict(**ho_rows[best], **vs_btc(R[best].loc[ev_ho].values, b.loc[ev_ho].values, rng=1))
    ho_mn = main_null(R[best].loc[ev_ho].values, b.loc[ev_ho].values)
    p5_support = bool(ho_best["sharpe"] > ho_btc["sharpe"] and ho_mn["dominates_return"])

    # ---- full-window (info; selection not isolated)
    full_rows = {n: dict(**stats_of(R[n].values), **vs_btc(R[n].values, b.values, rng=2)) for n in names}

    # ---- 6. cost robustness: rebuild carry sleeve at each impact_k; sign of Sharpe improvement (IS, best-at-base combo fixed; and all combos)
    costtab = {}
    for k in KS:
        ck = C[k]; cbk = allcombos(ck); row = {}
        for n in names:
            rr = cbk[n].loc[ev]
            row[n] = dict(is_diff=sr(rr.loc[ev_is]) - sr(b.loc[ev_is]), full_diff=sr(rr) - sr(b),
                          ho_diff=sr(rr.loc[ev_ho]) - sr(b.loc[ev_ho]))
        row["carry_is_sharpe"] = sr(ck.loc[ev].loc[ev_is]); row["carry_cagr_is"] = stats_of(ck.loc[ev].loc[ev_is].values)["cagr"]
        costtab[str(k)] = row
    sign_best = {k: bool(costtab[k][best]["is_diff"] > 0) for k in costtab}
    p6 = bool(all(sign_best.values()))
    sign_all = {n: {k: bool(costtab[k][n]["is_diff"] > 0) for k in costtab} for n in names}

    verdict = {
        "1_sharpe_gt_btc_significant": dict(passed=p1, raw_sig=sharpe_sig_raw, **{k: rb_[k] for k in ("sharpe_diff", "jkm_p", "jkm_p_bonf5", "boot_ci95", "boot_ci_bonf5_99")}),
        "2_MAIN_NULL_beats_btc_cash_not_dilution": dict(passed=p2, sharpe_diff=rb_["sharpe_diff"], **{k: mn_is[k] for k in ("btc_fraction_matched", "excess_ann_ret", "excess_ret_ci95", "dominates_return", "dominates_maxdd")}),
        "3_maxdd_lower_return_ge_blend": dict(passed=p3, combo_maxdd=mn_is["combo"]["maxdd"], btc_maxdd=btc_is["maxdd"], ratio=abs(mn_is["combo"]["maxdd"]) / abs(btc_is["maxdd"]), rule="|DD|<=0.75*|DD_BTC| and return > matched-vol BTC+cash"),
        "4_diversification_real": dict(passed=p4, corr=corr, **contrib),
        "5_holdout_supporting_forward_pending": dict(passed="pending (holdout supporting=%s; forward paper-trade pending)" % p5_support, holdout_supporting_ok=p5_support),
        "6_cost_robust_sign": dict(passed=p6, sign_best_by_k=sign_best),
    }
    confirmed = all(verdict[k]["passed"] is True for k in verdict if not k.startswith("5"))
    overall = "NOT CONFIRMED" if not confirmed else "CONFIRMED on backtest (forward paper-trade pending)"
    res = dict(generated=str(pd.Timestamp.now()), sleeve=SLEEVE, window=dict(eval_start=str(ev[0].date()), eval_end=str(ev[-1].date()), is_end=str(is_end.date()), n=len(ev), n_is=len(ev_is), n_ho=len(ev_ho), warmup_days=WIN),
               btc_buy_cost_bps=buycost * 1e4, corr=corr, btc_is=btc_is, carry_is=carry_is, combos_is=rows_is, best=best, main_null_best=mn_is,
               main_null_all=mn_all, holdout=dict(btc=ho_btc, carry=ho_carry, rows=ho_rows, best=ho_best, main_null=ho_mn),
               full_window=full_rows, btc_full=stats_of(b.values), carry_full=stats_of(cc.values), cost_robustness=costtab, sign_all=sign_all,
               verdict=verdict, overall=overall, n_trials=NTR)
    json.dump(res, open(OUT / "overlay.json", "w"), indent=1, default=float)
    write_md(res)
    log("overall", overall, "best", best, "p:", p1, p2, p3, p4, p6)


def f(x, p=1): return f"{100*x:.{p}f}%"


def write_md(o):
    L = []; A = L.append; v = o["verdict"]; b = o["best"]
    A("# Carry as overlay to BTC core - result\n")
    A(f"Frozen spec: research/PREREG_OVERLAY.md. Carry sleeve fixed `{o['sleeve']}` (net, impact_k=0.5, from carry_runner weights; not re-fit). "
      f"BTC core = BTCUSDT daily close-to-close buy&hold (klines_1d), single initial purchase costed one-way: taker fee 4.5bp + sqrt-impact on $1M vs 30d ADV = {o['btc_buy_cost_bps']:.2f}bp total, applied to day-1 return (no funding: spot-style). "
      f"Cash 0%. Eval window {o['window']['eval_start']}..{o['window']['eval_end']} after a {WIN}d trailing-warmup (n={o['window']['n']}; IS n={o['window']['n_is']} to {o['window']['is_end']}; HO n={o['window']['n_ho']}). n_trials={o['n_trials']}.\n")
    A(f"## OVERALL: **{o['overall']}**\n")
    c = o["corr"]
    A(f"## 1. Correlation BTC vs carry (daily)\nfull {c['full']:.3f}; IS {c['is_']:.3f}; HO {c['ho']:.3f}; on BTC-down days {c['down_days_corr']:.3f}.\n")
    A("## 2. Five combinations, IS (selection window)\n")
    A("| combo | ann ret | CAGR | vol | Sharpe | maxDD | dSharpe vs BTC | JKM-HAC p | p x5 (Bonf) | boot 95% CI | boot 99% CI (x5) |\n|---|---|---|---|---|---|---|---|---|---|---|")
    bi, ci = o["btc_is"], o["carry_is"]
    for nm, s in (("BTC core", bi), ("Carry sleeve", ci)):
        A(f"| {nm} | {f(s['ann_ret'])} | {f(s['cagr'])} | {f(s['vol'])} | {s['sharpe']:.2f} | {f(s['maxdd'])} | - | - | - | - | - |")
    for n, s in o["combos_is"].items():
        A(f"| {n}{' **(best IS)**' if n==b else ''} | {f(s['ann_ret'])} | {f(s['cagr'])} | {f(s['vol'])} | {s['sharpe']:.2f} | {f(s['maxdd'])} | {s['sharpe_diff']:+.2f} | {s['jkm_p']:.3f} | {s['jkm_p_bonf5']:.3f} | [{s['boot_ci95'][0]:+.2f},{s['boot_ci95'][1]:+.2f}] | [{s['boot_ci_bonf5_99'][0]:+.2f},{s['boot_ci_bonf5_99'][1]:+.2f}] |")
    A(f"\nBest on IS Sharpe: **{b}**.\n")
    mn = o["main_null_best"]
    A("## 3. MAIN NULL (point 2): combo vs BTC+cash at matched vol (IS, best combo)\n")
    A("| | ann ret | vol | Sharpe | maxDD |\n|---|---|---|---|---|")
    A(f"| {b} | {f(mn['combo']['ann_ret'])} | {f(mn['combo']['vol'])} | {mn['combo']['sharpe']:.2f} | {f(mn['combo']['maxdd'])} |")
    A(f"| BTC x {mn['btc_fraction_matched']:.2f} + cash | {f(mn['btc_cash_blend']['ann_ret'])} | {f(mn['btc_cash_blend']['vol'])} | {mn['btc_cash_blend']['sharpe']:.2f} | {f(mn['btc_cash_blend']['maxdd'])} |")
    A(f"\nExcess ann. return vs matched-vol BTC+cash: {f(mn['excess_ann_ret'])}, 95% boot CI [{f(mn['excess_ret_ci95'][0])}, {f(mn['excess_ret_ci95'][1])}]. Dominates on return: {mn['dominates_return']}; on maxDD: {mn['dominates_maxdd']}.")
    A("\nAll combos vs matched-vol BTC+cash (IS):\n\n| combo | BTC frac | excess ann ret | 95% CI | dominates ret | dominates DD |\n|---|---|---|---|---|---|")
    for n, m in o["main_null_all"].items():
        A(f"| {n} | {m['btc_fraction_matched']:.2f} | {f(m['excess_ann_ret'])} | [{f(m['excess_ret_ci95'][0])},{f(m['excess_ret_ci95'][1])}] | {m['dominates_return']} | {m['dominates_maxdd']} |")
    A("\n## 4. Six-point verdict (IS)\n")
    for k, d in v.items():
        A(f"- **{k}**: {d['passed'] if not isinstance(d['passed'], bool) else ('PASS' if d['passed'] else 'FAIL')}  \n  `{json.dumps({x: y for x, y in d.items() if x != 'passed'}, default=float)[:600]}`")
    h = o["holdout"]
    A("\n## 5. Holdout (SUPPORTING only - carry's holdout was already seen in FORM-L; not decisive)\n")
    A("| | ann ret | vol | Sharpe | maxDD |\n|---|---|---|---|---|")
    A(f"| BTC | {f(h['btc']['ann_ret'])} | {f(h['btc']['vol'])} | {h['btc']['sharpe']:.2f} | {f(h['btc']['maxdd'])} |")
    A(f"| Carry | {f(h['carry']['ann_ret'])} | {f(h['carry']['vol'])} | {h['carry']['sharpe']:.2f} | {f(h['carry']['maxdd'])} |")
    for n, s in h["rows"].items():
        A(f"| {n}{' (selected)' if n==b else ''} | {f(s['ann_ret'])} | {f(s['vol'])} | {s['sharpe']:.2f} | {f(s['maxdd'])} |")
    hb = h["best"]; hm = h["main_null"]
    A(f"\nSelected combo HO: dSharpe vs BTC {hb['sharpe_diff']:+.2f}, JKM p {hb['jkm_p']:.3f}, boot CI [{hb['boot_ci95'][0]:+.2f},{hb['boot_ci95'][1]:+.2f}]; vs matched-vol BTC+cash (frac {hm['btc_fraction_matched']:.2f}) excess {f(hm['excess_ann_ret'])} CI [{f(hm['excess_ret_ci95'][0])},{f(hm['excess_ret_ci95'][1])}]. Forward paper-trade (decisive) is PENDING.\n")
    A("## 6. Cost robustness: dSharpe (combo - BTC) by impact_k (carry sleeve rebuilt per k)\n")
    A("| impact_k | carry IS Sharpe | " + " | ".join(f"{n} IS" for n in o["sign_all"]) + " | selected HO |\n|---|---|" + "---|" * (len(o["sign_all"]) + 1))
    for k, r in o["cost_robustness"].items():
        A(f"| {k} | {r['carry_is_sharpe']:.2f} | " + " | ".join(f"{r[n]['is_diff']:+.2f}" for n in o["sign_all"]) + f" | {r[b]['ho_diff']:+.2f} |")
    A(f"\nSign of selected combo's IS improvement positive at all k: {v['6_cost_robust_sign']['passed']}.\n")
    A("## Full window (info only, selection not isolated)\n\n| combo | Sharpe | maxDD | dSharpe vs BTC | JKM p |\n|---|---|---|---|---|")
    bf = o["btc_full"]; A(f"| BTC | {bf['sharpe']:.2f} | {f(bf['maxdd'])} | - | - |")
    for n, s in o["full_window"].items():
        A(f"| {n} | {s['sharpe']:.2f} | {f(s['maxdd'])} | {s['sharpe_diff']:+.2f} | {s['jkm_p']:.3f} |")
    A("""
## Lookahead self-audit
- Vol/cov for invvol and vol-target are rolling(60) of daily returns then `.shift(1)`: weight on day t uses returns <= t-1. Monthly invvol takes the shifted weight of the first day of the month and holds it.
- Static and base 50/50 weights are constants; vol-target scale uses only trailing combo vol; no leverage (cap 1, rest cash 0%).
- Best combination chosen by IS Sharpe only (<= is_end); holdout touched once for the selected combo (plus display of the others, not used for choice). Holdout is not virgin for carry (FORM-L), so it is supporting.
- Carry sleeve NOT re-fit: weights come from `build_W(full ctx, w7d|z|vt|1d)` via carry_runner's cache (PIT universe, signals on t-1 info, trades at next open, ADV shift(1)); only `account(impact_k)` is re-run per k (weights do not depend on k). Note the sleeve itself was selected on IS in FORM-L (n=16 trials) - residual selection bias in the carry leg is NOT corrected here.
- BTC core: buy-and-hold, only day-1 purchase cost; no funding.
- Warmup: first 60 days dropped from all series (incl. BTC) so every combo has trailing stats.
- Underspecified choices fixed a priori: window 60d, daily rebalance to target weights, vol-target base 50/50, leverage cap 1, bootstrap block 10d, 2000 resamples, Bonferroni x5, 'substantially lower maxDD' = <=0.75x BTC maxDD.
""")
    (OUT / "overlay.md").write_text("\n".join(L))


if __name__ == "__main__":
    main()
