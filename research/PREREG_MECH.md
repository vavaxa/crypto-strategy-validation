# Pre-registration — Study 2: trend / breakout on Binance USDT-perps (daily)

> **Provenance note (honest):** this file was **reconstructed from `research/mech_runner.py` at
> publication time** to match the frozen design the runner implements; it is **not** an independently
> timestamped pre-commit. The runner itself states "Grid, sizing, risk, decision rule are FROZEN;
> nothing here tunes them." Treat the ordering as documented, not cryptographically proven. (See the
> repo README "Known limitations" — splitting pre-registrations into timestamped pre-run commits is an
> open item.)

Frozen **before** inspecting results:

## Hypothesis
A cross-sectional trend/breakout signal on a basket of liquid USDT-perps earns a risk-adjusted return
that survives realistic costs and beats BTC buy-and-hold.

## Universe (point-in-time, survivorship-free)
- Top-**N=30** USDT-perps by trailing 30-day mean quote volume, ranked at each daily close using only
  days ≤ t from `klines_1d_binance` (689 symbols incl. 75+ delisted). N=30 chosen a priori as the
  "liquid majors" scale (rank-30 median ≈ $157M/day, so a $1M book is ≪10% of volume); **not tuned**.
- Delisted symbols remain members until their last bar; pegged/stable bases excluded. Window
  2020-02-18..2026-10-18; IS = first ~80%, forward holdout = last 20% (2025-06-19..).

## Signals / grid (FROZEN; = multiple-testing budget)
- Trend/breakout families (breakout channels + moving-average states) × optional funding/OI filters,
  for a fixed grid of **24 configs**. Signals on `close(t)`, applied with `shift(1)`, executed at the
  next bar's **open**. Vol-targeted sizing; long-only; $1M book.
- `n_trials` = the grid size, carried into the Deflated Sharpe / data-snooping tests. No config, filter,
  or window added by result.

## Costs
Taker fee 0.00045 + square-root impact `max(0.5bp, impact_k·√(trade/ADV))` via `costs.impact_bps`
(ADV = trailing 30-day quote volume known before the open) + funding on held weight.
**Caveat (see repo Correction):** the published run used `impact_k=0.5`, an uncalibrated stub ~20–30×
too high; the honest per-symbol value is `k≈Y·σ`.

## Decision rule (ALL required)
1. Best config selected on IS only; OOF via purged 5-fold (embargo 2%).
2. Net Sharpe > BTC buy-and-hold **and** significant (DSR with `n_trials` = grid size; bootstrap CI
   excludes 0); White/Hansen SPA over the grid does not reject "no outperformance".
3. Holds on the forward holdout (sign-consistent).
4. Not carried by a single symbol or single regime.
Any one unmet → edge not confirmed.

## §9 — what NOT to do
- No adding configs/filters/windows by result; no re-labelling costs; no order-sending / live trading.
