# Crypto Strategy Research & Validation Framework

A pre-registered, overfitting-resistant research pipeline for testing whether a retail-scale operator can
beat **BTC buy-and-hold net of realistic costs** — built on a single VPS, and designed above all *not to
fool the researcher*.

> **Headline result:** across **8 pre-registered strategy families**, no tradeable edge survived realistic
> costs and out-of-sample testing. This repo documents the method, the data, and the honest negative result —
> including two *real but non-harvestable* risk premia it uncovered along the way.

This is a methodology portfolio. The point is not a winning strategy — it is **how to tell a real edge from
an overfit backtest**, which is the core skill in quant research and DeFi risk work.

---

## Why this exists

Most retail "quant" backtests are overfit: parameters tuned until the curve looks good, costs ignored,
survivorship bias baked in, and no honest out-of-sample test. This project inverts that. Every study was
**pre-registered** — hypothesis and pass/fail rule frozen *before* seeing results — and every verdict was
run through a formal data-snooping-aware validation stack. A negative result reported honestly is the
deliverable.

---

## Methodology (the actual value)

**1. Pre-registration.** For each study, a `PREREG_*.md` freezes the hypothesis, the parameter grid
(= multiple-testing budget), the decision rule, and an explicit "what NOT to do" clause before any data is
touched. No tuning-by-result.

**2. Anti-lookahead design.** Signals computed on `close(t)`, lagged with `shift(1)`, executed at the
next bar's **open**. All cross-series merges are as-of joins. Each study carries a lookahead self-audit.

**3. Survivorship-free, point-in-time data.** The universe is reconstructed from trailing turnover and
*includes delisted symbols*, so there is no survivor bias.

**4. Realistic execution costs.** Fees + square-root market impact + participation cap, with mandatory
impact-sensitivity sweeps (×0.25–×4): no conclusion is allowed to rest on a single cost assumption.

**5. A formal validation stack** (`validation/`):
- Deflated & Probabilistic Sharpe Ratio (DSR/PSR)
- Probability of Backtest Overfitting (PBO) via CSCV
- White's Reality Check & Hansen's SPA test
- Lo-adjusted Sharpe with Newey–West HAC standard errors
- Stationary / block bootstrap confidence intervals
- Purged k-fold cross-validation with embargo
- Jobson–Korkie–Memmel Sharpe-difference significance test

---

## Repository structure

```
research/
  validation/              Reusable, tested validation library (the core asset)
    sharpe.py                DSR / PSR / Lo-adjusted Sharpe (HAC)
    overfitting.py           PBO via CSCV
    data_snooping.py         White's Reality Check, Hansen SPA
    bootstrap.py             stationary / block bootstrap
    cross_validation.py      purged k-fold + embargo
    regimes.py               regime splits / change-points
    test_validation.py       unit tests (synthetic data — no downloads needed)
  execution/
    costs.py                 fee + sqrt-impact + participation-cap cost model
    test_costs.py            unit tests
  strategy/
    trend.py                 signal construction + anti-lookahead
    test_trend.py            lookahead unit test (future bar must not change t)
  mech_collect.py            point-in-time, survivorship-free data layer (Binance/Bybit)
  spot_collect.py            spot klines back to 2017
  vrp_fetch.py               Deribit DVOL implied-vol series
  mech_runner.py             study 2 — cross-sectional trend / breakout
  carry_runner.py            study 3 — funding carry (long-biased)
  overlay_runner.py          study 4 — carry as an overlay to a BTC core
  basis_runner.py            study 5 — delta-neutral basis carry (cash-and-carry)
  btc_timing_runner.py       study 6 — single-asset BTC in/out timing
  vrp_runner.py              study 7 — short-vol / variance-risk-premium
  mm_markout.py / mm_report.py  study 8 — market-making mark-out / adverse selection
  PREREG_*.md                frozen pre-registrations (hypothesis + rule, pre-data)
  LITERATURE_BENCHMARK.md    how findings line up with published literature

reports/
  RESEARCH_CONCLUSION.md     master synthesis (read this first)
  mech_trend / carry / overlay / basis_carry / btc_timing / vrp / mm_markout  (.md + .json)

data/
  DATA_MANIFEST.md           exact sources, windows, and symbols
```

> **Data is not committed.** All price/funding/OI/spot/vol data is reconstructible from public APIs
> (Binance, Bybit, Deribit) and is `.gitignore`d. See `data/DATA_MANIFEST.md` for exact sources and windows.
> The unit-test suite runs on synthetic data and needs no downloads.

---

## The 8 studies

| # | Hypothesis | Premium real? | Verdict | Why it fails for retail |
|---|------------|---------------|---------|--------------------------|
| 1 | On-chain inflow → pump | no | ✗ | marker is causal but gross move ≈ 0 |
| 2 | Trend / breakout, 30-alt basket | no | ✗ (0/7) | gross < BTC; alt market-impact dominates |
| 3 | Funding carry (long-biased) | **yes** (+564 bps/yr, t≈4.8) | ✗ | small, doesn't beat BTC, doesn't scale |
| 4 | Carry as overlay to BTC | — | ✗ | corr 0.66 with BTC = beta, not hedge; dilution |
| 5 | Delta-neutral basis carry | **yes & uncorrelated (~0)** | ✗ | 46×/yr turnover × 2 legs = net negative |
| 6 | Single-asset BTC timing | point-wise (SR 1.29 vs 0.93) | ✗ | not significant (CI includes 0) = dilution |
| 7 | Short-vol / VRP (DVOL) | **yes** (+8.4 vol-pts, t≈5.4) | ✗ | ruinous tail, fails holdout, decaying |
| 8 | Market-making (mark-out) | spread grows with spread, < fee | ✗ | even front-of-queue, captured spread < maker fee; tail p5 −6…−8 bp > edge |

All three axes of trading profit were tested — **price prediction, risk-premium harvest, and liquidity
provision** — and the cost wall held on every one.

---

## Key findings

- **Two structural walls.** (1) *Costs × turnover* kills everything that trades actively; the only
  cost-immune instrument (BTC) carries no signal. (2) *Sample length* — crypto has only ~1.5–2 full cycles,
  so slow regime effects (study 6) and tail non-ruin (study 7) cannot be confirmed statistically even if a
  modest real effect exists.
- **Real premia exist but don't net-harvest at retail scale.** Funding carry, delta-neutral basis, and the
  volatility risk premium are all statistically real — but each is either eaten by turnover/costs, or is
  payment for crash risk (short-vol is +0.81 correlated with BTC on crash days), and **all decay over time**
  (a signature of being arbitraged away).
- **The honest baseline wins.** Holding BTC sized to risk tolerance was the only thing that did not lose to
  itself net of costs. An optional ~100/200-day regime filter roughly halved historical drawdown but is
  **not statistically validated** — a comfort tool, not alpha.

---

## Reproducing

```bash
pip install -r requirements.txt
python -m pytest research/validation research/execution research/strategy   # test suite, no downloads
python research/mech_collect.py                 # rebuild the data layer from public APIs
python research/carry_runner.py                 # then re-run any study
```

---

## Not financial advice

This is a research and methodology demonstration. Nothing here is investment advice, and the negative
result is the point: it documents where edges *do not* survive honest testing.
