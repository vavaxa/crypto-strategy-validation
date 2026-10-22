"""BTC-only in/out timing study. Frozen spec: research/PREREG_BTCTIMING.md. 5 signals, n_trials=5.
Writes reports/btc_timing.{md,json}. Fast (seconds); re-running is idempotent (resumable by construction)."""
from __future__ import annotations
import sys, json, math
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from research.overlay_runner import sr, stats_of, jkm_hac, boot_sr_diff, ANN
from research.execution.costs import CostParams, impact_bps
from research.validation.bootstrap import stationary_bootstrap_indices
from research.validation.cross_validation import purged_kfold
from research.validation.sharpe import deflated_sharpe_ratio, sharpe_lo
from scipy import stats as sps

OUT = ROOT / "reports"
NTR = 5; CAPITAL = 1_000_000.0; WARM = 366; IS_FRAC = 0.8
SIGS = {"SMA100": ("sma", 100), "SMA200": ("sma", 200), "tsmom90": ("mom", 90), "tsmom180": ("mom", 180), "tsmom365": ("mom", 365)}
def log(*a): print(*a, flush=True)
def f(x, p=1): return f"{100*x:.{p}f}%"

def load():
    s = pd.read_parquet(ROOT / "data/mech/spot_klines_1d_binance.parquet")
    s = s[s.symbol == "BTCUSDT"].set_index("ts").sort_index()
    k = pd.read_parquet(ROOT / "data/mech/klines_1d_binance.parquet")
    k = k[k.symbol == "BTCUSDT"].set_index("ts").sort_index()
    j = s[["c"]].join(k[["c"]], rsuffix="_perp", how="inner")
    rel = (j.c / j.c_perp - 1).abs()
    sanity = dict(n_spot=len(s), first=str(s.index[0].date()), last=str(s.index[-1].date()), n_overlap=len(j), overlap_first=str(j.index[0].date()),
                  median_abs_rel_diff=float(rel.median()), max_abs_rel_diff=float(rel.max()), p99_abs_rel_diff=float(rel.quantile(.99)),
                  corr_daily_ret=float(j.c.pct_change().corr(j.c_perp.pct_change())))
    assert s.index.is_unique and (s.index.to_series().diff().dropna() == pd.Timedelta(days=1)).all(), "gaps"
    return s, sanity

def signal(c, kind, n):
    # computed on close of day t (uses c_t and earlier only); 1 = in BTC, 0 = cash
    if kind == "sma": return (c > c.rolling(n).mean()).astype(float).where(c.rolling(n).count() == n)
    return (c / c.shift(n) - 1 > 0).astype(float).where(c.shift(n).notna())

def run_strategy(o, c, sig, cost_oneway):
    """pos_d = sig_{d-1} (shift(1)); trade at OPEN d on flips. ret_d = prev*(o_d/c_{d-1}-1) + new*(c_d/o_d-1) - cost*|new-prev|."""
    pos = sig.shift(1)
    prev = pos.shift(1).fillna(0.0)             # before first eval day we are in cash -> initial entry is costed
    new = pos
    ret = prev * (o / c.shift(1) - 1) + new * (c / o - 1) - cost_oneway * (new - prev).abs()
    return ret, pos

def trades_of(o, c, pos, cost):
    """list of round trips (entry open -> exit open or last close) with net pnl"""
    p = pos.values; idx = pos.index; rt = []; ent = None
    prev = 0.0
    for i in range(len(p)):
        if p[i] == 1 and prev == 0: ent = i
        if p[i] == 0 and prev == 1 and ent is not None:
            rt.append((ent, i)); ent = None
        prev = p[i]
    if ent is not None: rt.append((ent, None))
    out = []
    for a, b in rt:
        pe = o.iloc[a]; px = o.iloc[b] if b is not None else c.iloc[-1]
        out.append(dict(entry=str(idx[a].date()), exit=str(idx[b].date()) if b is not None else "open", days=(b if b is not None else len(p)) - a,
                        pnl=float(px / pe * (1 - cost) ** 2 - 1)))
    return out

