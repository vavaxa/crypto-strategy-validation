# FORM-N delta-neutral basis carry (long spot / short perp) - PREREG_CARRY.md FORM-N

Generated 2026-10-19 15:20:01. ONE primary config `w7d|z|vt|1d (long spot / short perp)` (hyperparameters fixed = best FORM-L; n_trials=1, no grid). Window 2020-03-01..2026-10-18 (2423 d); IS ..2025-06-20; holdout from 2025-06-21 (last 20%).

## OVERALL: **NOT CONFIRMED**

| # | Point | Status | Number |
|---|---|---|---|
| 1 | net_carry_pos_sig | **FAIL** | gross carry 1274, price 5, costs 10368 -> net -9091 bps/yr; NW t -20.15; CI -10260..-8005 |
| 2 | sharpe_sig | **FAIL** | SR -14.28, PSR p 1.000, DSR(n=1) p 1.000, Lo SR -2.55 p 0.000 |
| 3 | btc_corr | **PASS** | daily corr -0.005, weekly 0.028, beta -0.001 |
| 4 | tail | **FAIL** | LUNA DD -2.4%, FTX DD -2.6%, skew -2.18, exkurt 7.8, price-leg skew -0.49/exkurt 11.9 |
| 5 | capacity | **FAIL** | net bps/yr by book: $0.1M -2459, $1.0M -9091, $5.0M -21080, $20.0M -42768 |
| 6 | cost_robust | **FAIL** | 0/10 cost scenarios positive; breakeven impact_k 0.031; breakeven fee mult at k=0 1.84x |
| 7 | holdout | **FAIL** | HO SR -18.94, net -12842 bps/yr (IS SR -13.23); Bybit/forward pending |

## Coverage

PIT top-30 members/day 29.6; with funding 19.9; with funding AND Binance spot AND trailing funding feature 19.5 (min 10; 66.0% of member-days, 98.2% of funded member-days). 67 of 72 funded perps have spot. Excluded (no Binance spot): APRUSDT, ARIAUSDT, BRUSDT, BTWUSDT, SIRENUSDT.

| year | members | funded | funded+spot | mean coins held |
|---|---|---|---|---|
| 2020 | 26.9 | 16.4 | 16.4 | 9.7 |
| 2021 | 30.0 | 21.9 | 21.9 | 13.4 |
| 2022 | 30.0 | 21.3 | 21.2 | 10.4 |
| 2023 | 30.0 | 20.5 | 20.5 | 13.3 |
| 2024 | 30.0 | 19.7 | 19.4 | 13.6 |
| 2025 | 30.0 | 18.5 | 17.9 | 11.3 |
| 2026 | 30.0 | 20.5 | 18.6 | 10.1 |

## 1. Gross basis-carry vs net after two-leg costs (full sample, impact_k 0.5, $1M, bps of book per year)

Book = one-leg notional (sum of weights <= 1). Perp margin NOT counted as extra capital in headline.

| component | bps/yr |
|---|---|
| funding received (gross carry) | 1274 |
| hedged price leg (spot - perp, i.e. -basis change) | 5 |
| gross before costs | 1280 |
| fees (perp 4.5bp + spot 10bp per unit traded) | -671 |
| impact (both legs) | -9697 |
| **NET** | **-9091** |

Mean gross exposure 0.79, mean coins held 11.8, turnover 46.3x book/yr, funding per unit notional 16.19%/yr. Carry NW t 8.93; price-leg NW t 0.45. Cost/carry = 8.14. Return on committed capital if perp margin 20%: -7576 bps/yr, if 100%: -4545. Round-trip fee per unit notional 29.0 bp (both legs in and out). Diagnostic naive (all positive-funding members equal weight): carry 1301, price 6, cost -5164, net -3859 bps/yr, SR -8.64.

## 2. Net Sharpe and significance

Net SR -14.28 (full), CI95 [-15.65, -13.08]; CAGR -59.8%; maxDD -99.8%; mean -9091 bps/yr, NW t -20.15, bootstrap CI [-10260,-8005]. PSR p=1.000; DSR (n_trials=1) p=1.000; Lo-adjusted SR -2.55 (eta 3.41), HAC t -26.67, p=0.000. Skew -2.18, excess kurt 7.8.

