# BTC in/out timing - result

Frozen spec: research/PREREG_BTCTIMING.md. 5 signals, n_trials=5. BTCUSDT SPOT daily, rf=0. Signal on close t, shift(1), trade at next OPEN on flips only. One-way cost 5.00bp (PRIMARY: taker 4.5 + 0.5bp half-spread floor, per the spec's 'impact ~0 for BTC'. NOTE costs.py's sqrt-impact stub taken literally gives 129bp one-way for $1M vs BTC ADV, which is unrealistic for BTC; shown as a stress below). Common eval window 2018-08-18..2026-10-19 (n=2985) after a 366d warmup (needed by tsmom365; applied to all 5 + B&H). IS n=2388 (..2025-03-01), HO n=597.

## OVERALL: **NOT CONFIRMED**

Data sanity: spot 2017-08-17..2026-10-19 n=3351; vs perp klines_1d (overlap n=2599 from 2019-09-08): median |close diff| 4.6bp, p99 14.7bp, max 176.4bp; daily-return corr 0.9998.

## 1. IS table (selection window)

| strategy | ann ret | CAGR | vol | Sharpe | maxDD | #entries | flips/yr | time in mkt | dSharpe vs BTC | JKM p | p x5 | boot95 CI | boot99 CI (x5) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BTC B&H | 60.9% | 48.1% | 65.2% | 0.93 | -76.6% | 1 | 0.15 | 100% | - | - | - | - | - |
| SMA100 **(best)** | 60.2% | 63.8% | 46.8% | 1.29 | -38.1% | 43 | 13.14 | 58% | +0.35 | 0.223 | 1.000 | [-0.18,+0.93] | [-0.35,+1.11] |
| SMA200 | 48.0% | 44.8% | 46.8% | 1.02 | -63.7% | 22 | 6.57 | 58% | +0.09 | 0.753 | 1.000 | [-0.47,+0.63] | [-0.63,+0.82] |
| tsmom90 | 47.8% | 42.1% | 49.6% | 0.97 | -66.3% | 50 | 15.28 | 59% | +0.03 | 0.911 | 1.000 | [-0.51,+0.61] | [-0.67,+0.76] |
| tsmom180 | 43.0% | 36.4% | 49.0% | 0.88 | -64.0% | 22 | 6.57 | 60% | -0.06 | 0.835 | 1.000 | [-0.64,+0.48] | [-0.83,+0.69] |
| tsmom365 | 55.5% | 49.0% | 55.3% | 1.00 | -63.3% | 12 | 3.52 | 69% | +0.07 | 0.763 | 1.000 | [-0.37,+0.52] | [-0.53,+0.68] |

Best on IS Sharpe: **SMA100**. Signals beating BTC IS Sharpe: **4/5**.

## 2. Points 1/2: Sharpe edge and MAIN NULL (IS, SMA100)

dSharpe = +0.35; JKM-HAC p raw 0.223, Bonferroni x5 1.000; bootstrap 95% CI [-0.18,+0.93], Bonferroni-99% CI [-0.35,+1.11]. Significant (Bonf): **False**; raw: False.

| | ann ret | vol | Sharpe | maxDD |
|---|---|---|---|---|
| SMA100 | 60.2% | 46.8% | 1.29 | -38.1% |
| BTC x 0.72 + cash (matched vol) | 43.7% | 46.8% | 0.93 | -63.1% |

Excess ann. return vs matched-vol BTC+cash 16.5%, 95% boot CI [-7.7%,41.8%]; dominates on return True, on maxDD True. MAIN-NULL (not dilution) passed: **False**.

All 5 vs matched-vol BTC+cash (IS):

| signal | BTC frac | excess ann ret | 95% CI | dom. ret | dom. DD |
|---|---|---|---|---|---|
| SMA100 | 0.72 | 16.5% | [-7.7%,41.8%] | True | True |
| SMA200 | 0.72 | 4.2% | [-21.1%,29.7%] | True | False |
| tsmom90 | 0.76 | 1.5% | [-25.7%,27.4%] | True | False |
| tsmom180 | 0.75 | -2.9% | [-28.9%,24.7%] | False | True |
| tsmom365 | 0.85 | 3.8% | [-22.1%,30.5%] | True | True |

