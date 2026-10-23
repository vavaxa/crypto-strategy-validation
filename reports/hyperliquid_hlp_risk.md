# Hyperliquid HLP: a ~$37M mechanical loss cap, procyclical capital, and a backstop that ends in ADL

*Independent risk note. Snapshot: 2026-10-22 (live cross-checks 2026-10-23), from the keyless Hyperliquid
`info` API. Reproducible — collector and calculations in
[`research/hl_collect.py`](../research/hl_collect.py),
[`research/hl_analysis.py`](../research/hl_analysis.py),
[`research/hl_risk_calcs.py`](../research/hl_risk_calcs.py),
[`research/hl_figures.py`](../research/hl_figures.py).*

## Summary

The common framing — "HLP is a ~$177M insurance fund, compare it to open interest" — is wrong on the
numerator, the mechanism, and the denominator. Working from the public vault data and the protocol docs:

1. **Depositor losses are mechanically capped at the perp account's equity (~$37.3M), then ADL takes
   over.** Auto-deleveraging triggers when an account's value goes negative and closes opposite positions
   at the previous mark price, "ensuring that the platform has no bad debt" [[2]](#sources). So the HLP
   perp account — live `clearinghouseState.accountValue` **$37.3M, zero open positions, ~fully
   withdrawable** — is a *hard ceiling* on what depositors can lose before the loss is socialised by ADL,
   not a "small share" of $177M.
2. **That capital is procyclical and leaves under stress.** Equity fell from a sampled peak of $603.9M to
   $177.4M — **−$489M of withdrawals against +$63M of PnL**, i.e. zero losses. It happened once sharply
   (Mar-2025, five weeks) and again as a 13-month monotonic drain since Sep-2025. A backstop whose capital
   reprices downward over time is the opposite of a growing reserve.
3. **Only ~21% of the headline capital is locatable in public accounts.** The vault address shows $37.3M
   of perp equity and **zero** spot balances; the other **$139.8M** of the reported $177.4M portfolio
   equity does not appear at the vault or leader address. Likely sub-accounts/component strategies — but
   not exposed by the public API, which is itself the finding.

And the genuinely thin margin cushion is **BTC/ETH at max leverage (~0.83% / ~1.33% of notional)**, the
deepest books — not the low-OI alts a "share-of-OI" lens would flag.

## Background: book → liquidator vault → ADL

Per the Hyperliquid docs [[1]](#sources)[[2]](#sources):

- **Tier 1 — the book.** "The positions are first attempted to be entirely closed by sending market
  orders to the book."
- **Tier 2 — the liquidator vault.** "Positions that are below 2/3 of the maintenance margin can be taken
  over by the liquidator vault, which is a component strategy of HLP." Maintenance margin "is half of the
  initial margin at max leverage, which varies from 3-40x."
- **Tier 3 — ADL.** "If a user's account value … becomes negative," opposite-side traders "are ranked by
  unrealized pnl and leverage used" and "their positions are closed at the previous mark price against the
  now underwater user, ensuring that the platform has no bad debt."

Two consequences the "insurance fund" framing misses. First, HLP depositors are the *second* line, and
their loss is **capped** at the liquidator-vault/perp-account capital: past that, ADL — not the fund —
absorbs the residual. Second, ADL does not *reimburse* the vault; it **caps** the vault's loss by closing
solvent traders' opposite positions at the previous mark (the cost comes out of those traders' unrealised
gains, not a payment into the vault).

## Data and method

One point-in-time snapshot of the public `info` endpoint (`meta`, `metaAndAssetCtxs`, `vaultDetails` for
`0xdfc24b077bc1425ad1dea75bcb6f8158e10df303`), plus live `clearinghouseState` / `spotClearinghouseState`
cross-checks. The collector stores the raw payload; analysis is pure post-processing.

**Granularity caveat (up front):** `vaultDetails` resolves full history only at ~14-day steps (sub-daily
only for the last ~31 days). Reproducible figures are the aggregates (cumulative PnL, decomposition,
σ); the `allTime` bucket *edges* are **not** stable (the API re-buckets each snapshot), so individual
interval dates are indicative and all extremes below are **sampled/observed**, not true extrema.

## Finding 1 — a ~$37M hard cap, and ~79% of the headline capital isn't in public accounts

The $177.4M is HLP's total portfolio equity. The capital that actually fronts backstop liquidations is the
**perp account**: live `clearinghouseState` reports **accountValue ≈ $37.3M, zero open positions, and
essentially all of it withdrawable**; the snapshot's `perpAllTime` slot agrees (~$37.6M). Because ADL
guarantees "no bad debt" by socialising beyond that point, **~$37.3M is a mechanical ceiling on depositor
loss**, not a fraction to be divided into OI. (The liquidator vault is *one* component strategy of the
perp slot, so its own capital is **at most** ~$37.3M.)

Where is the other **$139.8M** ($177.4M − $37.6M)? Not at the vault address: its spot balances are
**empty**, and the leader address holds ~$464 plus dust. So the public API, queried at the vault, accounts
for only **~21%** of the reported portfolio equity. The likely explanation is sub-accounts or component
strategies not exposed by address-level queries — but as it stands, **79% of HLP's stated capital is not
publicly locatable**, which is a transparency gap a depositor cannot independently verify.

*What would falsify this:* Hyperliquid naming the accounts/strategies holding the other $139.8M, or the
liquidator vault being capitalised above the perp account. Neither is visible in the current API/docs.

## Finding 2 — the capital is procyclical (the real buffer risk)

![HLP equity, cumulative PnL and net deposits](hl_equity_vs_pnl.svg)

Decomposing `equity = net deposits + cumulative PnL`:

- From the **sampled peak 2025-09-03** ($603.9M) to now ($177.4M): **dEquity −$426.5M = PnL +$62.6M +
  net flows −$489.1M.** The contraction is depositors leaving, not losses.
- **Mar-2025:** $509M → $150M in five weeks (~−$357M), almost all flows; the interval containing the JELLY
  resolution had **+$1.24M of PnL and −$160.3M of net outflow** — the event is invisible in the *PnL*
  curve but very visible in *capital*.

So the pattern is one sharp five-week drain (Mar-2025) and a **13-month monotonic decline since Sep-2025**.
The monotonicity matters more than the speed: this looks like a steady **repricing of the yield down**, not
a panic — and it means HLP's loss-absorbing capital is largest in calm markets and thinnest after stress.

*Note on withdrawals:* `vaultDetails.maxWithdrawable` is caller-relative (0 for a non-depositor) and is
**not** evidence of a lockup; HLP's deposit-lock terms would modulate exit speed but do not change the
observed multi-month drain. This finding rests on the equity/PnL/flow decomposition, which is exact.

## Finding 3 — the thin cushion is BTC/ETH at max leverage; worst events are idiosyncratic

Maintenance margin is **half the initial margin at max leverage** [[1]](#sources), so the cushion before
the liquidator vault is underwater on an inherited position ≈ (2/3)·MM of notional:

| Max leverage | Maintenance margin | Cushion ≈ (2/3)·MM | Example |
|---|---|---|---|
| 40x | 1.25% | **0.83%** | BTC |
| 25x | 2.00% | **1.33%** | ETH |
| 20x | 2.50% | 1.67% | SOL |
| 10x | 5.00% | 3.33% | HYPE |
| 5x | 10.0% | 6.67% | ATOM |
| 3x | 16.7% | 11.1% | long tail |

The thinnest cushions are on the **deepest books (BTC, ETH)** at max leverage — a gap through <1.3% of
notional hands the vault an underwater position — *not* the low-OI alts a share-of-OI lens flags.

Separately, the worst realized backstop event was **not** market beta. JELLY (Mar-2025) was a manipulated,
thinly-listed market: Halborn reports that "when losses reached **$12 million**, the protocol's validators
rapidly … delist[ed] the $JELLY token," settling at $0.0095 vs the $0.50 listing [[3]](#sources). The
point stands independent of the exact figure:

> ~14-day interval nets are **not** event losses. The largest known event loss (~$12M on JELLY) exceeds
> the worst *observed* interval (−$4.66M, a statistically unremarkable z = −1.31), which is exactly why the
> realized curve cannot be read as a measure of the tail.

## A labelled scenario (not a prediction): HYPE reflexivity

HYPE — the ecosystem's own token — is 13.8% of OI ($1.6B) at 10x. The API gives no long/short split;
funding is positive (longs pay), so longs likely dominate, but this is **not sized**, so `f` is an
uncalibrated assumption. Using the Finding-3 cushion, an inherited HYPE position only costs the vault
beyond its 3.33% margin, so loss `= f · $1.6B · max(0, c − 3.33%)`, against the **~$37.3M** perp cap:

| f \ c | 5% | 10% | 20% | 30% |
|---|---|---|---|---|
| 5% | 4% | 14% | 36% | 57% |
| 10% | 7% | 29% | 71% | 114% |
| 20% | 14% | 57% | **143%** | 228% |

(loss as % of the ~$37.3M perp cap). At f = 20%, c = 20% the loss is ~$54M — the liquidator vault is
exhausted and the remainder routes to ADL. This follows from the protocol's own cushion mechanics; it is a
sensitivity point, not a forecast.

## Other sign-sensitive channels

- **USDC depeg.** HLP's capital is USDC-denominated; a depeg (cf. Mar-2023) hits the buffer directly, with
  no market move required — a risk orthogonal to everything above.
- **Validator concentration.** The one true near-miss (JELLY) was resolved by **delisting**, a 2/3
  stake-weighted validator vote. The third backstop tier therefore rests on a small set of operators;
  depositors should price validator discretion, not an automatic rule.

## Recommendations

**For an HLP depositor.** The ~3.65% APR is *not* tail compensation — it is mechanically a
shrinking-base artifact: as capital fell $604M → $177M, the same PnL over less capital raises the APR. A
rising HLP APR signals a thinner buffer. Your loss is capped at the ~$37M perp account; beyond it you are
subject to ADL on the other side of the book, and ~79% of the headline capital is not publicly locatable.

**For a risk mandate.** Deposit/withdraw flows are already public (`userNonFundingLedgerUpdates`,
paginated, since 2023-05-04), so the ask is not "disclose flows." Ask for (a) the accounts/strategies
holding the unlocated $139.8M, and (b) intra-event HLP PnL and inherited inventory by market — the only
data that would let anyone evidence tail safety. Then cap single-market backstop concentration (HYPE
first, for reflexivity).

**For validators.** Make the trigger and process for discretionary intervention (as in the JELLY delist)
explicit; an implicit, stake-weighted backstop-of-last-resort should not be priced by depositors as if it
were automatic.

## Limitations

- One public snapshot; no privileged or trade-level data; ~14-day history resolution hides intra-event
  dynamics. Extremes quoted are sampled/observed, not true extrema.
- The liquidator-vault ≤ perp-account identification rests on the docs ("a component strategy of HLP") and
  the live `clearinghouseState` perp account; Hyperliquid does not publish the vault's capital separately,
  and $139.8M of portfolio equity is not locatable in public accounts (possible sub-accounts).
- The JELLY magnitude is Halborn's single figure; the HYPE scenario's `f`, `c` are assumptions.
- Independent analysis, not an audit, not affiliated with Hyperliquid.

## Sources

1. Hyperliquid docs — Liquidations: https://hyperliquid.gitbook.io/hyperliquid-docs/trading/liquidations
   ("first attempted to be entirely closed by sending market orders to the book"; "below 2/3 of the
   maintenance margin … taken over by the liquidator vault, which is a component strategy of HLP";
   "maintenance margin is half of the initial margin at max leverage, which varies from 3-40x").
2. Hyperliquid docs — Auto-deleveraging: https://hyperliquid.gitbook.io/hyperliquid-docs/trading/auto-deleveraging
   ("If a user's account value … becomes negative"; ranked "by unrealized pnl and leverage used"; "closed
   at the previous mark price against the now underwater user, ensuring that the platform has no bad debt").
3. Halborn — "Explained: The Hyperliquid JELLY incident (March 2025)":
   https://www.halborn.com/blog/post/explained-the-hyperliquid-hack-march-2025 ("when losses reached $12
   million … delist the $JELLY token"; settled valuing $JELLY at $0.0095 vs the $0.50 listing).
4. HLP vault `0xdfc24b077bc1425ad1dea75bcb6f8158e10df303` via the public `info` API (`vaultDetails`,
   `clearinghouseState`, `spotClearinghouseState`) — primary data.

## Reproducibility

```bash
python research/hl_collect.py        # snapshot the public API into data/hl/ (git-ignored)
python research/hl_analysis.py       # factual summary
python research/hl_risk_calcs.py     # the findings' numbers
python research/hl_figures.py        # the equity / PnL / net-deposits chart (SVG)
```

*Not financial advice. Independent research for discussion.*
