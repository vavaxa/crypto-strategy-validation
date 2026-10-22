# MM Phase A: mark-out on Binance Vision (2023-08-01..2023-08-31)

MEASUREMENT ONLY. Fill rule is an OPTIMISTIC UPPER BOUND (front of queue, zero latency). Real market making is worse. Spec: research/PREREG_MM_PHASEA.md. Code: research/mm_markout.py, research/mm_report.py.

## 1. Five tickers (fixed a priori, by liquidity tier, not by MM result)

- BTCUSDT: CONTROL (tight spread)
- ETHUSDT: top tier (~rank 2)
- SOLUSDT: ~rank 20 tier
- DOGEUSDT: mid tier (~rank 10-30 by 2023 volume; spec bucket "~rank 50")
- SXPUSDT: low-liquidity, ~rank 100 tier

The 5th (wider-spread, low-liquidity) candidate was chosen before any sim run by liquidity-tier judgement from the 2023 perp universe (data/mech/selected.json has no 2023 volumes, only today's live list): first candidate SXPUSDT (a mid/low-cap alt that was a ~rank 100 perp in 2023); bookTicker+aggTrades for the window verified present (HTTP 200), so no step to the next candidate (RLCUSDT, STORJUSDT were the fallbacks). Tier ranks are my a-priori judgement, not measured from 2023 volume. Honest caveat: the spec asked for four alts at ~top-5/20/50/100; we ran ETH, SOL, DOGE, SXP (3 alts + 1 more instead of a separate rank-50), per the task brief.

## 2. Method (as built)
- Top-of-book from bookTicker (event_time), consecutive identical (bid,ask) states collapsed. aggTrades from transact_time.
- Bid fill: is_buyer_maker=True trade with price <= best bid (last book state strictly before the trade). Ask fill: is_buyer_maker=False trade with price >= best ask. Fill price = our limit price.
- One fill per side per fixed 30s UTC bucket (first qualifying trade) so the 1s/5s/30s windows never overlap: no double counting. Underspecified in the spec; simplest a-priori choice.
- Mark-out bps of fill-time mid: buy (mid_h - bid)/mid0, sell (ask - mid_h)/mid0, h in 1,5,30s (mid_h = last book event <= t+h). Includes the captured half-spread by construction.
- Round trip gross = mean(bid-side) + mean(ask-side). Net = gross - 2*fee. Per-side net = mean - fee.
- Significance: Newey-West (lag 24) t on the hourly series of paired (bid-hour-mean + ask-hour-mean) round-trip mark-out.

## 3. Headline: round-trip mark-out, bps of mid (all 31 days)

| sym | tw spread bp | h | fills | bid mo | ask mo | median/fill | p5 | skew | RT gross | RT net 0bp | RT net 1bp | RT net 2bp | NW t (gross) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BTCUSDT | 0.04 | 1s | 178406 | -0.00 | 0.00 | 0.02 | -0.63 | -0.49 | -0.00 | -0.00 | -2.00 | -4.00 | -0.9 |
| BTCUSDT | 0.04 | 5s | 178406 | -0.00 | -0.01 | 0.02 | -1.67 | -0.24 | -0.01 | -0.01 | -2.01 | -4.01 | -2.1 |
| BTCUSDT | 0.04 | 30s | 178406 | -0.02 | 0.01 | 0.02 | -3.96 | 0.03 | -0.01 | -0.01 | -2.01 | -4.01 | -3.1 |
| ETHUSDT | 0.06 | 1s | 178445 | -0.01 | -0.01 | 0.03 | -0.79 | 5.29 | -0.02 | -0.02 | -2.02 | -4.02 | -3.0 |
| ETHUSDT | 0.06 | 5s | 178445 | -0.02 | -0.01 | 0.03 | -1.76 | 1.92 | -0.03 | -0.03 | -2.03 | -4.03 | -3.7 |
| ETHUSDT | 0.06 | 30s | 178445 | -0.03 | -0.01 | 0.03 | -4.14 | -0.17 | -0.04 | -0.04 | -2.04 | -4.04 | -4.2 |
| SOLUSDT | 0.45 | 1s | 178381 | -0.12 | -0.09 | 0.21 | -2.34 | -0.83 | -0.21 | -0.21 | -2.21 | -4.21 | -7.9 |
| SOLUSDT | 0.45 | 5s | 178381 | -0.15 | -0.11 | 0.20 | -4.21 | -0.01 | -0.26 | -0.26 | -2.26 | -4.26 | -10.0 |
| SOLUSDT | 0.45 | 30s | 178381 | -0.16 | -0.11 | -0.20 | -8.99 | 0.05 | -0.27 | -0.27 | -2.27 | -4.27 | -10.7 |
| DOGEUSDT | 1.45 | 1s | 177792 | 0.47 | 0.50 | 0.68 | -0.82 | -0.52 | 0.97 | 0.97 | -1.03 | -3.03 | 42.3 |
| DOGEUSDT | 1.45 | 5s | 177792 | 0.45 | 0.48 | 0.68 | -2.42 | -0.30 | 0.92 | 0.92 | -1.08 | -3.08 | 37.1 |
| DOGEUSDT | 1.45 | 30s | 177792 | 0.43 | 0.48 | 0.67 | -6.35 | 0.08 | 0.90 | 0.90 | -1.10 | -3.10 | 40.1 |
| SXPUSDT | 3.42 | 1s | 144034 | 0.74 | 0.63 | 1.52 | -1.96 | -1.05 | 1.37 | 1.37 | -0.63 | -2.63 | 16.4 |
| SXPUSDT | 3.42 | 5s | 144034 | 0.67 | 0.57 | 1.52 | -4.58 | -0.89 | 1.23 | 1.23 | -0.77 | -2.77 | 14.4 |
| SXPUSDT | 3.42 | 30s | 144034 | 0.60 | 0.54 | 1.52 | -7.71 | 0.27 | 1.14 | 1.14 | -0.86 | -2.86 | 14.0 |

Breakeven maker fee per side = RT gross / 2 (30s): BTCUSDT -0.01bp, ETHUSDT -0.02bp, SOLUSDT -0.13bp, DOGEUSDT 0.45bp, SXPUSDT 0.57bp. Headline maker fee is 2bp.

## 4. Crash day 2023-08-17 vs calm days (30s horizon)

| sym | part | fills | bid mo | ask mo | p5 | p1 | skew | RT gross | RT net 2bp |
|---|---|---|---|---|---|---|---|---|---|
| BTCUSDT | calm | 172648 | -0.01 | -0.00 | -3.87 | -8.12 | -0.04 | -0.01 | -4.01 |
| BTCUSDT | crash | 5758 | -0.28 | 0.24 | -7.62 | -21.47 | 0.04 | -0.04 | -4.04 |
| ETHUSDT | calm | 172687 | -0.02 | -0.01 | -4.05 | -8.29 | -0.17 | -0.04 | -4.04 |
| ETHUSDT | crash | 5758 | -0.27 | 0.19 | -8.67 | -26.31 | -0.05 | -0.08 | -4.08 |
| SOLUSDT | calm | 172623 | -0.15 | -0.11 | -8.82 | -15.96 | 0.01 | -0.26 | -4.26 |
| SOLUSDT | crash | 5758 | -0.44 | -0.07 | -15.91 | -38.09 | 0.11 | -0.51 | -4.51 |
| DOGEUSDT | calm | 172034 | 0.44 | 0.47 | -6.07 | -12.37 | 0.04 | 0.91 | -3.09 |
| DOGEUSDT | crash | 5758 | 0.10 | 0.71 | -11.46 | -32.09 | 0.09 | 0.81 | -3.19 |
| SXPUSDT | calm | 139014 | 0.62 | 0.52 | -7.64 | -14.74 | -0.15 | 1.15 | -2.85 |
| SXPUSDT | crash | 5020 | 0.06 | 0.85 | -12.79 | -42.35 | 0.45 | 0.91 | -3.09 |

On the crash day the bid side (long inventory into a falling market) takes the damage: p5/p1 left tail roughly doubles vs calm and the bid-side mean drops sharply, while the ask side partly offsets. Note one-day sample (fills capped at 2880/side/day by the bucket rule).

## 5. BTC control sanity

BTC time-weighted spread 0.037bp (one tick). RT gross at 30s = -0.01bp, net of 2bp fees = -4.01bp; NW t gross -3.1. Expected ~0/negative: **PASS** (no strongly profitable BTC -> no evidence of a simulator bug producing free money). Sanity ordering also holds: RT gross rises monotonically with the quoted spread (ETH/BTC ~0, SOL slightly negative, DOGE ~+0.9, SXP ~+1.1-1.4).

## 6. Go / no-go per symbol (OPTIMISTIC net RT > 0 at 2bp fee AND NW significant AND tail not ruinous)

- BTCUSDT: CONTROL (no-go by design)  (30s RT net@2bp -4.01bp; net@1bp -2.01; net@0bp -0.01; p5/fill -4.0bp)
- ETHUSDT: NO-GO  (30s RT net@2bp -4.04bp; net@1bp -2.04; net@0bp -0.04; p5/fill -4.1bp)
- SOLUSDT: NO-GO  (30s RT net@2bp -4.27bp; net@1bp -2.27; net@0bp -0.27; p5/fill -9.0bp)
- DOGEUSDT: NO-GO  (30s RT net@2bp -3.10bp; net@1bp -1.10; net@0bp 0.90; p5/fill -6.4bp)
- SXPUSDT: NO-GO  (30s RT net@2bp -2.86bp; net@1bp -0.86; net@0bp 1.14; p5/fill -7.7bp)

**Verdict: no instrument passes at the headline 2bp maker fee, even with the front-of-queue upper bound.** Gross round-trip edge is at most ~1.4bp (SXP 1s) against a 4bp round-trip fee; it is also negative for the tight-spread names. At 0bp fee (rebate/market-maker program) DOGE and SXP are positive and statistically significant on the upper bound, but that needs a fee tier we do not have, ignores queue position/latency/inventory, and each fill carries a p5 left tail of -6 to -8bp at 30s (worse on the crash day), i.e. several times the average edge. At 1bp fee still negative. Recommendation: market making is NOT viable for us at retail fees; stop (do not proceed to Phase B) unless a ~0bp maker tier is realistically obtainable, in which case only DOGE/SXP-type wide-spread alts merit a paper test, and expectation should be low.

## 7. SELF-AUDIT
- Fill rule optimistic: every trade at/through our level fills us at front of queue with zero latency and no min-size/partial fill; no queue position, no cancel/replace cost, no inventory risk. Upper bound only.
- Future mid is used only as measurement of the realised mark-out, never as a signal or to decide fills/placement.
- Event-time alignment: quote state = last bookTicker event_time strictly before the trade transact_time; mark-out mid = last event <= t+h. Binance event_time vs transact_time clocks may differ by ms; this is not tested and affects 1s results least-reliably.
- DATA CAVEAT: the 2023 archive bookTicker is sparse (e.g. ETH ~20k distinct states/day, SXP ~15-50k) so quotes may be stale versus the live book; a stale bid makes "trade <= bid" fills slightly too frequent (optimistic) and mid_h lag adds noise. Direction of bias: optimistic fill count, unclear on mark-out sign.
- No double counting: max one fill per side per 30s bucket; windows non-overlapping. Side mean means and pairing are per-hour; the paired NW t is on 24-lag hourly series (short, 31 days: weak for tails).
- Symbols/window/fees fixed before data; the one a-priori choice of SXP over alternatives was made before running the sim. Tier ranks are judgement, not 2023 volume data.
- Disk streaming: one symbol-day at a time, zip downloaded to data/mm/raw, raw deleted in finally block; only per-fill parquet (data/mm/fills, gitignored) kept. Peak extra disk under ~0.5GB.
- Bucket rule caps fills/day (5758 per 2880 buckets x2 saturated for liquid names), so fill counts are not realistic volumes; per-fill averages are the metric.
- Not done: queue-position modelling, latency, inventory/skew, funding, real fees tiers. Single month, single regime.