def main():
    s, sanity = load(); log("sanity", sanity)
    o, c = s.o, s.c
    cp = CostParams(); adv = (s.quote_volume.rolling(30).mean().shift(1))
    imp_bp = float(impact_bps(np.array([CAPITAL]), np.array([adv.loc["2018-08-17":].median()]), cp)[0])   # median-ADV impact (floor 0.5bp)
    cost_literal = cp.taker_fee + imp_bp / 1e4          # costs.py stub literally (sqrt-impact vs ADV): ~125bp, absurd for BTC; stress only
    imp_bp_primary = cp.min_spread_bps / 2.0            # PRIMARY: spec says impact ~0 for BTC -> half-spread floor 0.5bp only
    cost = cp.taker_fee + imp_bp_primary / 1e4
    log(f"PRIMARY one-way cost {cost*1e4:.2f}bp; costs.py-literal {cost_literal*1e4:.2f}bp (stress)")
    imp_literal = imp_bp; imp_bp = imp_bp_primary
    sigs = {n: signal(c, *v) for n, v in SIGS.items()}
    ev = c.index[WARM:]; n = len(ev); n_is = int(n * IS_FRAC); ev_is, ev_ho = ev[:n_is], ev[n_is:]
    # B&H: close-to-close, one initial cost (buy at open of first eval day -> day-1 ret = c/o-1 less cost)
    bh = c.pct_change().copy(); bh.iloc[:] = bh; d0 = ev[0]
    bh.loc[d0] = (c.loc[d0] / o.loc[d0]) * (1 - cost) - 1
    R, POS = {}, {}
    for nme, sg in sigs.items():
        r, p = run_strategy(o, c, sg, cost); R[nme], POS[nme] = r.loc[ev], p.loc[ev]
        assert POS[nme].notna().all() and R[nme].notna().all()
    B = bh.loc[ev]
    log(f"eval {ev[0].date()}..{ev[-1].date()} n={n} IS n={n_is} (..{ev_is[-1].date()}) HO n={len(ev_ho)}")

    def row(r, pos=None, idx=None):
        d = stats_of(r.values)
        if pos is not None:
            ch = pos.diff().abs(); ch.iloc[0] = abs(pos.iloc[0])  # initial entry counts
            d.update(n_flips=int(ch.sum()), n_roundtrips=int((ch.cumsum() // 1).iloc[-1] // 2) if False else int(((pos.diff() == 1).sum()) + (1 if pos.iloc[0] == 1 else 0)),
                     turnover_per_year=float(ch.sum() / (len(r) / ANN)), time_in_market=float(pos.mean()))
        else: d.update(n_flips=1, n_roundtrips=1, turnover_per_year=1 / (len(r) / ANN), time_in_market=1.0)
        return d
    def vs(r1, r2, rng=0):
        d, z, p, se = jkm_hac(r1.values, r2.values)
        b95 = boot_sr_diff(r1.values, r2.values, rng=rng); b99 = boot_sr_diff(r1.values, r2.values, rng=rng, alpha=0.05 / NTR)
        return dict(sharpe_diff=d, jkm_z=z, jkm_p=p, jkm_p_bonf5=min(1.0, p * NTR), boot_ci95=[b95["lo"], b95["hi"]], boot_ci_bonf5_99=[b99["lo"], b99["hi"]], boot_p=b95["p_boot"])
    def cash_blend(rt, rb):
        st, sb = stats_of(rt.values), stats_of(rb.values); a = st["vol"] / sb["vol"]; bl = a * rb
        ex = (rt - bl).values; idx = stationary_bootstrap_indices(len(ex), 10, 2000, rng=3)
        m = np.array([ex[i].mean() for i in idx]) * ANN
        sbl = stats_of(bl.values)
        return dict(btc_fraction_matched=float(a), timing=st, btc_cash_blend=sbl, excess_ann_ret=float(ex.mean() * ANN),
                    excess_ret_ci95=[float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))],
                    dominates_return=bool(st["ann_ret"] > sbl["ann_ret"]), dominates_maxdd=bool(st["maxdd"] > sbl["maxdd"]))

    # ---- IS table + selection
    Bi = B.loc[ev_is]; btc_is = row(Bi)
    tab = {nm: dict(**row(R[nm].loc[ev_is], POS[nm].loc[ev_is]), **vs(R[nm].loc[ev_is], Bi)) for nm in SIGS}
    best = max(SIGS, key=lambda k: tab[k]["sharpe"])
    n_beat = sum(tab[k]["sharpe"] > btc_is["sharpe"] for k in SIGS)
    log("IS sharpe", {k: round(tab[k]["sharpe"], 2) for k in tab}, "BTC", round(btc_is["sharpe"], 2), "best", best)
    rb = tab[best]; Ri = R[best].loc[ev_is]
    mn = cash_blend(Ri, Bi); mn_all = {k: cash_blend(R[k].loc[ev_is], Bi) for k in SIGS}
    sig_bonf = bool(rb["sharpe_diff"] > 0 and rb["jkm_p_bonf5"] < .05 and rb["boot_ci_bonf5_99"][0] > 0)
    sig_raw = bool(rb["sharpe_diff"] > 0 and rb["jkm_p"] < .05 and rb["boot_ci95"][0] > 0)
    # ---- purged k-fold on IS (signals have no fitted params -> per-fold OOS performance & consistency)
    folds = purged_kfold(n_is, 5, 0.02); cv = []
    for tr, te in folds:
        rt, rbb = Ri.values[te], Bi.values[te]
        cv.append(dict(n_test=len(te), sharpe=sr(rt), btc_sharpe=sr(rbb), diff=sr(rt) - sr(rbb), maxdd=stats_of(rt)["maxdd"], btc_maxdd=stats_of(rbb)["maxdd"]))
    cvs = np.array([x["diff"] for x in cv])
    # DSR on IS best (per-period SR)
    rr = Ri.values; T = len(rr); sp = rr.mean() / rr.std(ddof=1)
    dsr = deflated_sharpe_ratio(sp, NTR, T, skew=float(sps.skew(rr)), kurt=float(sps.kurtosis(rr, fisher=False)))
    dsr_btc = deflated_sharpe_ratio(Bi.mean() / Bi.std(ddof=1), 1, T, skew=float(sps.skew(Bi.values)), kurt=float(sps.kurtosis(Bi.values, fisher=False)))
    lo = sharpe_lo(rr) if callable(sharpe_lo) else None
    # ---- holdout (once, selected only)
    Bh, Rh = B.loc[ev_ho], R[best].loc[ev_ho]
    ho = dict(timing=row(Rh, POS[best].loc[ev_ho]), btc=row(Bh), **vs(Rh, Bh, rng=1), main_null=cash_blend(Rh, Bh))
    ho_all = {k: stats_of(R[k].loc[ev_ho].values) for k in SIGS}
    ho_same_sign = bool(ho["sharpe_diff"] > 0)
    # ---- full-window (info only)
    full = {k: dict(**row(R[k], POS[k]), **vs(R[k], B, rng=2)) for k in SIGS}; btc_full = row(B)
    # ---- by year / regime for best (full eval window; info, selection not isolated)
    Rf = R[best]; yr = {}
    for y in sorted(set(ev.year)):
        m = ev.year == y
        if m.sum() < 30: continue
        a, b = Rf[m], B[m]; pp = POS[best][m]
        yr[str(y)] = dict(n=int(m.sum()), timing_ret=float((1 + a).prod() - 1), btc_ret=float((1 + b).prod() - 1), timing_sharpe=sr(a.values), btc_sharpe=sr(b.values),
                          timing_maxdd=stats_of(a.values)["maxdd"], btc_maxdd=stats_of(b.values)["maxdd"], flips=int(pp.diff().abs().sum()), in_mkt=float(pp.mean()))
    eq = (1 + B).cumprod(); dd = eq / eq.cummax() - 1; bear = dd < -0.30   # ex-post label: BTC >30% below running ATH close
    reg = {}
    for nm, m in (("bull(DD>-30%)", ~bear), ("bear(DD<=-30%)", bear)):
        a, b = Rf[m], B[m]
        reg[nm] = dict(n=int(m.sum()), timing_ann_ret=float(a.mean() * ANN), btc_ann_ret=float(b.mean() * ANN), timing_sum_logret=float(np.log1p(a).sum()), btc_sum_logret=float(np.log1p(b).sum()),
                       in_mkt=float(POS[best][m].mean()))
    ex22 = ev.year != 2022
    x22 = dict(timing=stats_of(Rf[ex22].values), btc=stats_of(B[ex22].values), **vs(Rf[ex22], B[ex22], rng=4), main_null=cash_blend(Rf[ex22], B[ex22]),
               y2022_timing=stats_of(Rf[~ex22].values), y2022_btc=stats_of(B[~ex22].values))
    x22_is = ev_is[ev_is.year != 2022]
    x22_is_d = dict(timing=stats_of(Rf.loc[x22_is].values), btc=stats_of(B.loc[x22_is].values), **vs(Rf.loc[x22_is], B.loc[x22_is], rng=5))
    # ---- whipsaw
    tr = trades_of(o.loc[ev], c.loc[ev], POS[best], cost)
    def ws(a, b):
        t = [x for x in tr if a <= x["entry"] <= b]
        return dict(n_trades=len(t), win_rate=float(np.mean([x["pnl"] > 0 for x in t])) if t else None, median_days=float(np.median([x["days"] for x in t])) if t else None,
                    sum_pnl=float(np.sum([x["pnl"] for x in t])) if t else 0.0, short_trades_le30d=int(sum(x["days"] <= 30 for x in t)))
    whip = dict(all=ws("0000", "9999"), y2019=ws("2019-01-01", "2019-12-31"), y2022=ws("2022-01-01", "2022-12-31"),
                cost_total_bp_per_year=float(POS[best].diff().abs().sum() * cost * 1e4 / (n / ANN)), trades=tr)
    sw = {}
    for nm, m in (("2019 range", ev.year == 2019), ("2022 chop", ev.year == 2022)):
        if m.sum():
            sw[nm] = dict(timing_ret=float((1 + Rf[m]).prod() - 1), btc_ret=float((1 + B[m]).prod() - 1), flips=int(POS[best][m].diff().abs().sum()),
                          btc_range_hi_lo=float(c.loc[ev[m]].max() / c.loc[ev[m]].min() - 1))
    whip["sideways"] = sw
    # ---- cost stress (selection fixed to primary best; all 5 re-run per cost)
    cs = {}
    for cb_ in (cost * 1e4, 10.0, 25.0, cost_literal * 1e4):
        c_ = cb_ / 1e4; bh_ = bh.copy(); bh_.loc[d0] = (c.loc[d0] / o.loc[d0]) * (1 - c_) - 1; Bs = bh_.loc[ev]
        rowc = {}
        for nm, sg in sigs.items():
            r_, _ = run_strategy(o, c, sg, c_); r_ = r_.loc[ev]
            rowc[nm] = dict(is_sharpe=sr(r_.loc[ev_is].values), is_dsharpe=sr(r_.loc[ev_is].values) - sr(Bs.loc[ev_is].values),
                            ho_dsharpe=sr(r_.loc[ev_ho].values) - sr(Bs.loc[ev_ho].values), full_dsharpe=sr(r_.values) - sr(Bs.values))
        cs[f"{cb_:.1f}bp"] = rowc
    # ---- verdict
    p1 = sig_bonf; p2 = bool(p1 and mn["dominates_return"] and mn["dominates_maxdd"] and mn["excess_ret_ci95"][0] > 0)
    ddr = abs(rb["maxdd"]) / abs(btc_is["maxdd"]); p3 = bool(p1 and ddr <= .75)
    p4 = bool(ho_same_sign); p5 = bool(n_beat >= 3 and x22_is_d["sharpe_diff"] > 0 and x22["sharpe_diff"] > 0)
    verdict = {"1_sharpe_gt_btc_significant_bonf": p1, "1_raw": sig_raw, "2_main_null_not_dilution": p2, "3_maxdd<=0.75x_counts_only_if_1": p3, "3_maxdd_ratio": ddr,
               "4_holdout_sign_consistent": p4, "5_not_one_signal_or_one_crash": p5, "6_reported": True}
    confirmed = p1 and p2 and p3 and p5
    overall = "CONFIRMED (backtest)" if confirmed else "NOT CONFIRMED"
    res = dict(generated=str(pd.Timestamp.now()), sanity=sanity, cost_oneway_bp=cost * 1e4, impact_bp=imp_bp, window=dict(start=str(ev[0].date()), end=str(ev[-1].date()), n=n, n_is=n_is, is_end=str(ev_is[-1].date()), n_ho=len(ev_ho), warmup=WARM),
               btc_is=btc_is, signals_is=tab, best=best, n_beat_btc_is=int(n_beat), main_null_best=mn, main_null_all=mn_all, cv=dict(folds=cv, n_pos=int((cvs > 0).sum()), mean_diff=float(cvs.mean())),
               dsr=dsr, dsr_btc_n1=dsr_btc, holdout=dict(best=ho, all_signals=ho_all), full_window=full, btc_full=btc_full, by_year=yr, by_regime=reg, excl_2022_full=x22, excl_2022_IS=x22_is_d,
               cost_stress=cs, cost_literal_bp=cost_literal * 1e4, whipsaw=whip, verdict=verdict, overall=overall, n_trials=NTR)
    json.dump(res, open(OUT / "btc_timing.json", "w"), indent=1, default=float)
    write_md(res); log("overall", overall, verdict)

