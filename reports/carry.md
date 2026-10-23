> **⚠️ CORRECTION (2026-10).** Scored with an uncalibrated impact stub (`impact_k=0.5`, ~20–30× too
> high; true `k≈Y·σ`~0.015–0.06). Net crosses zero at `impact_k≈0.031`; the swept grid (0.125–2) never
> reached it. Correct label: **INCONCLUSIVE (impact-calibration-dependent)**, not a confirmed fail. See
> repo README «Correction». Re-run with calibrated per-symbol `k` pending.

---

# FORM-L funding-carry study (PREREG_CARRY.md, frozen)

Generated 2026-10-19 14:42:17. Long-only: BUY low/negative trailing funding among PIT-liquid members. 16 configs, n_trials=16. Window 2020-03-01..2026-10-18 (2423 d); IS ..2025-06-20 (1938 d), forward holdout from 2025-06-21 (485 d, last 20%).

## OVERALL: **NOT CONFIRMED**

| # | Point | Status | Number |
|---|---|---|---|
| 1 | who_pays | **PASS** | mean realized carry 564 bps/yr, NW t=4.78, 95% CI [310,863] |
| 2 | dsr_pbo | **FAIL** | DSR=0.196 (p=0.804), PBO=0.000 |
| 3 | spa | **FAIL** | SPA p: BTC buy&hold 1.000, Naive EW (no selection) 1.000 |
| 4 | net_vs_bench | **FAIL** | best SR 0.64/CAGR 11.4% vs BTC 0.86/40.8%, naive 0.69/22.3%; gate: cost-robust (p4 invariant) |
| 5 | holdout_paper | **pending** | holdout component PASS (HO SR 1.16 vs BTC -0.30, naive 0.19); paper pending |
| 6 | tail | **FAIL** | LUNA DD -16.6%, FTX DD -11.9%, boot-1y maxDD p5 -34.5%, skew -0.52, exkurt 8.3 |
| 7 | bybit | **pending** | pending (Bybit replication, cloud) |
| 8 | capacity | **FAIL** | Sharpe 1M 0.64 -> 5M 0.15 -> 20M -0.75; last-2y beats naive: False |

## Universe and coverage

