> **⚠️ CORRECTION (2026-10).** Scored with an uncalibrated impact stub (`impact_k=0.5`, ~20–30× too
> high; true `k≈Y·σ`~0.015–0.06). Net crosses zero at `impact_k≈0.031`; the swept grid (0.125–2) never
> reached it. Correct label: **INCONCLUSIVE (impact-calibration-dependent)**, not a confirmed fail. See
> repo README «Correction». Re-run with calibrated per-symbol `k` pending.

---

# Mechanism study: trend/breakout on Binance USDT-perps (daily)

Generated 2026-10-19 11:04 UTC by `research/mech_runner.py`. Pre-registration frozen; grid/decision rule unchanged.

## Overall: **NOT CONFIRMED** (edge not confirmed; point 7 was not run and points below decide the rest)

## (a) Universe

* Point-in-time **top-N = 30** USDT-perps by trailing 30-day mean quote volume, ranked at every daily close using only days <= t from `klines_1d_binance` (689 symbols incl. 75+ delisted). Same N for every config, benchmark and window.
* WHY N=30: chosen a priori (before any result) as the 'liquid majors' scale: in 2021-2026 the 30th-ranked coin still trades a median $157M/day (median across days of the rank-30 trailing volume, IS), so a $1M book is <<10% of volume; larger N would pull in mid-caps whose impact is exactly the uncalibrated part of the cost model. Not tuned.
* Eligibility on day t: is_usdt_perp, bar exists with volume>0, t < delivery_ts, >= 30 days of history; pegged/stable bases excluded (`['AEUR', 'BUSD', 'DAI', 'EUR', 'FDUSD', 'PAXG', 'TUSD', 'USDC', 'USDE', 'USDP', 'XAUT']`). Delisted symbols stay members until their last bar (delivery_ts / last archive bar).
* Evaluation starts 2020-02-18 (first day with >= 10 members; early history has <30 listed perps so universe < N). Window 2020-02-18..2026-10-18 (2435 days; last partial bar dropped). In-sample (IS) 2020-02-18..2025-06-18 (1948 d); forward holdout 2025-06-19..2026-10-18 (487 d, last 20%).
* Ever-member symbols: IS 271, full 381. Rebrands (MATIC->POL, MKR->SKY...) are separate symbols (not stitched).
* Coverage of member symbol-days (IS): real funding 67.3% (full sample 67.2%); OI history 46.1% (so **+oi trades only that subset**, almost none before ~2021-12). Missing-funding symbol-days get a constant drag of **3.00 bp/day** per unit long (= median daily funding sum across the 77 funded symbols over IS; mean 2.74). Sensitivity with 0 drag is below.
* Costs: taker fee 0.00045, impact = max(0.5bp, impact_k*sqrt(trade/ADV)) from `costs.impact_bps` (impact_k=0.5 STUB), ADV = trailing 30d quote volume known before the open, notional = |dW| x $1,000,000; funding applied on the held weight; borrow n/a (long-only). Participation-cap violations (trade > 10% of previous-day volume): 0.0000% of trades. Vectorised cost path vs `costs.apply_costs` (fee+impact) on 25 sample trades: 3202.10 vs 3202.10 USD.

## (b) All 24 configs, in-sample (net of fees, impact, funding)

OOF = purged 5-fold (embargo 2%) over the IS window; params are fixed (no training), so the OOF series is the IS series cut into 5 contiguous test folds and 'OOF Sharpe' = mean of the 5 fold Sharpes (annualised sqrt(365)).

