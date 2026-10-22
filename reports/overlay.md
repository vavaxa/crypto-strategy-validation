# Carry as overlay to BTC core - result

Frozen spec: research/PREREG_OVERLAY.md. Carry sleeve fixed `w7d|z|vt|1d` (net, impact_k=0.5, from carry_runner weights; not re-fit). BTC core = BTCUSDT daily close-to-close buy&hold (klines_1d), single initial purchase costed one-way: taker fee 4.5bp + sqrt-impact on $1M vs 30d ADV = 132.87bp total, applied to day-1 return (no funding: spot-style). Cash 0%. Eval window 2020-04-30..2026-10-18 after a 60d trailing-warmup (n=2363; IS n=1878 to 2025-06-20; HO n=485). n_trials=5.

## OVERALL: **NOT CONFIRMED**

## 1. Correlation BTC vs carry (daily)
full 0.629; IS 0.659; HO 0.522; on BTC-down days 0.524.

## 2. Five combinations, IS (selection window)

| combo | ann ret | CAGR | vol | Sharpe | maxDD | dSharpe vs BTC | JKM-HAC p | p x5 (Bonf) | boot 95% CI | boot 99% CI (x5) |
|---|---|---|---|---|---|---|---|---|---|---|
| BTC core | 66.1% | 61.4% | 60.3% | 1.10 | -76.7% | - | - | - | - | - |
| Carry sleeve | 14.0% | 12.8% | 19.6% | 0.71 | -39.7% | - | - | - | - | - |
| static_f0.5 | 40.0% | 39.2% | 37.4% | 1.07 | -60.3% | -0.02 | 0.813 | 1.000 | [-0.23,+0.19] | [-0.29,+0.23] |
| static_f0.7 | 50.5% | 48.8% | 46.3% | 1.09 | -67.5% | -0.01 | 0.901 | 1.000 | [-0.11,+0.10] | [-0.14,+0.12] |
| static_f0.9 | 60.9% | 57.5% | 55.6% | 1.09 | -73.8% | -0.00 | 0.961 | 1.000 | [-0.03,+0.03] | [-0.04,+0.03] |
| invvol_monthly | 28.3% | 28.0% | 26.8% | 1.06 | -49.7% | -0.04 | 0.857 | 1.000 | [-0.48,+0.42] | [-0.61,+0.51] |
| voltarget20 **(best IS)** | 25.0% | 25.5% | 21.1% | 1.18 | -38.7% | +0.09 | 0.579 | 1.000 | [-0.23,+0.41] | [-0.32,+0.55] |

Best on IS Sharpe: **voltarget20**.

## 3. MAIN NULL (point 2): combo vs BTC+cash at matched vol (IS, best combo)

| | ann ret | vol | Sharpe | maxDD |
|---|---|---|---|---|
| voltarget20 | 25.0% | 21.1% | 1.18 | -38.7% |
| BTC x 0.35 + cash | 23.1% | 21.1% | 1.10 | -36.6% |

Excess ann. return vs matched-vol BTC+cash: 1.8%, 95% boot CI [-4.9%, 8.8%]. Dominates on return: True; on maxDD: False.

All combos vs matched-vol BTC+cash (IS):

| combo | BTC frac | excess ann ret | 95% CI | dominates ret | dominates DD |
|---|---|---|---|---|---|
| static_f0.5 | 0.62 | -0.9% | [-8.1%,6.5%] | False | False |
| static_f0.7 | 0.77 | -0.3% | [-4.6%,4.1%] | False | False |
| static_f0.9 | 0.92 | -0.0% | [-1.5%,1.4%] | False | False |
| invvol_monthly | 0.44 | -1.0% | [-12.1%,10.7%] | False | False |
| voltarget20 | 0.35 | 1.8% | [-4.9%,8.8%] | True | False |

## 4. Six-point verdict (IS)

- **1_sharpe_gt_btc_significant**: FAIL  
  `{"raw_sig": false, "sharpe_diff": 0.08745803374791336, "jkm_p": 0.5788496183361889, "jkm_p_bonf5": 1.0, "boot_ci95": [-0.22932464078104653, 0.4051788522343396], "boot_ci_bonf5_99": [-0.3236597360367533, 0.5451469160433383]}`
- **2_MAIN_NULL_beats_btc_cash_not_dilution**: FAIL  
  `{"sharpe_diff": 0.08745803374791336, "btc_fraction_matched": 0.349920535200124, "excess_ann_ret": 0.01845742316488605, "excess_ret_ci95": [-0.04871266954885432, 0.08758496349888191], "dominates_return": true, "dominates_maxdd": false}`
- **3_maxdd_lower_return_ge_blend**: PASS  
  `{"combo_maxdd": -0.3872936676085593, "btc_maxdd": -0.7666956183209541, "ratio": 0.5051465775384547, "rule": "|DD|<=0.75*|DD_BTC| and return > matched-vol BTC+cash"}`