## 3. Correlation to BTC

Daily corr(sleeve, BTC) = **-0.005**, weekly 0.028, beta -0.001, price-leg-only daily corr -0.327. Mean sleeve daily return on BTC worst-5% days -23.2 bp, best-5% days -25.5 bp, all days -24.9 bp. By year: {2020: 0.07351640430225878, 2021: -0.002820210944215067, 2022: 0.07098606925616711, 2023: -0.08663024513211934, 2024: -0.09547822400805119, 2025: -0.07270380471054062, 2026: -0.04887104475422152}. In stress windows: {'LUNA': 0.08380678534928944, 'FTX': -0.42633105826732853}. Threshold |corr|<0.3 -> PASS.

## 4. Tail: LUNA / FTX / basis blow-up

| window | maxDD | cum net | worst day net | worst day price-leg | cum price leg | cum carry | expo | coins | worst held-coin 1d basis move | worst any-member 1d basis move |
|---|---|---|---|---|---|---|---|---|---|---|
| LUNA | -2.4% | -2.4% | -0.8% | -0.1% | 0.0% | -0.2% | 0.38 | 4.2 | [('2022-05-10', 'EOSUSDT', 0.005031446540880502)] | [('2022-05-13', 'LUNAUSDT', 135.0)] |
| FTX | -2.6% | -2.5% | -1.0% | -0.0% | 0.1% | -0.0% | 0.59 | 7.5 | [('2022-11-08', 'SOLUSDT', 0.021956818082365603)] | [('2022-11-10', 'SOLUSDT', 0.16648595953876244)] |

Full-sample maxDD -99.8%; bootstrap 1y maxDD median -58.7%, p5 -70.8%. Net daily skew -2.18, excess kurt 7.8; price-leg (basis) daily std 3.0 bp, skew -0.49, excess kurt 11.9, worst day -0.3% (-10.8 sigma); corr(price leg, |BTC ret|) 0.033. Worst price-leg days: [('2024-09-05', -0.003266602835399575), ('2020-03-13', -0.0026232179367414697), ('2020-11-21', -0.0015844150618195413), ('2021-02-13', -0.0014018869371437903), ('2021-01-03', -0.0012523457221645575)]. Worst net days: [('2020-03-14', -0.02852735720333366), ('2020-06-03', -0.02596340708242706), ('2026-03-11', -0.02453988951742947), ('2020-04-13', -0.02280457234157518), ('2020-06-24', -0.022437671456807973)]. Flags: net short-vol True, price-leg short-vol True. Exchange/counterparty risk (FTX-style) is NOT modeled: both legs sit on Binance in this data.

## 5. Capacity (net through impact, both legs)

| book | net SR | net bps/yr | NW t | costs bps/yr | CAGR |
|---|---|---|---|---|---|
| $0.1M | -9.57 | -2459 | -11.88 | 3738 | -21.8% |
| $1M | -14.28 | -9091 | -20.15 | 10368 | -59.8% |
| $5M | -15.45 | -21080 | -22.37 | 22355 | -88.0% |
| $20M | -15.87 | -42768 | -23.15 | 44038 | -98.7% |

## 6. Cost / fee stress (full sample, $1M)

| scenario | net bps/yr | net SR | NW t | costs bps/yr | positive? |
|---|---|---|---|---|---|
| fee1x|k0.125 | -1816 | -8.06 | -9.64 | 3096 | NO |
| fee1x|k0.25 | -4241 | -12.02 | -15.94 | 5520 | NO |
| fee1x|k0.5 | -9091 | -14.28 | -20.15 | 10368 | NO |
| fee1x|k1 | -18790 | -15.34 | -22.18 | 20065 | NO |
| fee1x|k2 | -38189 | -15.82 | -23.06 | 39460 | NO |
| fee2x|k0.125 | -2488 | -10.24 | -12.80 | 3767 | NO |
| fee2x|k0.25 | -4913 | -13.20 | -17.98 | 6191 | NO |
| fee2x|k0.5 | -9762 | -14.87 | -21.27 | 11040 | NO |
| fee2x|k1 | -19462 | -15.63 | -22.76 | 20737 | NO |
| fee2x|k2 | -38860 | -15.97 | -23.36 | 40131 | NO |

