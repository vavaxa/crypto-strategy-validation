# VRP study (prereg: research/PREREG_VRP.md)

**Overall: NOT CONFIRMED as tradeable edge**

## Coverage
- DVOL BTC 2021-03-24..2026-10-19, 2036 rows, close range 32.38..156.2 (all in 10..200: True); ETH rows 2036. Missing days after join with spot: BTC 0, ETH 0. Last spot day used 2026-10-18 (today's partial bar dropped).

## 1. Measurement: VRP = DVOL - forward RV (vol points)
| asset/spec | n | mean | NW t | hit IV>RV | median | mean IV | mean RV | var-terms mean (IV^2-RV^2) | var NW t | non-overlap mean / t / hit | skew | exc.kurt |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BTC h30_cc | 2005 | 8.40 | 5.43 | 0.716 | 10.05 | 59.94 | 51.54 | 936 | 4.43 | 10.27 / 4.55 / 0.75 (n=67) | -0.20 | 0.85 |
| BTC h30_gk | 2005 | 4.36 | 2.70 | 0.662 | 6.04 | 59.94 | 55.58 | 432 | 1.59 | 6.18 / 2.78 / 0.72 (n=67) | -1.05 | 4.85 |
| BTC h7_cc | 2028 | 11.22 | 9.80 | 0.762 | 13.54 | 59.67 | 48.45 | 911 | 5.45 | 11.41 / 8.85 / 0.76 (n=290) | -1.12 | 3.56 |
| ETH h30_cc | 2005 | 4.50 | 2.06 | 0.647 | 7.60 | 73.97 | 69.47 | 435 | 0.99 | 5.94 / 2.02 / 0.72 (n=67) | -0.91 | 2.95 |
| ETH h30_gk | 2005 | 0.13 | 0.05 | 0.572 | 2.77 | 73.97 | 73.83 | -324 | -0.55 | 1.67 / 0.51 / 0.60 (n=67) | -1.64 | 6.90 |
| ETH h7_cc | 2028 | 8.56 | 5.34 | 0.698 | 11.90 | 73.69 | 65.13 | 384 | 1.06 | 8.71 / 4.89 / 0.70 (n=290) | -1.55 | 6.03 |

BTC by year (h30 cc): 2021: mean 18.02, NW t 3.63, hit 0.88, n=283; 2022: mean 12.17, NW t 2.87, hit 0.67, n=365; 2023: mean 6.61, NW t 2.99, hit 0.73, n=365; 2024: mean 7.18, NW t 2.65, hit 0.73, n=366; 2025: mean 6.45, NW t 2.74, hit 0.71, n=365; 2026: mean -0.40, NW t -0.09, hit 0.59, n=261
BTC halves: first: mean 11.86, t 5.03, hit 0.74; second: mean 4.94, t 2.72, hit 0.69
BTC VRP percentiles: {1: -39.108627520289424, 5: -19.593803517151947, 25: -1.6123836982902802, 50: 10.046171371371507, 75: 18.152471385151927, 95: 34.4478251948934}

ETH by year (h30 cc): 2021: mean 11.56, NW t 1.19, hit 0.81, n=283; 2022: mean 8.96, NW t 1.54, hit 0.63, n=365; 2023: mean 5.33, NW t 2.86, hit 0.72, n=365; 2024: mean 3.35, NW t 1.18, hit 0.61, n=366; 2025: mean -2.55, NW t -0.64, hit 0.54, n=365; 2026: mean 0.91, NW t 0.16, hit 0.60, n=261
ETH halves: first: mean 8.45, t 2.38, hit 0.71; second: mean 0.55, t 0.23, hit 0.58
ETH VRP percentiles: {1: -72.8221037440918, 5: -33.321754641626306, 25: -6.938407700004788, 50: 7.599997628072579, 75: 17.48691382271513, 95: 36.741726140454226}

### Left tail (BTC, h30 cc)
- LUNA 2022-04-15..2022-05-31: worst entry 2022-05-02, VRP -21.81 (IV 62.42, fwd RV 84.23), var-terms -3199; window mean VRP -7.28
- FTX 2022-10-15..2022-11-30: worst entry 2022-11-03, VRP -28.59 (IV 53.98, fwd RV 82.57), var-terms -3904; window mean VRP 11.72
- Worst 30d windows (separated >=30d): 2026-01-28: VRP -45.24 (IV 38.00 vs RV 83.24; var -5484); 2021-04-28: VRP -39.63 (IV 76.96 vs RV 116.59; var -7670); 2024-02-23: VRP -30.82 (IV 52.23 vs RV 83.05; var -4170); 2022-11-03: VRP -28.59 (IV 53.98 vs RV 82.57; var -3904); 2025-02-23: VRP -23.31 (IV 48.47 vs RV 71.78; var -2803); 2024-07-12: VRP -22.16 (IV 46.32 vs RV 68.48; var -2544)

## 2. Strategy proxy: short 30d variance swap, daily tranches (BTC)
Eval 2021-06-27..2026-10-18 (n=1940 days), IS ..2025-09-25 (n=1552), holdout n=388. Best on IS (net s=1.5): **always|constvega**. V0=0.005 equity per vol pt, vol-target 0.1 cap 2.0, thr 5.0, roll 0.25 vol pt.

| config | gross ann ret | gross Sharpe | net ann ret (s=1.5) | net Sharpe | NW t | maxDD | skew | kurt | DSR daily | DSR monthly | monthly Sharpe | monthly hit | breakeven s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| always|constvega | 0.364 | 2.02 | 0.278 | 1.50 | 2.51 | -0.304 | -7.08 | 83.3 | 0.946 | 0.840 | 1.10 | 0.66 | 6.08 |
| always|voltarget | 0.229 | 1.49 | 0.159 | 1.00 | 1.81 | -0.232 | -7.27 | 87.2 | 0.808 | 0.740 | 0.84 | 0.62 | 4.70 |
| cond|constvega | 0.166 | 1.15 | 0.112 | 0.75 | 1.28 | -0.314 | -8.13 | 105.9 | 0.669 | 0.556 | 0.60 | 0.67 | 4.49 |
| cond|voltarget | 0.166 | 1.02 | 0.103 | 0.62 | 1.06 | -0.344 | -7.42 | 87.7 | 0.586 | 0.528 | 0.51 | 0.64 | 3.89 |

IS/holdout Sharpe (net s=1.5): always|constvega: IS 2.28 / HO -0.84; always|voltarget: IS 1.68 / HO -0.74; cond|constvega: IS 1.59 / HO -1.82; cond|voltarget: IS 1.41 / HO -1.72

### Cost gate (net ann return / Sharpe / NW t by s)
| config | gross s=0 | s=1.0 | s=1.5 | s=2.0 | sign flip? |
|---|---|---|---|---|---|
| always|constvega | 0.364 / 2.02 / t3.37 | 0.307 / 1.67 / t2.79 | 0.278 / 1.50 / t2.51 | 0.249 / 1.33 / t2.22 | no |
| always|voltarget | 0.229 / 1.49 / t2.67 | 0.182 / 1.16 / t2.10 | 0.159 / 1.00 / t1.81 | 0.135 / 0.84 / t1.52 | no |
| cond|constvega | 0.166 / 1.15 / t1.93 | 0.130 / 0.88 / t1.49 | 0.112 / 0.75 / t1.28 | 0.094 / 0.63 / t1.06 | no |
| cond|voltarget | 0.166 / 1.02 / t1.72 | 0.124 / 0.75 / t1.28 | 0.103 / 0.62 / t1.06 | 0.082 / 0.49 / t0.84 | no |

Bootstrap 95% CI of best-IS config net annual return: [0.06077680415999922, 0.4820662202295771]

### Tail characterization
- always|constvega: skew -7.08, kurt 83.3, worst day -0.1705 = -17.61 sigma; maxDD -0.304 (2026-03-06); worst 30d sum -0.320 (ending 2026-02-27) = 0.22x of total net gain; monthly worst -0.275 vs mean 0.0226; monthly skew -1.19; LUNA(May-Jun22) pnl -0.148 maxDD-in-window -0.202; FTX(Nov-Dec22) pnl 0.033 maxDD-in-window -0.196
- always|voltarget: skew -7.27, kurt 87.2, worst day -0.1520 = -18.36 sigma; maxDD -0.232 (2026-03-06); worst 30d sum -0.246 (ending 2026-02-27) = 0.29x of total net gain; monthly worst -0.187 vs mean 0.0129; monthly skew -0.96; LUNA(May-Jun22) pnl -0.114 maxDD-in-window -0.134; FTX(Nov-Dec22) pnl -0.033 maxDD-in-window -0.111
- cond|constvega: skew -8.13, kurt 105.9, worst day -0.1441 = -18.52 sigma; maxDD -0.314 (2026-09-04); worst 30d sum -0.279 (ending 2026-02-27) = 0.47x of total net gain; monthly worst -0.233 vs mean 0.0093; monthly skew -1.47; LUNA(May-Jun22) pnl -0.090 maxDD-in-window -0.122; FTX(Nov-Dec22) pnl -0.059 maxDD-in-window -0.196
- cond|voltarget: skew -7.42, kurt 87.7, worst day -0.1566 = -17.95 sigma; maxDD -0.344 (2026-09-04); worst 30d sum -0.276 (ending 2026-02-27) = 0.50x of total net gain; monthly worst -0.193 vs mean 0.0086; monthly skew -0.56; LUNA(May-Jun22) pnl -0.132 maxDD-in-window -0.156; FTX(Nov-Dec22) pnl -0.065 maxDD-in-window -0.114

### BTC correlation and down-day behaviour (net s=1.5)
- always|constvega: corr daily -0.00, down-days corr 0.81, monthly corr 0.16, beta -0.0006; mean ret BTC-down days 0.00092 vs up days 0.00061; BTC<=-5% days n=64 mean -0.0248 sum -1.589; BTC<=-10%: n=7 sum -0.580; months BTC down: n=32 mean 0.0138 hit 0.59; BTC-up months mean 0.0315; worst-20% BTC months mean -0.0294 hit 0.38
- always|voltarget: corr daily 0.02, down-days corr 0.75, monthly corr 0.09, beta 0.0048; mean ret BTC-down days 0.00051 vs up days 0.00036; BTC<=-5% days n=64 mean -0.0202 sum -1.295; BTC<=-10%: n=7 sum -0.464; months BTC down: n=32 mean 0.0097 hit 0.59; BTC-up months mean 0.0162; worst-20% BTC months mean -0.0200 hit 0.38
- cond|constvega: corr daily 0.04, down-days corr 0.74, monthly corr 0.13, beta 0.0120; mean ret BTC-down days 0.00033 vs up days 0.00029; BTC<=-5% days n=64 mean -0.0197 sum -1.260; BTC<=-10%: n=7 sum -0.489; months BTC down: n=32 mean 0.0033 hit 0.59; BTC-up months mean 0.0154; worst-20% BTC months mean -0.0257 hit 0.38
- cond|voltarget: corr daily 0.06, down-days corr 0.69, monthly corr 0.12, beta 0.0177; mean ret BTC-down days 0.00030 vs up days 0.00027; BTC<=-5% days n=64 mean -0.0214 sum -1.372; BTC<=-10%: n=7 sum -0.506; months BTC down: n=32 mean 0.0040 hit 0.62; BTC-up months mean 0.0132; worst-20% BTC months mean -0.0237 hit 0.46

## 5. Holdout (last 20%, supporting) and ETH replication (same 4 configs, no re-selection)
- always|constvega: BTC HO ann ret -0.191, Sharpe -0.84, maxDD -0.304 | ETH full net ann ret 0.066, Sharpe 0.26, maxDD -0.625, DSR monthly 0.259, skew -6.14, sign flip across s: False; ETH HO Sharpe -0.60
- always|voltarget: BTC HO ann ret -0.158, Sharpe -0.74, maxDD -0.232 | ETH full net ann ret -0.026, Sharpe -0.14, maxDD -0.548, DSR monthly 0.085, skew -11.04, sign flip across s: False; ETH HO Sharpe -0.63
- cond|constvega: BTC HO ann ret -0.327, Sharpe -1.82, maxDD -0.312 | ETH full net ann ret -0.007, Sharpe -0.04, maxDD -0.520, DSR monthly 0.126, skew -8.40, sign flip across s: True; ETH HO Sharpe -1.19
- cond|voltarget: BTC HO ann ret -0.357, Sharpe -1.72, maxDD -0.337 | ETH full net ann ret -0.015, Sharpe -0.07, maxDD -0.580, DSR monthly 0.114, skew -14.22, sign flip across s: True; ETH HO Sharpe -0.72

## 6. RV-estimator robustness (GK vs close-to-close, net s=1.5, BTC)
- always|constvega: cc ann ret 0.278 / Sharpe 1.50; GK ann ret 0.121 / Sharpe 0.87
- always|voltarget: cc ann ret 0.159 / Sharpe 1.00; GK ann ret 0.077 / Sharpe 0.41
- cond|constvega: cc ann ret 0.112 / Sharpe 0.75; GK ann ret 0.042 / Sharpe 0.38
- cond|voltarget: cc ann ret 0.103 / Sharpe 0.62; GK ann ret 0.030 / Sharpe 0.17

## Decision rule (6 points)
- **1_premium**: `{"verdict": "PARTIAL", "mean": 8.396398713253323, "nw_t": 5.428799727600909, "hit": 0.7162094763092269, "years_positive": "5/6", "halves": {"first": {"mean": 11.861025547737102, "nw_t": 5.034926054042047, "hit": 0.7445109780439122}, "second": {"mean": 4.9352261428118975, "nw_t": 2.721278188595856, "hit": 0.6879361914257228}}}`
- **2_net_pnl**: `{"best_is": "always|constvega", "net_ann_ret": 0.2781249475878592, "net_sharpe": 1.4974407621863912, "nw_t": 2.505406588480254, "dsr_daily": 0.9462515393958816, "dsr_monthly": 0.8398611983741746, "sign_flip": false, "breakeven_s": 6.079793777108381, "all_net_positive": ["always|constvega", "always|voltarget", "cond|constvega", "cond|voltarget"], "verdict": "FAIL"}`
- **3_tail**: `{"verdict": "FAIL (insurance-selling tail)", "skew": -7.082003275734597, "kurt": 83.25764213924968, "worst_day_sigma": -17.612440926904263, "maxdd": -0.3043120481539786, "LUNA": {"window": "2022-05-01..2022-06-30", "pnl_sum": -0.14837252339872528, "max_dd_in_window": -0.2015865439597586, "worst_day": -0.1015681909847268}, "FTX": {"window": "2022-11-01..2022-12-31", "pnl_sum": 0.03324232112068389, "max_dd_in_window": -0.1963408109077538, "worst_day": -0.1132488623621244}, "worst_30d": {"end": "2026-02-27", "sum": -0.3203843605654104}, "monthly_worst_over_mean": -12.141052580532588, "gains_erased": 0.2167317292131313}`
- **4_btc_corr**: `{"verdict": "NOT a diversifier (loses in BTC crashes)", "btc_le_5pct_sum": -1.5894517176600385, "btc_le_10pct_sum": -0.5795284728513317, "worst20_months_mean": -0.02938229343185689, "corr_daily": -0.001582557792967943, "corr_monthly": 0.15794203508781315, "corr_down_days": 0.807609662673757, "beta": -0.0005636947712175441, "mean_ret_on_btc_down_days": 0.0009151993096303812, "mean_ret_on_btc_up_days": 0.0006071853048640361}`
- **5_holdout_eth**: `{"holdout_sharpe": -0.8423376543706002, "holdout_mean_daily": -0.000522752981729806, "holdout_same_sign": false, "eth_net_sharpe": 0.25763402882135117, "eth_net_ann_ret": 0.06649989921960765, "eth_dsr_monthly": 0.2594730987052454, "live_forward": "PENDING", "verdict": "PENDING (live/forward required; tail not confirmable)"}`
- **6_robust**: `{"cost_gate_sign_flip": false, "gk_net_sharpe": 0.8692988996279088, "gk_net_ann_ret": 0.12058895054478652, "cc_net_sharpe": 1.4974407621863912, "verdict": "PASS"}`

## Lookahead self-audit
- Forward RV (`fwd_rv`) used ONLY in the measurement layer (VRP_t); the strategy never reads it. Strategy tranche entered at close t using IV_t and trailing RV (returns <= t); accrues returns from t+1 (equivalent of shift(1)); vol-target scale uses trailing 60d std shifted by 1.
- Scramble test (reverse all prices after 2025-05-02): signal unchanged for t<=cut: True; always|constvega book prefix unchanged: True; vol-target prefix unchanged: True. (Prefix includes pnl on days <= cut only from returns <= cut, hence unchanged.)
- Overlap: 30d windows overlap -> NW HAC lag = 30 on all means; non-overlapping 30d (every 30th obs) reported; DSR also on non-overlapping monthly sums (headline conservative).
- Holdout: best config chosen on first 80% only (IS Sharpe, net s=1.5); holdout metrics reported once, never used for selection. Grid is exactly 4 configs (n_trials=4); h=7, GK, ETH are robustness outside n_trials. Constants (THR=5, V0, vol-target 10%/cap 2, roll 0.25, s grid) fixed a priori before running; none tuned.
- Simplifications: daily accrual uses realized r^2 only (no mark-to-market of remaining implied variance); vol-target scales the s=0 book of the same regime so costs do not change sizing; returns arithmetic on fixed equity; no margin/funding costs; Deribit DVOL is an index, not a tradeable quote; the s-vol-point spread is an assumption (live calibration pending).
