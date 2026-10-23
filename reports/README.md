# Reports — quick entry

**Thesis (3 lines)**
- A methodology portfolio: overfitting-resistant validation (Deflated/Probabilistic Sharpe, PBO/CSCV,
  White/Hansen SPA, Lo-HAC, purged k-fold) applied honestly to crypto strategies and one live system.
- No studied strategy beat BTC buy-and-hold on validated terms; the cost-sensitive ones are labelled
  **INCONCLUSIVE** after a self-caught market-impact miscalibration — not "fail."
- Flagship is an **applied risk note on Hyperliquid's HLP backstop**, derived entirely from its public API.

**3 numbers**
- **~$37M** — HLP's liquidation-channel capital = a *mechanical* loss cap (ADL beyond it), not the ~$177M
  "insurance fund" headline.
- **+218 bps/yr** — basis-carry net at a calibrated impact `k≈0.02` (`net(k)=606−19394k`); the published run
  used a 20–30× impact stub and had mislabelled this a fail.
- **38/38** validation unit tests pass; the core (PSR/DSR/PBO/SPA/Lo) was independently verified correct.

**Start here**
- Applied risk note: [`hyperliquid_hlp_risk.md`](hyperliquid_hlp_risk.md) · charts
  [`hl_equity_vs_pnl.svg`](hl_equity_vs_pnl.svg), [`impact_sensitivity_basis.svg`](impact_sensitivity_basis.svg)
- Strategy synthesis + correction: [`RESEARCH_CONCLUSION.md`](RESEARCH_CONCLUSION.md)
- Code: [`../research/validation/`](../research/validation/) (the stack) ·
  [`../research/execution/costs.py`](../research/execution/costs.py) ·
  [`../research/hl_risk_calcs.py`](../research/hl_risk_calcs.py) (HLP numbers)
- Full overview: [`../README.md`](../README.md)

Per-study reports: trend `mech_trend` · funding carry `carry` · overlay `overlay` · basis `basis_carry` ·
BTC timing `btc_timing` · short-vol/VRP `vrp` · market-making `mm_markout` (each `.md` + `.json`).
