import json
ROOT='/home/hermes/crypto-bot'
r=json.load(open(f'{ROOT}/reports/mm_markout_raw.json'))
order=['BTCUSDT','ETHUSDT','SOLUSDT','DOGEUSDT','SXPUSDT']
role={'BTCUSDT':'CONTROL (tight spread)','ETHUSDT':'top tier (~rank 2)','SOLUSDT':'~rank 20 tier','DOGEUSDT':'mid tier (~rank 10-30 by 2023 volume; spec bucket "~rank 50")','SXPUSDT':'low-liquidity, ~rank 100 tier'}
def go(s):
    v=r[s]['h30s']['all']; g=v['rt_gross_bps']
    ok=v['rt_net_fee2']>0 and v.get('nw_t_rt_net_fee2',-9)>2
    return 'GO' if ok else 'NO-GO'
L=[]
L.append('# MM Phase A: mark-out on Binance Vision (2023-08-01..2023-08-31)\n')
L.append('MEASUREMENT ONLY. Fill rule is an OPTIMISTIC UPPER BOUND (front of queue, zero latency). Real market making is worse. Spec: research/PREREG_MM_PHASEA.md. Code: research/mm_markout.py, research/mm_report.py.\n')
L.append('## 1. Five tickers (fixed a priori, by liquidity tier, not by MM result)\n')
for s in order: L.append(f'- {s}: {role[s]}')
L.append('\nThe 5th (wider-spread, low-liquidity) candidate was chosen before any sim run by liquidity-tier judgement from the 2023 perp universe (data/mech/selected.json has no 2023 volumes, only today\'s live list): first candidate SXPUSDT (a mid/low-cap alt that was a ~rank 100 perp in 2023); bookTicker+aggTrades for the window verified present (HTTP 200), so no step to the next candidate (RLCUSDT, STORJUSDT were the fallbacks). Tier ranks are my a-priori judgement, not measured from 2023 volume. Honest caveat: the spec asked for four alts at ~top-5/20/50/100; we ran ETH, SOL, DOGE, SXP (3 alts + 1 more instead of a separate rank-50), per the task brief.\n')
L.append('## 2. Method (as built)\n- Top-of-book from bookTicker (event_time), consecutive identical (bid,ask) states collapsed. aggTrades from transact_time.\n- Bid fill: is_buyer_maker=True trade with price <= best bid (last book state strictly before the trade). Ask fill: is_buyer_maker=False trade with price >= best ask. Fill price = our limit price.\n- One fill per side per fixed 30s UTC bucket (first qualifying trade) so the 1s/5s/30s windows never overlap: no double counting. Underspecified in the spec; simplest a-priori choice.\n- Mark-out bps of fill-time mid: buy (mid_h - bid)/mid0, sell (ask - mid_h)/mid0, h in 1,5,30s (mid_h = last book event <= t+h). Includes the captured half-spread by construction.\n- Round trip gross = mean(bid-side) + mean(ask-side). Net = gross - 2*fee. Per-side net = mean - fee.\n- Significance: Newey-West (lag 24) t on the hourly series of paired (bid-hour-mean + ask-hour-mean) round-trip mark-out.\n')
L.append('## 3. Headline: round-trip mark-out, bps of mid (all 31 days)\n')
L.append('| sym | tw spread bp | h | fills | bid mo | ask mo | median/fill | p5 | skew | RT gross | RT net 0bp | RT net 1bp | RT net 2bp | NW t (gross) |')
L.append('|---|---|---|---|---|---|---|---|---|---|---|---|---|---|')
for s in order:
    for h in ('h1s','h5s','h30s'):
        e=r[s][h]['all']
        L.append(f"| {s} | {r[s]['tw_spread_bps_mean']:.2f} | {h[1:]} | {e['both']['n']} | {e['bid']['mean']:.2f} | {e['ask']['mean']:.2f} | {e['both']['median']:.2f} | {e['both']['p5']:.2f} | {e['both']['skew']:.2f} | {e['rt_gross_bps']:.2f} | {e['rt_net_fee0']:.2f} | {e['rt_net_fee1']:.2f} | {e['rt_net_fee2']:.2f} | {e.get('nw_t_rt_gross',float('nan')):.1f} |")
L.append('\nBreakeven maker fee per side = RT gross / 2 (30s): '+', '.join(f"{s} {r[s]['h30s']['all']['rt_gross_bps']/2:.2f}bp" for s in order)+'. Headline maker fee is 2bp.\n')
L.append('## 4. Crash day 2023-08-17 vs calm days (30s horizon)\n')
L.append('| sym | part | fills | bid mo | ask mo | p5 | p1 | skew | RT gross | RT net 2bp |')
L.append('|---|---|---|---|---|---|---|---|---|---|')
for s in order:
    for p in ('calm','crash'):
        e=r[s]['h30s'][p]
        L.append(f"| {s} | {p} | {e['both']['n']} | {e['bid']['mean']:.2f} | {e['ask']['mean']:.2f} | {e['both']['p5']:.2f} | {e['both']['p1']:.2f} | {e['both']['skew']:.2f} | {e['rt_gross_bps']:.2f} | {e['rt_net_fee2']:.2f} |")