- **4_diversification_real**: FAIL  
  `{"corr": {"full": 0.6285136411739842, "is_": 0.6594766702277954, "ho": 0.5216229964316008, "down_days_corr": 0.5244264816369675}, "carry_mean_ann": 0.14004723840053365, "carry_mean_on_btc_down_days_ann": -1.7039096302131735, "carry_mean_on_btc_up_days_ann": 1.8920934842796013}`
- **5_holdout_supporting_forward_pending**: pending (holdout supporting=True; forward paper-trade pending)  
  `{"holdout_supporting_ok": true}`
- **6_cost_robust_sign**: FAIL  
  `{"sign_best_by_k": {"0.125": true, "0.25": true, "0.5": true, "1.0": false, "2.0": false}}`

## 5. Holdout (SUPPORTING only - carry's holdout was already seen in FORM-L; not decisive)

| | ann ret | vol | Sharpe | maxDD |
|---|---|---|---|---|
| BTC | -8.6% | 41.6% | -0.21 | -53.0% |
| Carry | 24.4% | 21.0% | 1.16 | -16.3% |
| static_f0.5 | 7.9% | 27.7% | 0.28 | -33.7% |
| static_f0.7 | 1.3% | 32.8% | 0.04 | -40.4% |
| static_f0.9 | -5.3% | 38.5% | -0.14 | -48.8% |
| invvol_monthly | 12.0% | 24.6% | 0.49 | -27.5% |
| voltarget20 (selected) | 3.2% | 21.5% | 0.15 | -28.3% |

Selected combo HO: dSharpe vs BTC +0.36, JKM p 0.242, boot CI [-0.21,+0.92]; vs matched-vol BTC+cash (frac 0.52) excess 7.7% CI [-4.5%,20.7%]. Forward paper-trade (decisive) is PENDING.

## 6. Cost robustness: dSharpe (combo - BTC) by impact_k (carry sleeve rebuilt per k)

| impact_k | carry IS Sharpe | static_f0.5 IS | static_f0.7 IS | static_f0.9 IS | invvol_monthly IS | voltarget20 IS | selected HO |
|---|---|---|---|---|---|---|---|
| 0.125 | 1.01 | +0.05 | +0.03 | +0.01 | +0.12 | +0.17 | +0.50 |
| 0.25 | 0.91 | +0.03 | +0.02 | +0.01 | +0.07 | +0.14 | +0.45 |
| 0.5 | 0.71 | -0.02 | -0.01 | -0.00 | -0.04 | +0.09 | +0.36 |
| 1.0 | 0.32 | -0.13 | -0.06 | -0.01 | -0.25 | -0.02 | +0.17 |
| 2.0 | -0.46 | -0.33 | -0.15 | -0.04 | -0.68 | -0.24 | -0.21 |

Sign of selected combo's IS improvement positive at all k: False.

## Full window (info only, selection not isolated)

| combo | Sharpe | maxDD | dSharpe vs BTC | JKM p |
|---|---|---|---|---|
| BTC | 0.89 | -76.7% | - | - |
| static_f0.5 | 0.94 | -60.3% | +0.05 | 0.602 |
| static_f0.7 | 0.92 | -67.5% | +0.03 | 0.522 |
| static_f0.9 | 0.90 | -73.8% | +0.01 | 0.472 |
| invvol_monthly | 0.95 | -49.7% | +0.06 | 0.775 |
| voltarget20 | 0.97 | -38.7% | +0.08 | 0.612 |

## Lookahead self-audit
- Vol/cov for invvol and vol-target are rolling(60) of daily returns then `.shift(1)`: weight on day t uses returns <= t-1. Monthly invvol takes the shifted weight of the first day of the month and holds it.
- Static and base 50/50 weights are constants; vol-target scale uses only trailing combo vol; no leverage (cap 1, rest cash 0%).
- Best combination chosen by IS Sharpe only (<= is_end); holdout touched once for the selected combo (plus display of the others, not used for choice). Holdout is not virgin for carry (FORM-L), so it is supporting.
- Carry sleeve NOT re-fit: weights come from `build_W(full ctx, w7d|z|vt|1d)` via carry_runner's cache (PIT universe, signals on t-1 info, trades at next open, ADV shift(1)); only `account(impact_k)` is re-run per k (weights do not depend on k). Note the sleeve itself was selected on IS in FORM-L (n=16 trials) - residual selection bias in the carry leg is NOT corrected here.
- BTC core: buy-and-hold, only day-1 purchase cost; no funding.
- Warmup: first 60 days dropped from all series (incl. BTC) so every combo has trailing stats.
- Underspecified choices fixed a priori: window 60d, daily rebalance to target weights, vol-target base 50/50, leverage cap 1, bootstrap block 10d, 2000 resamples, Bonferroni x5, 'substantially lower maxDD' = <=0.75x BTC maxDD.