| config | OOF Sharpe (mean of 5) | worst fold | IS net Sharpe | net CAGR | maxDD | rank |
|---|---|---|---|---|---|---|
| brk20/10|bare | 0.50 | -1.02 | 0.61 | 20.0% | -74.9% | 1 |
| tsmom30|+oi | 0.45 | -0.59 | 0.16 | 1.3% | -40.0% | 2 |
| brk55/20|+vol | 0.43 | -1.70 | 0.60 | 19.0% | -82.0% | 3 |
| brk20/10|+vol | 0.42 | -1.09 | 0.55 | 16.1% | -80.0% | 4 |
| brk55/20|bare | 0.41 | -1.55 | 0.57 | 17.1% | -80.7% | 5 |
| brk20/10|+reg | 0.34 | -1.20 | 0.48 | 11.2% | -79.4% | 6 |
| brk20/20|bare | 0.34 | -1.37 | 0.47 | 10.4% | -84.3% | 7 |
| brk55/20|+reg | 0.33 | -1.59 | 0.49 | 12.1% | -83.1% | 8 |
| brk55/10|bare | 0.28 | -1.69 | 0.49 | 12.6% | -82.3% | 9 |
| brk55/10|+vol | 0.26 | -1.81 | 0.48 | 11.9% | -82.0% | 10 |
| brk20/20|+reg | 0.25 | -1.62 | 0.40 | 6.0% | -84.8% | 11 |
| brk20/20|+vol | 0.25 | -1.44 | 0.39 | 5.7% | -87.3% | 12 |
| brk20/10|+oi | 0.19 | -1.52 | -0.00 | -6.5% | -72.7% | 13 |
| tsmom90|+oi | 0.16 | -2.22 | 0.25 | 3.0% | -34.0% | 14 |
| brk20/20|+oi | 0.14 | -1.72 | -0.09 | -10.0% | -79.3% | 15 |
| brk55/10|+reg | 0.13 | -1.89 | 0.33 | 3.3% | -84.1% | 16 |
| brk55/20|+oi | 0.13 | -1.63 | 0.03 | -4.6% | -66.9% | 17 |
| brk55/10|+oi | 0.07 | -1.72 | 0.03 | -4.3% | -66.1% | 18 |
| tsmom90|+vol | 0.07 | -0.92 | 0.30 | 3.5% | -56.6% | 19 |
| tsmom30|+vol | -0.18 | -1.42 | 0.16 | -1.1% | -60.7% | 20 |
| tsmom90|+reg | -0.21 | -1.46 | 0.05 | -6.1% | -66.0% | 21 |
| tsmom90|bare | -0.45 | -1.82 | -0.50 | -20.8% | -71.9% | 22 |
| tsmom30|bare | -0.69 | -2.42 | -0.24 | -14.2% | -74.0% | 23 |
| tsmom30|+reg | -0.76 | -1.81 | -0.34 | -16.4% | -74.8% | 24 |
| **BTC buy&hold (same costs)** | - | - | 0.82 | 37.3% | -78.9% | |
| **SMA100 equal-weight (same costs)** | - | - | 0.33 | 3.2% | -77.9% | |

Selected (max mean-OOF Sharpe): **brk20/10|bare**. Mean daily turnover (sum|dW|) of best: 0.128; mean gross exposure 0.56.
Best config annualised return decomposition (arithmetic, IS): gross 81.8%, fees -2.1%, impact -35.9%, funding -8.0%, net 35.7%.
Funding sensitivity: with NO drag on symbols missing funding history, best-by-OOF would be brk20/10|bare; IS net Sharpe of brk20/10|bare = 0.63 (vs 0.61), holdout net Sharpe -0.12 (vs -0.13).

## (c) 7-point decision rule (base costs, impact_k=0.5)

| # | criterion | result | number |
|---|---|---|---|
| 1 | Best-config DSR>0 at p<0.05 (n_trials=24) | **FAIL** | DSR=0.493 (p=0.507); SR*=0.62 ann vs obs 0.61; PSR(0)=0.918 |
| 2 | PBO < 5% | **FAIL** | PBO=0.600 (12870 CSCV partitions) |
| 3 | SPA rejects 'no edge' p<0.05 vs BTC B&H AND SMA100 (worse of the two) | **FAIL** | SPA p: BTC buy&hold=1.000 (WRC 0.953); SMA100 equal-weight=0.357 (WRC 0.528) |
| 4 | Net Sharpe > BTC B&H and > SMA100 (IS) | **FAIL** | net Sharpe 0.61 vs BTC B&H 0.82, SMA100 0.33 (CAGR 20.0% vs 37.3% / 3.2%) |
| 5 | Holds on forward holdout (net>0, Sharpe >= half of IS) | **FAIL** | holdout net Sharpe -0.13, CAGR -14.9%, maxDD -47.3% vs IS Sharpe 0.61 (rule: >0 and >= 0.5x IS) |
| 6 | Mechanism: P1 FOR, >=2 of P2-P6 FOR, none AGAINST | **FAIL** | P1=INCONCLUSIVE; FOR among P2-P6 = 0; any AGAINST = True; gates={'P1': 'INCONCLUSIVE', 'P2': 'AGAINST', 'P3': 'INCONCLUSIVE', 'P4': 'AGAINST', 'P5': 'INCONCLUSIVE', 'P6': 'UNTESTABLE'} |
| 7 | Independent replication on Bybit | **FAIL** | NOT RUN in this environment (replication is designated for the cloud on Bybit); counts as not satisfied |

0/7 pass. Rule requires all 7 -> **edge NOT CONFIRMED**.

## (d) impact_k sensitivity (x0.5 / x1 / x2)