## 3. maxDD (point 3)
SMA100 maxDD -38.1% vs BTC -76.6%: ratio 0.50 (threshold 0.75). Counts only if point 1 holds: **False**.

## Purged k-fold (k=5, embargo 2%) on IS, SMA100
Signals have no fitted parameters, so folds give OOS-style consistency: dSharpe vs BTC per fold +0.97, +0.03, +0.38, -0.04, -0.24 (3/5 positive, mean +0.22). DSR (n_trials=5) = 0.984 (SR* annual-eq 0.46); PSR vs 0 = 1.000. BTC B&H DSR (n_trials=1) = 0.991.

## 4. Holdout (last 20%, selected signal evaluated once)

| | ann ret | vol | Sharpe | maxDD | flips/yr |
|---|---|---|---|---|---|
| BTC | 6.9% | 43.3% | 0.16 | -53.0% | - |
| SMA100 | 13.5% | 22.5% | 0.60 | -23.8% | 10.39 |

HO dSharpe +0.44, JKM p 0.494, boot95 [-0.84,+1.68]; vs matched-vol BTC+cash (frac 0.52) excess 10.0% CI [-17.6%,38.1%]. Sign consistent (dSharpe>0): **True**.

## 5. Breadth, years, regimes, ex-2022 (selected signal; full eval window, info - selection not isolated)

Full window, all signals:

| strategy | ann ret | CAGR | vol | Sharpe | maxDD | #entries | flips/yr | time in mkt | dSharpe vs BTC | JKM p | boot95 CI |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BTC B&H | 50.1% | 36.2% | 61.4% | 0.82 | -76.6% | 1 | 0.12 | 100% | - | - | - |
| SMA100 | 50.9% | 51.7% | 43.1% | 1.18 | -38.1% | 52 | 12.59 | 55% | +0.37 | 0.159 | [-0.14,+0.89] |
| SMA200 | 40.1% | 35.8% | 43.5% | 0.92 | -63.7% | 31 | 7.46 | 55% | +0.11 | 0.685 | [-0.43,+0.62] |
| tsmom90 | 39.0% | 32.8% | 45.4% | 0.86 | -66.3% | 54 | 13.08 | 56% | +0.04 | 0.863 | [-0.45,+0.57] |
| tsmom180 | 38.8% | 32.8% | 45.9% | 0.85 | -64.0% | 27 | 6.48 | 58% | +0.03 | 0.903 | [-0.48,+0.51] |
| tsmom365 | 46.0% | 38.6% | 51.0% | 0.90 | -63.3% | 13 | 3.18 | 64% | +0.09 | 0.693 | [-0.34,+0.53] |

By year (SMA100):

| year | timing ret | BTC ret | timing Sharpe | BTC Sharpe | timing maxDD | BTC maxDD | flips | in-mkt |
|---|---|---|---|---|---|---|---|---|
| 2018 | -6.1% | -43.7% | -0.98 | -2.02 | -9.6% | -56.4% | 4 | 7% |
| 2019 | 135.0% | 94.3% | 1.79 | 1.31 | -28.2% | -49.4% | 8 | 54% |
| 2020 | 170.2% | 302.0% | 2.19 | 2.25 | -24.6% | -53.6% | 15 | 82% |
| 2021 | 78.8% | 59.8% | 1.22 | 0.98 | -35.7% | -53.1% | 13 | 69% |
| 2022 | -20.5% | -64.2% | -1.38 | -1.29 | -28.9% | -66.9% | 8 | 7% |
| 2023 | 83.8% | 155.6% | 1.69 | 2.35 | -26.3% | -20.0% | 13 | 76% |
| 2024 | 66.5% | 121.3% | 1.35 | 1.76 | -35.6% | -26.2% | 18 | 76% |
| 2025 | 5.8% | -6.3% | 0.35 | 0.05 | -17.4% | -32.0% | 19 | 54% |
| 2026 | 9.9% | -5.8% | 0.65 | 0.06 | -13.2% | -39.5% | 5 | 36% |