PIT top-30 by trailing-30d quote volume over all 689 USDT perps (incl. delisted), then intersected with the 77 symbols that have funding history. Mean members/day 29.6; mean members WITH funding 19.9 (67.2% of member-days; min 10). Members without funding cannot be traded here (carry universe is a subset of the PIT majors; the 77 were selected partly with today's volume, a residual selection bias that cannot be removed without funding for the other 612).

| year | members/day | with funding/day | coverage |
|---|---|---|---|
| 2020 | 26.9 | 16.4 | 61.1% |
| 2021 | 30.0 | 21.9 | 73.1% |
| 2022 | 30.0 | 21.3 | 70.8% |
| 2023 | 30.0 | 20.5 | 68.4% |
| 2024 | 30.0 | 19.7 | 65.7% |
| 2025 | 30.0 | 18.5 | 61.8% |
| 2026 | 30.0 | 20.5 | 68.2% |

## All 16 configs (IS, net of costs, impact_k=0.5, $1M)

OOF Sharpe = mean over purged 5-fold (embargo 2%). carry = realized funding cashflow (bps of equity/yr, + = received). price = arithmetic price P&L %/yr. cost = fees+impact %/yr.

| config | OOF SR | IS SR | net CAGR | maxDD | carry bps/yr | price %/yr | cost %/yr | turn/yr | gross expo |
|---|---|---|---|---|---|---|---|---|---|
| w3d|quint|eq|8h | -1.08 | -1.02 | -43.7% | -95.3% | 802 | 35.5 | 91.59 | 88.9 | 0.44 |
| w3d|quint|eq|1d | -0.52 | -0.50 | -28.8% | -89.9% | 775 | 32.8 | 65.12 | 62.7 | 0.44 |
| w3d|quint|vt|8h | -1.19 | -1.25 | -25.4% | -79.1% | 320 | 17.5 | 47.81 | 53.2 | 0.25 |
| w3d|quint|vt|1d | -0.53 | -0.58 | -13.9% | -60.9% | 311 | 17.9 | 33.82 | 37.6 | 0.25 |
| w3d|z|eq|8h | 0.12 | 0.13 | -5.7% | -73.8% | 575 | 47.8 | 48.71 | 68.2 | 0.43 |
| w3d|z|eq|1d | 0.29 | 0.29 | 1.9% | -72.2% | 550 | 54.1 | 46.86 | 55.0 | 0.43 |
| w3d|z|vt|8h | 0.27 | 0.21 | 2.1% | -44.4% | 620 | 14.5 | 16.76 | 31.6 | 0.20 |
| w3d|z|vt|1d | 0.29 | 0.21 | 2.2% | -45.0% | 596 | 15.4 | 17.37 | 26.6 | 0.21 |
| w7d|quint|eq|8h | -0.23 | -0.23 | -19.7% | -85.1% | 775 | 32.2 | 52.39 | 51.0 | 0.44 |
| w7d|quint|eq|1d | 0.01 | 0.01 | -10.0% | -80.8% | 747 | 32.5 | 41.06 | 38.6 | 0.44 |
| w7d|quint|vt|8h | -0.27 | -0.31 | -8.7% | -52.4% | 310 | 17.1 | 27.20 | 31.1 | 0.25 |
| w7d|quint|vt|1d | 0.03 | -0.02 | -2.6% | -47.4% | 296 | 17.7 | 21.16 | 23.4 | 0.25 |
| w7d|z|eq|8h | 0.54 | 0.51 | 13.3% | -71.0% | 569 | 40.9 | 23.75 | 35.3 | 0.42 |
| w7d|z|eq|1d | 0.56 | 0.53 | 14.9% | -70.3% | 554 | 43.5 | 24.65 | 30.6 | 0.42 |
| w7d|z|vt|8h | 0.67 | 0.61 | 10.7% | -39.2% | 573 | 14.5 | 8.26 | 16.3 | 0.20 |
| w7d|z|vt|1d **(best)** | 0.71 | 0.64 | 11.4% | -39.7% | 564 | 15.6 | 8.66 | 14.6 | 0.20 |
| BENCH BTC buy&hold | - | 0.86 | 40.8% | -78.9% | -1273 | 66.0 | 0.00 | 0.0 | 1.00 |
| BENCH Naive EW (no selection) | - | 0.69 | 22.3% | -85.1% | -1010 | 77.6 | 8.65 | 8.2 | 1.01 |
| BENCH Naive vol-targeted (diagnostic) | - | 0.69 | 13.6% | -36.4% | -212 | 18.8 | 1.62 | 3.2 | 0.27 |

## Decision rule, point by point (best config `w7d|z|vt|1d` chosen by OOF Sharpe)

1. **Who pays**: mean realized funding cashflow 564 bps/yr (NW t=4.78; bootstrap 95% CI [310,863]) -> PASS. Versus naive no-selection basket: 1574 bps/yr (NW t=8.62). Carry per unit notional: strategy 28.07%/yr vs naive -10.02%/yr (negative = longs pay).
2. **DSR/PBO**: DSR=0.196, p=0.804 (deflated bench SR* 0.053 daily), PBO=0.000 -> FAIL.
3. **SPA** (all 16 configs vs benchmark): BTC buy&hold: SPA p=1.000, WRC p=0.961; Naive EW (no selection): SPA p=1.000, WRC p=0.974; diagnostic vs vol-targeted naive: SPA p=0.484 -> FAIL.
4. **Net vs benchmarks** (IS, base costs): best SR 0.64, CAGR 11.4%, maxDD -39.7%; BTC 0.86/40.8%/-78.9%; naive 0.69/22.3%/-85.1% -> FAIL (requires SR and CAGR above both).
5. **Holdout + paper**: holdout component PASS; paper-trade pending (forward) -> overall pending, NOT PASS.
6. **Tail**: see section below -> FAIL.
7. **Bybit replication**: pending (cloud).
8. **Capacity**: see section below -> FAIL.

## Cost gate (impact_k sweep x0.25..x4 of 0.5)

Best config re-selected at each impact_k; point-4 requires best SR and CAGR above BTC and naive (IS).

| impact_k | best cfg | SR | CAGR | BTC SR/CAGR | naive SR/CAGR | P4 | DSR p | PBO | SPA BTC | SPA naive |
|---|---|---|---|---|---|---|---|---|---|---|
| 0.125 | w7d|z|vt|1d | 0.95 | 18.3% | 0.86/40.8% | 0.76/30.1% | FAIL | 0.088 | 0.108 | 1.000 | 1.000 |
| 0.25 | w7d|z|vt|1d | 0.85 | 16.0% | 0.86/40.8% | 0.74/27.5% | FAIL | 0.266 | 0.028 | 1.000 | 1.000 |
| 0.5 | w7d|z|vt|1d | 0.64 | 11.4% | 0.86/40.8% | 0.69/22.3% | FAIL | 0.804 | 0.000 | 1.000 | 1.000 |
| 1.0 | w7d|z|vt|1d | 0.24 | 2.9% | 0.86/40.8% | 0.60/12.5% | FAIL | 1.000 | 0.000 | 1.000 | 1.000 |
| 2.0 | w7d|z|vt|8h | -0.52 | -11.7% | 0.86/40.8% | 0.41/-4.7% | FAIL | 1.000 | 0.000 | 1.000 | 1.000 |

Point-4 invariant across all five: **True** -> label: **cost-robust (p4 invariant)**. Best config changes with impact_k: True. Path (a) (real fills / paper) not available here. Note: 'cost-robust' only says the point-4 verdict does not depend on impact_k; if it is FAIL everywhere, the edge is simply not there.

## Holdout (best config evaluated once, impact_k=0.5)

| series | IS SR | IS CAGR | IS maxDD | HO SR | HO CAGR | HO maxDD | HO carry bps/yr | IS carry bps/yr |
|---|---|---|---|---|---|---|---|---|
| best | 0.64 | 11.4% | -39.7% | 1.16 | 24.9% | -16.3% | 782 | 564 |
| btc | 0.86 | 40.8% | -78.9% | -0.30 | -19.2% | -53.7% | -404 | -1273 |
| naive | 0.69 | 22.3% | -85.1% | 0.19 | -12.0% | -71.4% | 327 | -1010 |

HO Sharpe 95% bootstrap CI [-0.47, 2.73]; HO carry NW t=3.31. same-sign: True, beats both benchmarks: True, IS Sharpe inside HO CI: True.

## Tail (point 6)

A-priori limits (not in PREREG, fixed here): stress-window maxDD <= 15.0%; 1y bootstrap 5th-pct maxDD >= -35.0%; short-vol flag if skew < -1 or excess kurtosis > 10.

| window | series | maxDD | cum ret | worst day |
|---|---|---|---|---|
| LUNA | best | -16.6% | -16.6% | -7.8% |
| LUNA | btc | -20.3% | -19.0% | -11.7% |
| LUNA | naive | -48.7% | -46.0% | -26.5% |
| LUNA | best avg gross exposure | 0.14 | | |
| FTX | best | -11.9% | -7.4% | -7.5% |
| FTX | btc | -25.3% | -21.6% | -14.1% |
| FTX | naive | -33.3% | -27.3% | -18.7% |
| FTX | best avg gross exposure | 0.18 | | |

Bootstrap (stationary, 1y paths, 1000): maxDD median -16.1%, 5th pct -34.5%, 1st pct -41.3% (BTC 5th pct -70.6%). Daily skew -0.52, excess kurtosis 8.3, worst day -8.6% (-8.3 sigma), 1% ES -4.2% (-4.0 sigma). Carry share of net P&L 44.0%. Hidden short-vol flag: **False**. This book is long-only price exposure, so its left tail is mostly directional beta, not a sold-straddle payoff; the carry share and benchmark comparison show how much of the result is carry versus beta.

## Capacity (point 8)

Impact = k*sqrt(trade/ADV30d), k=0.5; target book fixed a priori at $5M.

| book $ | SR | CAGR | cost %/yr | BTC SR | naive SR |
|---|---|---|---|---|---|
| 0.1M | 0.92 | 17.7% | 3.19 | 0.86 | 0.75 |
| 1M | 0.64 | 11.4% | 8.66 | 0.86 | 0.69 |
| 5M | 0.15 | 0.9% | 18.54 | 0.86 | 0.57 |
| 20M | -0.75 | -15.6% | 36.43 | 0.86 | 0.37 |
| 50M | -1.74 | -31.6% | 57.21 | 0.86 | 0.13 |

Capacity prong (SR@5M >= 0.5*SR@1M and > both benchmarks at 5M): False. Decay prong (last two years strategy return > 0 and > naive): False.

| year | days | SR | strategy carry bps/yr | strategy ret | naive ret | mean member funding bps/yr (paid by longs) |
|---|---|---|---|---|---|---|
| 2020 | 306 | 0.35 | 124 | 4.4% | 61.9% | 1896 |
| 2021 | 365 | 2.93 | 42 | 76.8% | 423.2% | 3608 |
| 2022 | 365 | -1.91 | 1058 | -37.1% | -81.5% | -859 |
| 2023 | 365 | 2.01 | 1355 | 40.7% | 132.8% | -202 |
| 2024 | 366 | 1.08 | 303 | 20.3% | 20.2% | 985 |
| 2025 | 365 | -0.93 | 321 | -15.8% | -55.1% | 66 |
| 2026 | 291 | 2.14 | 1063 | 44.2% | 24.7% | -672 |

Spearman(year, strategy carry) = 0.57 (p=0.18); Spearman(year, mean member funding) = -0.50 (p=0.25). Falling member funding with a falling strategy edge would be consistent with an arbitrageable premium; a flat/rising edge would not.

## A-priori choices for underspecified items (fixed before results; not searched)

- Time base 8h bars aligned to funding (from 1h klines), results aggregated to UTC days (mech_runner stats, ANN=365). 8h rebalance = decide every bar; daily = decide at the 00:00 UTC bar only.
- target_vol 0.20 via trailing-90-bar book vol, gross <= 1 (no leverage), cap 10%/coin applied after scaling (equal-weight quintile therefore holds ~ceil(0.2n)*10% gross; z-tilt weight ~ max(-z,0)).
- No-trade band: skip per-coin changes with |target-held| <= 20% of max(target, held); entries/exits always trade. Min 10 eligible members else flat. Funding eligibility: >=80% of expected events in the window.
- Costs: taker 4.5 bp + max(0.5 bp, k*sqrt(trade/ADV30d)) on |dW| at open, capital $1M (mech_runner convention). No borrow (long-only). costs.py participation cap not applied (mech_runner convention).
- P6 limits and P8 target book: see Tail/Capacity sections.
- Benchmarks: BTC buy&hold pays funding too; naive = all eligible PIT members equal weight (cap 10%), daily rebalance with same band, same costs, no selection. A vol-targeted naive is a diagnostic only.

## LOOKAHEAD SELF-AUDIT (carry-specific)

| Risk | Prevention |
|---|---|
| Funding as-of timing | Decision for bar k (made at close of bar k-1 = open instant of bar k) uses only funding events with ts strictly < that instant: bins <= k-1 via `.shift(1)` after the rolling sum; the event stamped exactly at the instant is excluded. Timestamps rounded to the minute (ms jitter). |
| Trailing-window shift | Rolling 9/21 bins (3d/7d) computed on the event series then shifted by one bar; features never include bar k. Eligibility requires >=80% of expected events in the window (no zero-fill of missing history). Vol inputs use returns through bar k-1 (shifted). |
| Entry at open | Weight row k is traded at O_k: price P&L = W_{k-1}*(O_k/C_{k-1}-1) + W_k*(C_k/O_k-1); costs on |dW| at open using ADV shift(1). |
| Realized funding booking | Real funding events, not averages: events stamped exactly at bar open (settlement instant) are charged on the PRE-trade weight W_{k-1} (a same-instant trade cannot avoid or capture that payment); events inside the bar on W_k. Long pays when rate>0, receives when <0. |
| Universe ranking trailing | Daily top-30 by trailing-30d mean quote volume (rolling, row i uses days <= i), membership for bars of day D taken from the close of D-1; delisted symbols kept until delivery; ranked over all 689, then intersected with funded symbols. Not the selected.json ranking (today's volume). |
| Holdout isolation | A separate `Ctx(end=last IS day)` is built; all 16 configs, benchmarks, OOF, DSR/PBO/SPA, cost gate and capacity are computed on it. The full context is used only after `best` is fixed. Empirical check: max abs weight difference on IS rows between full and IS contexts = 0.00e+00 (weight on symbols absent from IS ctx: 0.00e+00). Residual: the cost gate re-selects `best` per impact_k; only the impact_k=0.5 best is evaluated on the holdout. |
| Embargo / CV | `purged_kfold(k=5, embargo=2%)` via mech_runner.oof_table on IS daily returns; best by mean OOF Sharpe; n_trials=16 in DSR and the PBO matrix has exactly the 16 configs. Rules have no fitted parameters, so purging only guards serial dependence. |
| Residual risks | (1) the 77 funded symbols were chosen with today's volume (survivor tilt; see coverage); (2) evaluation start uses a data-count fact, not performance; (3) no L2: impact is the k*sqrt placeholder (hence cost gate); (4) intra-holding weight drift ignored (constant-weight convention shared with mech_runner). |