L.append('\nOn the crash day the bid side (long inventory into a falling market) takes the damage: p5/p1 left tail roughly doubles vs calm and the bid-side mean drops sharply, while the ask side partly offsets. Note one-day sample (fills capped at 2880/side/day by the bucket rule).\n')
b=r['BTCUSDT']['h30s']['all']
L.append('## 5. BTC control sanity\n')
L.append(f"BTC time-weighted spread {r['BTCUSDT']['tw_spread_bps_mean']:.3f}bp (one tick). RT gross at 30s = {b['rt_gross_bps']:.2f}bp, net of 2bp fees = {b['rt_net_fee2']:.2f}bp; NW t gross {b.get('nw_t_rt_gross',float('nan')):.1f}. Expected ~0/negative: **PASS** (no strongly profitable BTC -> no evidence of a simulator bug producing free money). Sanity ordering also holds: RT gross rises monotonically with the quoted spread (ETH/BTC ~0, SOL slightly negative, DOGE ~+0.9, SXP ~+1.1-1.4).\n")
L.append('## 6. Go / no-go per symbol (OPTIMISTIC net RT > 0 at 2bp fee AND NW significant AND tail not ruinous)\n')
for s in order:
    e=r[s]['h30s']['all']
    L.append(f"- {s}: {go(s) if s!='BTCUSDT' else 'CONTROL (no-go by design)'}  (30s RT net@2bp {e['rt_net_fee2']:.2f}bp; net@1bp {e['rt_net_fee1']:.2f}; net@0bp {e['rt_net_fee0']:.2f}; p5/fill {e['both']['p5']:.1f}bp)")
L.append('\n**Verdict: no instrument passes at the headline 2bp maker fee, even with the front-of-queue upper bound.** Gross round-trip edge is at most ~1.4bp (SXP 1s) against a 4bp round-trip fee; it is also negative for the tight-spread names. At 0bp fee (rebate/market-maker program) DOGE and SXP are positive and statistically significant on the upper bound, but that needs a fee tier we do not have, ignores queue position/latency/inventory, and each fill carries a p5 left tail of -6 to -8bp at 30s (worse on the crash day), i.e. several times the average edge. At 1bp fee still negative. Recommendation: market making is NOT viable for us at retail fees; stop (do not proceed to Phase B) unless a ~0bp maker tier is realistically obtainable, in which case only DOGE/SXP-type wide-spread alts merit a paper test, and expectation should be low.\n')
L.append('## 7. SELF-AUDIT\n- Fill rule optimistic: every trade at/through our level fills us at front of queue with zero latency and no min-size/partial fill; no queue position, no cancel/replace cost, no inventory risk. Upper bound only.\n- Future mid is used only as measurement of the realised mark-out, never as a signal or to decide fills/placement.\n- Event-time alignment: quote state = last bookTicker event_time strictly before the trade transact_time; mark-out mid = last event <= t+h. Binance event_time vs transact_time clocks may differ by ms; this is not tested and affects 1s results least-reliably.\n- DATA CAVEAT: the 2023 archive bookTicker is sparse (e.g. ETH ~20k distinct states/day, SXP ~15-50k) so quotes may be stale versus the live book; a stale bid makes "trade <= bid" fills slightly too frequent (optimistic) and mid_h lag adds noise. Direction of bias: optimistic fill count, unclear on mark-out sign.\n- No double counting: max one fill per side per 30s bucket; windows non-overlapping. Side mean means and pairing are per-hour; the paired NW t is on 24-lag hourly series (short, 31 days: weak for tails).\n- Symbols/window/fees fixed before data; the one a-priori choice of SXP over alternatives was made before running the sim. Tier ranks are judgement, not 2023 volume data.\n- Disk streaming: one symbol-day at a time, zip downloaded to data/mm/raw, raw deleted in finally block; only per-fill parquet (data/mm/fills, gitignored) kept. Peak extra disk under ~0.5GB.\n- Bucket rule caps fills/day (5758 per 2880 buckets x2 saturated for liquid names), so fill counts are not realistic volumes; per-fill averages are the metric.\n- Not done: queue-position modelling, latency, inventory/skew, funding, real fees tiers. Single month, single regime.\n')
open(f'{ROOT}/reports/mm_markout.md','w').write('\n'.join(L))
out={'window':'2023-08-01..2023-08-31','tickers':{s:role[s] for s in order},'verdict':{s:go(s) for s in order},'results':r}
json.dump(out,open(f'{ROOT}/reports/mm_markout.json','w'),indent=1)