def write_md(o):
    L = []; A = L.append; b = o["best"]; w = o["window"]; v = o["verdict"]
    A("# BTC in/out timing - result\n")
    A(f"Frozen spec: research/PREREG_BTCTIMING.md. 5 signals, n_trials={o['n_trials']}. BTCUSDT SPOT daily, rf=0. Signal on close t, shift(1), trade at next OPEN on flips only. One-way cost {o['cost_oneway_bp']:.2f}bp (PRIMARY: taker 4.5 + 0.5bp half-spread floor, per the spec's 'impact ~0 for BTC'. NOTE costs.py's sqrt-impact stub taken literally gives {o['cost_literal_bp']:.0f}bp one-way for $1M vs BTC ADV, which is unrealistic for BTC; shown as a stress below). "
      f"Common eval window {w['start']}..{w['end']} (n={w['n']}) after a {w['warmup']}d warmup (needed by tsmom365; applied to all 5 + B&H). IS n={w['n_is']} (..{w['is_end']}), HO n={w['n_ho']}.\n")
    A(f"## OVERALL: **{o['overall']}**\n")
    s = o["sanity"]; A(f"Data sanity: spot {s['first']}..{s['last']} n={s['n_spot']}; vs perp klines_1d (overlap n={s['n_overlap']} from {s['overlap_first']}): median |close diff| {s['median_abs_rel_diff']*1e4:.1f}bp, p99 {s['p99_abs_rel_diff']*1e4:.1f}bp, max {s['max_abs_rel_diff']*1e4:.1f}bp; daily-return corr {s['corr_daily_ret']:.4f}.\n")
    def tr(nm, d, extra=""):
        return f"| {nm} | {f(d['ann_ret'])} | {f(d['cagr'])} | {f(d['vol'])} | {d['sharpe']:.2f} | {f(d['maxdd'])} | {d['n_roundtrips']} | {d['turnover_per_year']:.2f} | {f(d['time_in_market'],0)} |{extra}"
    hdr = "| strategy | ann ret | CAGR | vol | Sharpe | maxDD | #entries | flips/yr | time in mkt |"
    A("## 1. IS table (selection window)\n"); A(hdr + " dSharpe vs BTC | JKM p | p x5 | boot95 CI | boot99 CI (x5) |\n" + "|---|" * 0 + "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    A(tr("BTC B&H", o["btc_is"], " - | - | - | - | - |"))
    for k, d in o["signals_is"].items():
        A(tr(k + (" **(best)**" if k == b else ""), d, f" {d['sharpe_diff']:+.2f} | {d['jkm_p']:.3f} | {d['jkm_p_bonf5']:.3f} | [{d['boot_ci95'][0]:+.2f},{d['boot_ci95'][1]:+.2f}] | [{d['boot_ci_bonf5_99'][0]:+.2f},{d['boot_ci_bonf5_99'][1]:+.2f}] |"))
    A(f"\nBest on IS Sharpe: **{b}**. Signals beating BTC IS Sharpe: **{o['n_beat_btc_is']}/5**.\n")
    rb = o["signals_is"][b]
    A(f"## 2. Points 1/2: Sharpe edge and MAIN NULL (IS, {b})\n")
    A(f"dSharpe = {rb['sharpe_diff']:+.2f}; JKM-HAC p raw {rb['jkm_p']:.3f}, Bonferroni x5 {rb['jkm_p_bonf5']:.3f}; bootstrap 95% CI [{rb['boot_ci95'][0]:+.2f},{rb['boot_ci95'][1]:+.2f}], Bonferroni-99% CI [{rb['boot_ci_bonf5_99'][0]:+.2f},{rb['boot_ci_bonf5_99'][1]:+.2f}]. Significant (Bonf): **{v['1_sharpe_gt_btc_significant_bonf']}**; raw: {v['1_raw']}.\n")
    mn = o["main_null_best"]
    A("| | ann ret | vol | Sharpe | maxDD |\n|---|---|---|---|---|")
    A(f"| {b} | {f(mn['timing']['ann_ret'])} | {f(mn['timing']['vol'])} | {mn['timing']['sharpe']:.2f} | {f(mn['timing']['maxdd'])} |")
    A(f"| BTC x {mn['btc_fraction_matched']:.2f} + cash (matched vol) | {f(mn['btc_cash_blend']['ann_ret'])} | {f(mn['btc_cash_blend']['vol'])} | {mn['btc_cash_blend']['sharpe']:.2f} | {f(mn['btc_cash_blend']['maxdd'])} |")
    A(f"\nExcess ann. return vs matched-vol BTC+cash {f(mn['excess_ann_ret'])}, 95% boot CI [{f(mn['excess_ret_ci95'][0])},{f(mn['excess_ret_ci95'][1])}]; dominates on return {mn['dominates_return']}, on maxDD {mn['dominates_maxdd']}. MAIN-NULL (not dilution) passed: **{v['2_main_null_not_dilution']}**.\n")
    A("All 5 vs matched-vol BTC+cash (IS):\n\n| signal | BTC frac | excess ann ret | 95% CI | dom. ret | dom. DD |\n|---|---|---|---|---|---|")
    for k, m in o["main_null_all"].items():
        A(f"| {k} | {m['btc_fraction_matched']:.2f} | {f(m['excess_ann_ret'])} | [{f(m['excess_ret_ci95'][0])},{f(m['excess_ret_ci95'][1])}] | {m['dominates_return']} | {m['dominates_maxdd']} |")
    A(f"\n## 3. maxDD (point 3)\n{b} maxDD {f(rb['maxdd'])} vs BTC {f(o['btc_is']['maxdd'])}: ratio {v['3_maxdd_ratio']:.2f} (threshold 0.75). Counts only if point 1 holds: **{v['3_maxdd<=0.75x_counts_only_if_1']}**.\n")
    c = o["cv"]; d = o["dsr"]
    A(f"## Purged k-fold (k=5, embargo 2%) on IS, {b}\nSignals have no fitted parameters, so folds give OOS-style consistency: dSharpe vs BTC per fold " + ", ".join(f"{x['diff']:+.2f}" for x in c["folds"]) + f" ({c['n_pos']}/5 positive, mean {c['mean_diff']:+.2f}). DSR (n_trials=5) = {d['dsr']:.3f} (SR* annual-eq {d['sr_star']*math.sqrt(ANN):.2f}); PSR vs 0 = {d['psr']:.3f}. BTC B&H DSR (n_trials=1) = {o['dsr_btc_n1']['dsr']:.3f}.\n")
    h = o["holdout"]["best"]
    A("## 4. Holdout (last 20%, selected signal evaluated once)\n\n| | ann ret | vol | Sharpe | maxDD | flips/yr |\n|---|---|---|---|---|---|")
    A(f"| BTC | {f(h['btc']['ann_ret'])} | {f(h['btc']['vol'])} | {h['btc']['sharpe']:.2f} | {f(h['btc']['maxdd'])} | - |")
    A(f"| {b} | {f(h['timing']['ann_ret'])} | {f(h['timing']['vol'])} | {h['timing']['sharpe']:.2f} | {f(h['timing']['maxdd'])} | {h['timing']['turnover_per_year']:.2f} |")
    hm = h["main_null"]
    A(f"\nHO dSharpe {h['sharpe_diff']:+.2f}, JKM p {h['jkm_p']:.3f}, boot95 [{h['boot_ci95'][0]:+.2f},{h['boot_ci95'][1]:+.2f}]; vs matched-vol BTC+cash (frac {hm['btc_fraction_matched']:.2f}) excess {f(hm['excess_ann_ret'])} CI [{f(hm['excess_ret_ci95'][0])},{f(hm['excess_ret_ci95'][1])}]. Sign consistent (dSharpe>0): **{v['4_holdout_sign_consistent']}**.\n")
    A("## 5. Breadth, years, regimes, ex-2022 (selected signal; full eval window, info - selection not isolated)\n")
    A("Full window, all signals:\n\n" + hdr + " dSharpe vs BTC | JKM p | boot95 CI |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    A(tr("BTC B&H", o["btc_full"], " - | - | - |"))
    for k, dd_ in o["full_window"].items(): A(tr(k, dd_, f" {dd_['sharpe_diff']:+.2f} | {dd_['jkm_p']:.3f} | [{dd_['boot_ci95'][0]:+.2f},{dd_['boot_ci95'][1]:+.2f}] |"))
    A(f"\nBy year ({b}):\n\n| year | timing ret | BTC ret | timing Sharpe | BTC Sharpe | timing maxDD | BTC maxDD | flips | in-mkt |\n|---|---|---|---|---|---|---|---|---|")
    for y, r in o["by_year"].items():
        A(f"| {y} | {f(r['timing_ret'])} | {f(r['btc_ret'])} | {r['timing_sharpe']:.2f} | {r['btc_sharpe']:.2f} | {f(r['timing_maxdd'])} | {f(r['btc_maxdd'])} | {r['flips']} | {f(r['in_mkt'],0)} |")
    A("\nRegime (ex-post label: bear = BTC >30% below running ATH close; used for decomposition only):\n\n| regime | days | timing ann ret | BTC ann ret | timing sum log-ret | BTC sum log-ret | in-mkt |\n|---|---|---|---|---|---|---|")
    for k, r in o["by_regime"].items():
        A(f"| {k} | {r['n']} | {f(r['timing_ann_ret'])} | {f(r['btc_ann_ret'])} | {r['timing_sum_logret']:+.2f} | {r['btc_sum_logret']:+.2f} | {f(r['in_mkt'],0)} |")
    x, xi = o["excl_2022_full"], o["excl_2022_IS"]
    A(f"\nExcluding 2022 (full window): timing Sharpe {x['timing']['sharpe']:.2f} / maxDD {f(x['timing']['maxdd'])} vs BTC {x['btc']['sharpe']:.2f} / {f(x['btc']['maxdd'])}; dSharpe {x['sharpe_diff']:+.2f}, JKM p {x['jkm_p']:.3f}, boot95 [{x['boot_ci95'][0]:+.2f},{x['boot_ci95'][1]:+.2f}]. (IS ex-2022: dSharpe {xi['sharpe_diff']:+.2f}, p {xi['jkm_p']:.3f}.) "
      f"2022 alone: timing Sharpe {x['y2022_timing']['sharpe']:.2f}, ret(ann) {f(x['y2022_timing']['ann_ret'])} vs BTC {x['y2022_btc']['sharpe']:.2f}, {f(x['y2022_btc']['ann_ret'])}. Point 5 passed: **{v['5_not_one_signal_or_one_crash']}**.\n")
    ws = o["whipsaw"]
    A(f"## 6. Whipsaw ({b})\nTotal: {ws['all']['n_trades']} round trips over {w['n']/365:.1f}y, win rate {f(ws['all']['win_rate'],0)}, median hold {ws['all']['median_days']:.0f}d, trips <=30d: {ws['all']['short_trades_le30d']}; cost drag {ws['cost_total_bp_per_year']:.1f}bp/yr.\n")
    for k in ("y2019", "y2022"):
        t = ws[k]; A(f"- entries in {k[1:]}: {t['n_trades']} trades, win rate {f(t['win_rate'],0) if t['win_rate'] is not None else 'n/a'}, sum pnl {f(t['sum_pnl'])}, <=30d trips {t['short_trades_le30d']}")
    for k, r in ws["sideways"].items(): A(f"- {k}: timing {f(r['timing_ret'])} vs BTC {f(r['btc_ret'])}, flips {r['flips']}, BTC high/low range {f(r['btc_range_hi_lo'],0)}")
    A("## Cost stress (one-way cost; dSharpe vs B&H at same cost; selection fixed from primary)\n\n| cost | " + " | ".join(f"{k} IS/HO/full" for k in SIGS) + " |\n|---|" + "---|" * len(SIGS))
    for cb_, r in o["cost_stress"].items():
        A(f"| {cb_} | " + " | ".join(f"{r[k]['is_dsharpe']:+.2f}/{r[k]['ho_dsharpe']:+.2f}/{r[k]['full_dsharpe']:+.2f}" for k in SIGS) + " |")
    A("""
## Lookahead self-audit
- Signals (SMA/ROC) use close_t and earlier only; `pos = signal.shift(1)`; trade executes at OPEN of t+1 (ret_d = prev*(o_d/c_{d-1}-1) + new*(c_d/o_d-1) - cost*|dpos|), so no same-close entry; flat-to-in day earns only close/open of the entry day.
- Cost 4.5bp taker + 0.5bp floor per flip (see stress table), charged on every flip incl. initial entry; B&H pays one initial cost.
- Selection of best signal uses IS Sharpe only (first 80%); holdout evaluated once for the chosen signal (other signals shown for display, not used). Full-window / by-year / ex-2022 tables are informational (selection not isolated).
- Purged k-fold (k=5, 2% embargo) on IS; signals have no fitted parameters, so purge matters only for DSR/consistency. DSR with n_trials=5.
- Warmup 365d dropped for all strategies so every signal is defined from day 1; rolling windows are trailing. Regime labels are ex-post (decomposition only, not traded).
- Data: spot BTCUSDT; no funding; cash 0%. Bootstrap block 10d, 2000 resamples, JKM-HAC (Ledoit-Wolf) identical to overlay_runner.
""")
    (OUT / "btc_timing.md").write_text("\n".join(L))

if __name__ == "__main__": main()