| impact_k | best (by OOF) | IS Sharpe | DSR p | PBO | SPA p (worse) | pt1 | pt2 | pt3 | pt4 | pt5 | holdout Sharpe |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.25 | brk20/10|bare | 0.92 | 0.221 | 0.488 | 0.791 | FAIL | FAIL | FAIL | PASS | FAIL | 0.22 |
| 0.50 | brk20/10|bare | 0.61 | 0.507 | 0.600 | 1.000 | FAIL | FAIL | FAIL | FAIL | FAIL | -0.13 |
| 1.00 | tsmom30|+oi | -0.13 | 0.981 | 0.606 | 1.000 | FAIL | FAIL | FAIL | FAIL | FAIL | -0.02 |

Points 1-5 that FLIP across impact_k: [4]. Verdict is cost-dependent (flagged).

**Cost-model caveat:** costs.py impact = k*sqrt(trade/ADV) with k=0.5 gives ~77 bp per unit traded for this book (uncalibrated STUB, no volatility scaling); with daily vol-target resizing the best config turns over 0.13/day, so impact (not fees) dominates net results and the x0.5/x2 verdicts differ. Treat all net numbers as conditional on this stub.

## (e) Mechanism gates (P2/P4/P6 are SURROGATES; no liquidation or borrow history exists)

* **P1 (filter improves edge): INCONCLUSIVE.** Net IS Sharpe, bare vs filtered (annualised):
  * +vol: mean dSharpe +0.18, improved in 3/6 signals, annual-return diff of the 6-signal average 6.1% (95% block-bootstrap CI 0.1%..13.1%). Per signal (bare->filtered): brk20/10 0.61->0.55, brk20/20 0.47->0.39, brk55/10 0.49->0.48, brk55/20 0.57->0.60, tsmom30 -0.24->0.16, tsmom90 -0.50->0.30
  * +oi (bare control restricted to symbol-days with OI history): mean dSharpe -0.03, improved in 2/6 signals, annual-return diff of the 6-signal average -1.7% (95% block-bootstrap CI -4.3%..0.9%). Per signal (bare->filtered): brk20/10 0.12->-0.00, brk20/20 0.02->-0.09, brk55/10 0.10->0.03, brk55/20 0.12->0.03, tsmom30 0.07->0.16, tsmom90 0.09->0.25
  * Rule: FOR needs mean dSharpe>0, >=4/6 improved and CI low>0 for +vol OR +oi; AGAINST if both have mean<0 and CI high<0.
* **P2 liquidation-cluster SURROGATE: AGAINST.** Pooled entries of the 6 bare signals (IS, n=3466; entries from different signals overlap in time so p-values are anti-conservative). At the signal bar (close T-1) on an up-day: taker-sell-dominant (taker_buy_ratio<0.5) in 57.8% of entries vs base rate 71.0% (ratio 0.81, binom p=1.000); fwd-10d return flagged vs not +5.13% vs +3.46% (Welch p=0.126) -> INCONCLUSIVE. OI fell >1% on an up-day in 7.0% of entries with OI vs base 18.9% (ratio 0.37, p=1.000, n_oi=1290); fwd return flagged vs not +2.00% vs +2.89% (p=0.659) -> AGAINST.
* **P3 edge concentrates in smaller coins: INCONCLUSIVE.** Entries by PIT liquidity rank at the signal bar: rank>10 (n=2533) mean fwd-10d +4.04% vs rank<=10 (n=911) +3.38%, diff +0.66%, Welch p=0.483. Best-config gross P&L attribution (IS, arithmetic sum of daily contributions): rank>10 +2.43, rank<=10 +1.94. Retail-venue split (spot, Coinbase) NOT available -> by-rank proxy only.
* **P4 expensive-short (funding as proxy): AGAINST.** Entries split at median trailing-3d funding (3.00 bp/day): low-funding (shorts pay / crowded short) mean fwd-10d +1.68% (n=1283) vs high +10.70% (n=1062), diff -9.02%, p=0.000. Real borrow cost history is untestable; funding is the perp surrogate. CAVEAT: trailing funding is a bull-market proxy (high funding = strong-uptrend regimes), so this split is confounded with the market regime and 'AGAINST' here is weak evidence about shorting cost.
* **P5 decay: INCONCLUSIVE.** Best config IS first half Sharpe 0.87 vs second half 0.29 (z of drop = 0.66; FOR needs lower 2nd half with z>1.64). By year (best): 2020: 0.69, 2021: 1.81, 2022: -1.35, 2023: 1.07, 2024: 0.21, 2025: -0.59. Median across 24 configs by year: 2020: 0.88, 2021: 1.67, 2022: -1.96, 2023: 0.53, 2024: 0.22, 2025: -0.90.
* **P6 counterparty (account-level liquidations/positions): UNTESTABLE** with free data.

