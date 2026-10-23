# Hyperliquid HLP: procyclical capital, idiosyncratic losses, and a backstop that leans on ADL

*Independent risk note. Snapshot: 2026-10-22, from the keyless Hyperliquid `info` API.
Reproducible — collector and calculations in
[`research/hl_collect.py`](../research/hl_collect.py),
[`research/hl_analysis.py`](../research/hl_analysis.py),
[`research/hl_risk_calcs.py`](../research/hl_risk_calcs.py),
[`research/hl_figures.py`](../research/hl_figures.py).*

## Summary

A common framing is "HLP is a ~$177M insurance fund backstopping Hyperliquid, so compare it to open
interest." That framing is wrong on both the numerator and the mechanism. Working from the public
vault data and the protocol docs, three findings:

1. **The backstop is three-tier, and the capital that actually fronts it is ~$38M, not $177M.**
   Liquidations hit the order book first; only positions below **2/3 of maintenance margin** are taken
   over by the *liquidator vault* — "a component strategy of HLP" [[docs]](#sources) — and anything
   beyond that socialises through **auto-deleveraging (ADL)**, the docs' "final safeguard." HLP's perp
   slot (which houses that strategy) is **$37.6M**, and `maxDistributable` equals it to the dollar; the
   $177M headline includes capital that is not first-loss backstop.
2. **HLP capital is procyclical — it shrinks via withdrawals, not losses, exactly when it matters.**
   Equity fell 71% from its $603.9M peak, but that was **−$489M of depositor withdrawals against
   +$63M of PnL** — zero dollars of loss. This has happened twice in weeks (Mar-2025 and Sep-2025→now).
   A backstop that is smallest right after stress is a feature worth pricing.
3. **The genuinely thin cushion is BTC/ETH at max leverage — not the low-OI alts.** Maintenance margin
   is half the initial margin at max leverage, so the cushion before the liquidator vault is underwater
   is **~0.83% of notional on BTC (40x) and ~1.33% on ETH (25x)**, versus ~11% on a 3x long-tail asset.
   And the worst *realized* event (JELLY) was idiosyncratic — an oracle/listing/manipulation failure
   resolved by **validator governance** (market delisting) plus ADL, not by the buffer absorbing it.

Net: HLP's demonstrated safety reflects (a) a regime in which book liquidity has absorbed most flow,
(b) a capital base that leaves precisely when tested, and (c) a true backstop of last resort that is
*other traders (ADL) and validators*, not a thick fund. None of this is visible if you divide $177M
by open interest.

## Background: the three-tier liquidation path

Per the Hyperliquid docs (see [Sources](#sources)):

- **Tier 1 — the book.** "The positions are first attempted to be entirely closed by sending market
  orders to the book."
- **Tier 2 — the liquidator vault.** "If the account equity drops below 2/3 of the maintenance margin
  without successful liquidation through the book," then "positions that are below 2/3 of the
  maintenance margin can be taken over by the liquidator vault, which is a component strategy of HLP."
- **Tier 3 — ADL.** "Auto-deleveraging is an important final safeguard on the solvency of the
  platform"; a user "who has no open positions will not socialize any losses of the platform."

So HLP depositors are not a first-instance insurance fund — they are the *second* line, capitalised at
the liquidator-vault/perp-slot level, with ADL socialising the residual to profitable counterparties.

## Data and method

All figures come from one point-in-time snapshot of the public `info` endpoint
(`meta`, `metaAndAssetCtxs`, and `vaultDetails` for the HLP vault
`0xdfc24b077bc1425ad1dea75bcb6f8158e10df303`). The collector stores the raw payload; the analysis is
pure post-processing. **Reproducible aggregates** are the cumulative-PnL, mean, σ and decomposition
figures below; the *bucket edges* of the `allTime` window are **not** stable (the API re-buckets to
~101 points on every snapshot), so individual interval dates are indicative, not fixed.

## What the record shows (observations)

| Metric | Value |
|---|---|
| HLP equity | **$177.4M** = net deposits $38.6M + cumulative PnL $138.8M |
| Equity peak | $603.9M (2025-09-03) → now −71%, **all of it withdrawals** |
| Perp/strategy slot (fronts the liquidator vault) | **$37.6M** (peak $309.3M, −88%); `maxDistributable` = $37.637M (≡ slot); `maxWithdrawable` = $0 |
| Cumulative PnL since 2023-05 | +$138.8M |
| ~14-day interval PnL (n=100) | mean +$1.39M, σ $4.62M; best +$41.44M (z=8.66), worst −$4.66M (z=−1.31) |
| Skew | **7.0 — of which ~6.5 is one interval** (Oct-2025); 4.7 without it |
| Total perp OI | **$11.6B**; BTC 30.7% + ETH 22.8% + HYPE 13.8% = 67% |
| Leverage caps (234 perps) | 3x: 130 · 5x: 63 · 10x: 35 · 20x: 4 · 25x: 1 (ETH) · 40x: 1 (BTC) |
| Reported APR / leader commission | 3.65% / 0 |

The return series is positively skewed, and the skew is essentially one windfall — not evidence of a
structurally benign distribution from 100 points.

## Finding 1 — the backstop capital is ~$38M, and the tail routes to ADL

The $177M is HLP's total equity across its component strategies. The liquidator vault that actually
takes over sub-2/3-MM positions is one *perp* strategy; the snapshot's perp slot is **$37.6M**, and the
vault's `maxDistributable` equals that figure to the dollar. Beyond the liquidator vault's capacity,
losses do not draw down "the fund" — they socialise via **ADL** onto the most-profitable opposing
positions. The real backstop of last resort is therefore other traders and, in the extreme, validator
intervention — not a thick reserve.

*What would falsify this:* Hyperliquid disclosing that the liquidator vault is capitalised well above
the perp slot (e.g. can draw on the full $177M), or ADL being bounded/insured such that socialisation
cannot reach solvent traders. Neither is stated in the current docs.

## Finding 2 — the capital is procyclical (and that is the real buffer risk)

![HLP equity vs cumulative PnL](hl_equity_vs_pnl.svg)

Decomposing `equity = net deposits + cumulative PnL`:

- From the **2025-09-03 peak** ($603.9M) to now ($177.4M): **dEquity −$426.5M = PnL +$62.6M + net flows
  −$489.1M.** The contraction is depositors leaving, not losses.
- **Mar-2025:** equity ran $509M → $150M in five weeks (~−$357M), again almost entirely flows; the
  interval containing the JELLY resolution (delisting ~03-26) had **+$1.24M of PnL and −$160.3M of net
  outflow**. The event is invisible in the *PnL* curve but very visible in *capital*.

The risk this surfaces is not "the fund took a loss"; it is that **HLP's loss-absorbing capital is
largest in calm markets and contracts fastest around stress**, because the same events that stress the
backstop also prompt depositors to withdraw. A buffer that mean-reverts downward under stress is the
opposite of what a backstop should do.

*What would falsify this:* evidence that deposits are sticky or lock up through stress (they do not —
`maxWithdrawable` fluctuates and the Mar/Sep episodes show fast exits), or a protocol-owned,
non-withdrawable first-loss tranche.

## Finding 3 — the thin cushion is BTC/ETH at max leverage; the worst events are idiosyncratic

Maintenance margin is **half the initial margin at max leverage**, so the cushion before the liquidator
vault is underwater on an inherited position ≈ (2/3)·MM of notional:

| Max leverage | Maintenance margin | Cushion ≈ (2/3)·MM | Example |
|---|---|---|---|
| 40x | 1.25% | **0.83%** | BTC |
| 25x | 2.00% | **1.33%** | ETH |
| 20x | 2.50% | 1.67% | SOL |
| 10x | 5.00% | 3.33% | HYPE |
| 5x | 10.0% | 6.67% | ATOM |
| 3x | 16.7% | 11.1% | long tail |

The thinnest cushions sit on the **deepest books (BTC, ETH)** at max leverage — where a gap through
<1% of notional hands the vault an underwater position — *not* on the low-OI alts that a
"share-of-OI" lens flags. OI concentration and tail fragility point at different assets.

Separately, the worst *realized* backstop event to date was **not** market beta. JELLY (Mar-2025) was a
manipulated, thinly-listed market: public post-mortems put the unrealized hit at **roughly
$10–13.5M** before validators **delisted the market** and settled at an oracle price, leaving HLP
~+$0.7M [[Halborn]](#sources). POPCAT is reported at ~−$4.9M [[reports]](#sources); notably it does
**not** show up as a negative ~14-day interval in the vault curve. That is the point:

> ~14-day interval nets are **not** event losses. The largest *known event* losses (≈−$4.9M POPCAT,
> ≈−$10–13.5M mark on JELLY) exceed the worst observed interval (−$4.66M, a statistically unremarkable
> z = −1.31) — which is exactly why the realized curve cannot be read as a measure of the tail.

*What would falsify this:* trade-level HLP data showing inherited BTC/ETH inventory consistently
unwound inside the cushion, or the idiosyncratic events being contained by capital rather than by
delisting. The public data can neither confirm nor refute this at the needed resolution — which is
itself the finding.

## A labelled scenario (not a prediction): HYPE reflexivity

HYPE — the ecosystem's own token — is 13.8% of OI ($1.6B) at 10x. The API gives no long/short split;
funding is positive (longs pay), so longs likely dominate, but this is **not sized**, so the
inheritance fraction `f` below is an uncalibrated assumption. Loss `= f · $1.6B · c` (c = adverse
unwind cost), against the **~$38M** perp/liquidator capital:

| f \ c | 5% | 10% | 20% | 30% |
|---|---|---|---|---|
| 5% | 11% | 21% | 43% | 64% |
| 10% | 21% | 43% | 86% | 128% |
| 20% | 43% | 86% | 171% | 257% |

(loss as % of the ~$38M perp capital). At f = 20%, c = 30% the loss is ~$97M — the liquidator vault is
exhausted several times over and the remainder routes to ADL. The purpose is sensitivity, not forecast:
it shows the backstop's first-loss capital is small relative to a single concentrated, reflexive market.

## Recommendations

**For an HLP depositor.** The ~3.65% APR is *not* compensation for the tail — it is mechanically a
shrinking-base artifact: as capital fell $604M → $177M, the same PnL divided by less capital raises the
APR. A rising HLP APR is a signal of a thinner buffer, not a thicker cushion. Size exposure to a vault
whose first-loss capital is ~$38M, whose worst case routes to ADL, and whose capital leaves under
stress.

**For a risk mandate.** The highest-value transparency ask is **not** "disclose flows" — deposit/
withdraw flows are already public via `userNonFundingLedgerUpdates` (paginated, since 2023-05-04). Ask
instead for **intra-event HLP PnL and inherited inventory by market**, which is the only thing that
would let anyone evidence tail safety. Then cap single-market backstop concentration, treating HYPE
explicitly for its reflexivity.

**For validators.** Because the one true near-miss (JELLY) was resolved by **delisting** — a 2/3
stake-weighted governance action — the backstop-of-last-resort is validator discretion. Make the
trigger and process for such intervention explicit; an implicit discretionary backstop should not be
priced by depositors as if it were automatic.

## Limitations

- One public snapshot; no privileged or trade-level data. `vaultDetails` resolves full history only at
  ~14-day steps (sub-daily only for the last ~31 days), so intra-event dynamics are not observable.
- The liquidator-vault = perp-slot identification rests on the `maxDistributable` match and the docs'
  "component strategy of HLP"; Hyperliquid does not publish the vault's capital separately.
- Incident magnitudes are from public post-mortems (secondary) and vary by source; used for mapping,
  not re-derived. The HYPE scenario's `f`, `c` are assumptions.
- Independent analysis, not an audit, not affiliated with Hyperliquid.

## Sources

1. Hyperliquid docs — Liquidations: https://hyperliquid.gitbook.io/hyperliquid-docs/trading/liquidations
   (verbatim: "first attempted to be entirely closed by sending market orders to the book"; "below 2/3
   of the maintenance margin … taken over by the liquidator vault, which is a component strategy of
   HLP"; "maintenance margin is half of the initial margin at max leverage, which varies from 3-40x").
2. Hyperliquid docs — Auto-deleveraging: https://hyperliquid.gitbook.io/hyperliquid-docs/trading/auto-deleveraging
   ("an important final safeguard on the solvency of the platform"; a user "who has no open positions
   will not socialize any losses").
3. Halborn — "Explained: The Hyperliquid JELLY incident (March 2025)":
   https://www.halborn.com/blog/post/explained-the-hyperliquid-hack-march-2025
4. HLP vault (`0xdfc24b077bc1425ad1dea75bcb6f8158e10df303`) via the public `info` API — primary data.

*(POPCAT / ETH-long magnitudes are from community post-mortems; exact tx references not independently
re-derived here.)*

## Reproducibility

```bash
python research/hl_collect.py        # snapshot the public API into data/hl/ (git-ignored)
python research/hl_analysis.py       # factual summary
python research/hl_risk_calcs.py     # the findings' numbers
python research/hl_figures.py        # the equity-vs-PnL chart (SVG)
```

*Not financial advice. Independent research for discussion.*