Regime (ex-post label: bear = BTC >30% below running ATH close; used for decomposition only):

| regime | days | timing ann ret | BTC ann ret | timing sum log-ret | BTC sum log-ret | in-mkt |
|---|---|---|---|---|---|---|
| bull(DD>-30%) | 1491 | 91.3% | 109.1% | +3.16 | +3.75 | 72% |
| bear(DD<=-30%) | 1494 | 10.5% | -8.8% | +0.24 | -1.22 | 38% |

Excluding 2022 (full window): timing Sharpe 1.34 / maxDD -35.7% vs BTC 1.12 / -63.3%; dSharpe +0.22, JKM p 0.404, boot95 [-0.29,+0.74]. (IS ex-2022: dSharpe +0.16, p 0.575.) 2022 alone: timing Sharpe -1.38, ret(ann) -21.6% vs BTC -1.29, -82.1%. Point 5 passed: **True**.

## 6. Whipsaw (SMA100)
Total: 52 round trips over 8.2y, win rate 23%, median hold 6d, trips <=30d: 38; cost drag 63.0bp/yr.

- entries in 2019: 4 trades, win rate 25%, sum pnl 146.2%, <=30d trips 3
- entries in 2022: 4 trades, win rate 0%, sum pnl -22.1%, <=30d trips 4
- 2019 range: timing 135.0% vs BTC 94.3%, flips 8, BTC high/low range 285%
- 2022 chop: timing -20.5% vs BTC -64.2%, flips 8, BTC high/low range 202%
## Cost stress (one-way cost; dSharpe vs B&H at same cost; selection fixed from primary)

| cost | SMA100 IS/HO/full | SMA200 IS/HO/full | tsmom90 IS/HO/full | tsmom180 IS/HO/full | tsmom365 IS/HO/full |
|---|---|---|---|---|---|
| 5.0bp | +0.35/+0.44/+0.37 | +0.09/+0.16/+0.11 | +0.03/+0.01/+0.04 | -0.06/+0.58/+0.03 | +0.07/+0.12/+0.09 |
| 10.0bp | +0.34/+0.42/+0.35 | +0.08/+0.14/+0.10 | +0.02/-0.00/+0.03 | -0.06/+0.57/+0.02 | +0.07/+0.11/+0.08 |
| 25.0bp | +0.30/+0.35/+0.31 | +0.06/+0.07/+0.07 | -0.03/-0.03/-0.01 | -0.08/+0.54/+0.00 | +0.06/+0.10/+0.07 |
| 128.7bp | +0.00/-0.13/+0.00 | -0.08/-0.36/-0.11 | -0.35/-0.23/-0.31 | -0.22/+0.33/-0.14 | -0.01/+0.04/+0.01 |

## Lookahead self-audit
- Signals (SMA/ROC) use close_t and earlier only; `pos = signal.shift(1)`; trade executes at OPEN of t+1 (ret_d = prev*(o_d/c_{d-1}-1) + new*(c_d/o_d-1) - cost*|dpos|), so no same-close entry; flat-to-in day earns only close/open of the entry day.
- Cost 4.5bp taker + 0.5bp floor per flip (see stress table), charged on every flip incl. initial entry; B&H pays one initial cost.
- Selection of best signal uses IS Sharpe only (first 80%); holdout evaluated once for the chosen signal (other signals shown for display, not used). Full-window / by-year / ex-2022 tables are informational (selection not isolated).
- Purged k-fold (k=5, 2% embargo) on IS; signals have no fitted parameters, so purge matters only for DSR/consistency. DSR with n_trials=5.
- Warmup 365d dropped for all strategies so every signal is defined from day 1; rolling windows are trailing. Regime labels are ex-post (decomposition only, not traded).
- Data: spot BTCUSDT; no funding; cash 0%. Bootstrap block 10d, 2000 resamples, JKM-HAC (Ledoit-Wolf) identical to overlay_runner.