DIAGNOSTIC (not the primary verdict; the impact model k is an uncalibrated placeholder): spread-floor-only costs (impact_k=0, only the 0.5bp/leg half-spread floor + fees):

| scenario | net bps/yr | net SR | NW t | PSR p | Lo p | CI95 mean bps/yr | maxDD |
|---|---|---|---|---|---|---|---|
| fee1x|k0 | 562 | 3.81 | 3.89 | 0.000 | 0.000 | [232,974] | -8.5% |
| fee2x|k0 | -109 | -0.70 | -0.74 | 0.956 | 0.488 | [-448,308] | -30.5% |

Breakeven impact_k (fee 1x) = 0.0314 (primary k=0.5; grid spans 0.125..2).

Breakeven fee multiple (impact_k 0, fees only): 1.84x of assumed fees.

## 7. Holdout (supporting; last 20%) and by-year

HO 2025-06-21..2026-10-18 (485 d): SR -18.94, net -12842 bps/yr (carry 338, price 13, cost -13192), NW t -12.55, maxDD -81.9%. IS SR -13.23, net -8152 bps/yr, carry 1509. Bybit replication and forward paper: pending.

| year | days | net ret | SR | carry bps | price bps | cost bps | expo | coins |
|---|---|---|---|---|---|---|---|---|
| 2020 | 306 | -74.9% | -16.54 | 1815 | -1 | 18205 | 0.68 | 9.7 |
| 2021 | 365 | -24.3% | -6.10 | 3867 | 18 | 6654 | 0.81 | 13.4 |
| 2022 | 365 | -52.2% | -16.21 | 342 | 32 | 7729 | 0.76 | 10.4 |
| 2023 | 365 | -61.7% | -18.54 | 829 | 11 | 10415 | 0.84 | 13.3 |
| 2024 | 366 | -45.7% | -14.41 | 1280 | -38 | 7318 | 0.85 | 13.6 |
| 2025 | 365 | -54.1% | -20.26 | 403 | -4 | 8177 | 0.80 | 11.3 |
| 2026 | 291 | -73.0% | -21.02 | 268 | 22 | 16624 | 0.73 | 10.1 |

## Lookahead self-audit

* Funding as-of: trailing-7d funding sum uses only events with ts strictly before the decision (bar-open) instant (carry_runner `.shift(1)` on 8h bins, >=80% event count required); the event stamped exactly at close is excluded.
* Funding booked at true settlement events: event stamped at bar open on pre-trade W_(k-1), events inside the bar on W_k.
* Basis as-of: basis = perp close/(spot close*scale)-1 at bar close; used only for reporting/stress, NOT in selection. Spot validity and spot ADV gates use close of bar k-1 and ADV shift(1) of daily spot volume.
* Next-open booking: decisions at close k-1, trade at OPEN of bar k for BOTH legs; price P&L = W_(k-1)*gap + W_k*intra for each leg.
* Selection/vol shift: sigma and hedged-book vol use returns through bar k-1 only (`shift(1)`); z-score is cross-sectional on same-instant info.
* PIT universe: same top-30 trailing-30d-volume recipe as FORM-L (membership at day D-1 close), intersected with funded & spot (spot listing date implicit via finite spot close/ADV).
* Holdout isolation: weights rebuilt on a context truncated at the last IS day; max|W_full - W_IS| over IS rows = 0.00e+00, weight on non-IS symbols in IS rows = 0.00e+00. Hyperparameters fixed a priori from FORM-L (no tuning on holdout; none tuned at all here). Caveat: FORM-L best config was itself selected on the IS window of FORM-L.
* Spot ffill uses only past bars (limit 6); fraction of held coin-bars with raw spot hole 0.0000.
* Caveats not lookahead: spot fee 10 bp is an assumption (no BNB/VIP); no margin/liquidation model; constant-notional funding approximation; both legs same exchange (counterparty risk unmodeled).