Gate tally: FOR among P2-P6 = 0; any AGAINST = True; P1 = INCONCLUSIVE -> point 6 FAIL.

## (f) In-sample vs forward holdout (best config, evaluated ONCE after selection)

Selected on IS only: **brk20/10|bare** (impact_k 0.5).

| window | net Sharpe | net CAGR | maxDD | total return |
|---|---|---|---|---|
| IS (best) | 0.61 | 20.0% | -74.9% | 164.4% |
| Holdout (best) | -0.13 | -14.9% | -47.3% | -19.4% |
| Holdout gross (best, pre-cost) | 0.62 | 19.5% | -38.9% | 26.8% |
| Holdout BTC buy&hold | -0.33 | -20.1% | -53.7% | -25.8% |
| Holdout SMA100 EW | -0.69 | -30.4% | -51.2% | -38.3% |

Holdout net Sharpe 95% block-bootstrap CI: -1.88..1.61. Holdout mean turnover 0.117/day, exposure 0.45.

## (g) LOOKAHEAD SELF-AUDIT

| risk | how it is prevented in the code |
|---|---|
| Universe ranking | `Panel.member`: rank on `qv30` = trailing 30-day mean of quote_volume with value at row i using rows <= i (rolling, no centering); the mask at close i only gates decisions for bar i+1. Not ranked on 'today's top by volume' (that was the selected.json bias). IS and full panels are asserted to give identical membership on IS dates. Delisted symbols are kept until delivery_ts / last bar (no survivorship). |
| Signal timing | indicators in `trend.py` are trailing with `.shift(1)` on Donchian/exit/vol-median; the decision at close of bar i is shifted so row T carries weight computed from bars < T (verified in code, 9 unit tests pass after the mask patch). |
| Entry timing | trend.py's own equity curve is close-to-close, but THIS runner books P&L as W[T-1]*(O_T/C_{T-1}-1) + W[T]*(C_T/O_T-1): a signal formed at close T-1 is entered at OPEN T, never at the close it was observed. Costs are charged on |W_T - W_{T-1}| at that open, with ADV known before that open. |
| Universe vs positions | `member_mask` (new optional arg of `generate_positions`, default None=old behaviour) blocks entries and forces exits for non-members using the mask at close i. This is applied INSIDE the position loop so gross cap/kill-switch see the real portfolio. |
| Funding as-of | Realised funding is an accounting cost (events inside the bar [t, t+1d) times the weight held in that bar) - never a signal input in the main grid (funding_filter is off). Timestamps rounded to the minute to remove +-1 ms jitter. Missing-funding drag constant is the median over IS dates only. Funding/OI feature in P4 uses days <= T-1. |
| OI as-of | OI uses the 00:00 UTC snapshot (state at prior close) forward-filled onto the daily index (`trend._asof` ffill only); `oi > oi.shift(5)` is evaluated at close i. +oi therefore blocks symbols/dates without OI history (reported as reduced coverage, not dropped). |
| Holdout isolation | A separate `Panel(end=IS last day)` is built; all 24 configs, benchmarks, OOF, DSR/PBO/SPA, P1-P5 are computed on it, so no holdout bar exists in memory. Only after `best` is fixed is the full panel loaded and the best config run once. Check: max |W_full - W_IS| on IS rows = 1.11e-16 (positions on IS rows do not depend on later data). For the impact_k sensitivity the per-multiplier best is also evaluated on the holdout (possible additional look; flagged). |
| Purged k-fold / embargo | `purged_kfold(n,5,0.02)` test indices used. Since configs have fixed parameters, nothing is trained on the 'train' folds, so purge/embargo is vacuous; the residual leak is path dependence (stop/drawdown state carried across fold boundaries), which is causal and not removed. The OOF number is therefore close to the plain IS Sharpe; selection among 24 is handled by DSR/PBO/SPA, not by the fold split. |
| Selection bias | Best-of-24 is penalised by DSR (n_trials=24, var_sr from the 24 IS Sharpes), PBO (CSCV, 16 slices) and WRC/SPA vs both benchmarks. |
| Residual risks (not removable here) | (1) N=30 and window RANK_WIN=30 were fixed before running; (2) delisted-symbol final bars: exit at last close, no delisting-gap loss; (3) rebrand discontinuities; (4) trend.py's internal drawdown halt uses close-to-close equity, slightly different from this runner's open-entry P&L; (5) costs are uncalibrated (impact_k stub, capital $1M assumed); (6) 77-symbol funding drag constant is a assumption; (7) event-study p-values ignore clustering. |

## Files
`research/mech_runner.py`, `research/strategy/trend.py` (added optional `member_mask`), `research/mech_cache/` (position cache), `reports/mech_trend.md`, `reports/mech_trend.json`.